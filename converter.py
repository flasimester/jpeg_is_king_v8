"""
Core conversion engine: RAW / HEIC / TIFF / PNG / video -> JPEG, WebP, PNG or TIFF.

Can be used as a library (see app.py) or as a CLI:

    python converter.py photo.ARW folder_with_photos -q 85 -s 50 -o out_dir -r
    python converter.py shots/ --format webp -q 80
    python converter.py shots/ --format jpeg --progressive --subsampling 4:4:4
    python converter.py shots/ --format png --png-level 9
    python converter.py shots/ --format tiff --tiff-compression deflate
    python converter.py --selftest [sample.ARW sample.HEIC ...]     # check this installation
"""
from __future__ import annotations

import argparse
import errno
import io
import os
import re
import subprocess
import sys
import threading
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageFile, ImageOps, UnidentifiedImageError

# Input files are the user's own: lift Pillow's decompression-bomb limit so huge panoramas
# and scans (above ~89 million pixels) open instead of warning or failing.
Image.MAX_IMAGE_PIXELS = None

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # HEIC/HEIF unavailable
    pillow_heif = None

try:
    import rawpy
except ImportError:  # RAW unavailable
    rawpy = None

# --------------------------------------------------------------------------
# Supported formats
# --------------------------------------------------------------------------
RAW_EXTS = {".arw", ".dng", ".cr2", ".cr3", ".nef", ".raf", ".orf", ".rw2"}
HEIF_EXTS = {".heic", ".heif"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp"}
VIDEO_EXTS = {".mov", ".mp4", ".m4v", ".avi", ".mkv"}
ALL_EXTS = RAW_EXTS | HEIF_EXTS | IMAGE_EXTS | VIDEO_EXTS

# Output formats: key -> (PIL format name, file extension)
OUTPUT_FORMATS = {
    "jpeg": ("JPEG", ".jpg"),
    "webp": ("WEBP", ".webp"),
    "png": ("PNG", ".png"),
    "tiff": ("TIFF", ".tif"),
}
SUBSAMPLING = {"4:4:4": 0, "4:2:2": 1, "4:2:0": 2}
AUTO = "auto"  # pick 4:4:4 or 4:2:0 per image by measuring colour damage
SUBSAMPLING_CHOICES = [AUTO] + list(SUBSAMPLING)
TIFF_COMPRESSIONS = {
    "lzw": "tiff_lzw",
    "deflate": "tiff_adobe_deflate",
    "jpeg": "jpeg",
    "none": "raw",
}

# Auto-detection tuning (see detect_subsampling)
AUTO_PIXEL_ERROR = 24  # a pixel counts as "damaged" if its colour error is above this (0-255 scale)

BUILD_ID = "2026-11-17-final"  # shown in the window title and self-test so you can tell which build runs
DEFAULT_OUT_SUBDIR = "converted"
_ALL_OUT_SUBDIRS = {"converted", "jpeg_output"}  # skipped when scanning folders

VIDEO_TIMEOUT = 120  # seconds FFmpeg may spend on one frame before we give up


# --------------------------------------------------------------------------
# Readable error messages
# --------------------------------------------------------------------------
def friendly_error(e: BaseException) -> str:
    """Turn an exception into a short message a person can act on."""
    name = type(e).__name__
    msg = str(e).strip()
    if isinstance(e, RuntimeError) and not name.startswith("LibRaw"):
        return msg or "Unknown error"  # our own messages are already readable
    if isinstance(e, FileExistsError):
        return "The output location already exists as a file (choose a different output folder)"
    if isinstance(e, FileNotFoundError):
        what = getattr(e, "filename", None)
        return f"File or folder not found: {Path(str(what)).name}" if what else "File or folder not found"
    if isinstance(e, PermissionError):
        return "Permission denied (read-only folder, or the file is open in another program)"
    if isinstance(e, OSError) and e.errno == errno.ENOSPC:
        return "Disk is full"
    if isinstance(e, OSError) and (e.errno == errno.ENAMETOOLONG or getattr(e, "winerror", None) == 206):
        return "File path is too long"
    if isinstance(e, UnidentifiedImageError):
        return "Not a readable image (corrupt, empty, or the wrong file type)"
    if isinstance(e, MemoryError):
        return "Not enough memory for this image (try a smaller Resize %)"
    if name.startswith("LibRaw"):
        return f"RAW file could not be decoded by LibRaw (unsupported camera or corrupt file): {msg[:120]}"
    if isinstance(e, ValueError) and msg:
        return msg
    return f"{name}: {msg[:160]}" if msg else name


def to_long_path(path: str) -> str:
    """Windows: prefix very long absolute paths with \\\\?\\ so they open (limit is otherwise 260 chars)."""
    if len(path) < 240 or path.startswith("\\\\?\\"):
        return path
    if path.startswith("\\\\"):  # UNC share
        return "\\\\?\\UNC\\" + path[2:]
    return "\\\\?\\" + path


def _fs(path: Path):
    """Path to hand to the file system (long-path safe on Windows, unchanged elsewhere)."""
    if os.name == "nt":
        return to_long_path(os.path.abspath(str(path)))
    return path


# --------------------------------------------------------------------------
# FFmpeg lookup (works from source and from a PyInstaller bundle)
# --------------------------------------------------------------------------
_FFMPEG_CACHE: dict = {}
FFMPEG_PROBLEMS: list[str] = []  # why candidate FFmpeg files were rejected (shown when none works)


def _tail(*chunks: bytes) -> str:
    text = " ".join(c.decode("utf-8", "replace").strip() for c in chunks if c)
    lines = [ln.strip() for ln in text.replace("\r", "\n").splitlines() if ln.strip()]
    return lines[-1][:160] if lines else ""


def ffmpeg_works(path: str) -> tuple[bool, str]:
    """Run `ffmpeg -version` and report (ok, reason). A file that merely exists is not enough:
    Chocolatey / Scoop 'shims' are tiny launchers that fail with "Could not read shim file"
    as soon as they are copied away from their package folder."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        p = subprocess.run([path, "-version"], stdin=subprocess.DEVNULL, capture_output=True,
                           creationflags=flags, timeout=30)
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except OSError as e:
        return False, str(e)
    first = p.stdout.decode("utf-8", "replace").lstrip()[:40].lower()
    if p.returncode == 0 and first.startswith("ffmpeg version"):
        return True, first.splitlines()[0] if first else ""
    return False, _tail(p.stderr, p.stdout) or f"exit code {p.returncode}"


def resolve_shim(path: str) -> str | None:
    """If `path` is a Scoop or Chocolatey shim, return the real program it points to."""
    p = Path(path)
    sidecar = p.with_suffix(".shim")  # Scoop: ffmpeg.shim contains   path = "C:\\...\\ffmpeg.exe"
    if sidecar.is_file():
        try:
            for line in sidecar.read_text(encoding="utf-8", errors="replace").splitlines():
                m = re.match(r"\s*path\s*=\s*\"?([^\"]+?)\"?\s*$", line)
                if m and Path(m.group(1)).is_file():
                    return m.group(1)
        except OSError:
            pass
    try:  # Chocolatey: `shim --shimgen-noop` prints   Target: 'C:\\...\\ffmpeg.exe'
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        r = subprocess.run([path, "--shimgen-noop"], stdin=subprocess.DEVNULL, capture_output=True,
                           creationflags=flags, timeout=15)
        m = re.search(r"Target:\s*'([^']+)'", r.stdout.decode("utf-8", "replace"))
        if m and Path(m.group(1)).is_file():
            return m.group(1)
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def usable_ffmpeg(path: str) -> str | None:
    """Return a path to a working FFmpeg for `path` (following a shim if needed), else None."""
    ok, why = ffmpeg_works(path)
    if ok:
        return path
    target = resolve_shim(path)
    if target and target != path:
        ok2, why2 = ffmpeg_works(target)
        if ok2:
            return target
        why = why2
    FFMPEG_PROBLEMS.append(f"{path}: {why}")
    return None


def _ffmpeg_candidates() -> list[str]:
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    found: list[Path] = []
    if getattr(sys, "frozen", False):
        found.append(Path(getattr(sys, "_MEIPASS", "")) / exe)
        found.append(Path(sys.executable).parent / exe)
    here = Path(__file__).resolve().parent
    found += [here / exe, here / "ffmpeg" / exe]
    for d in os.environ.get("PATH", "").split(os.pathsep):  # every PATH entry, not only the first
        if d:
            found.append(Path(d.strip('"')) / exe)
    out, seen = [], set()
    for c in found:
        key = str(c).lower()
        if key not in seen and c.is_file():
            seen.add(key)
            out.append(str(c))
    return out


def find_ffmpeg(refresh: bool = False) -> str | None:
    """Path of an FFmpeg that actually runs (bundled copy first, then the system), or None."""
    if refresh or "path" not in _FFMPEG_CACHE:
        FFMPEG_PROBLEMS.clear()
        found = None
        for c in _ffmpeg_candidates():
            found = usable_ffmpeg(c)
            if found:
                break
        _FFMPEG_CACHE["path"] = found
    return _FFMPEG_CACHE["path"]


def ffmpeg_problem() -> str:
    """Human-readable reason why video is unavailable."""
    if FFMPEG_PROBLEMS:
        return ("an FFmpeg file was found but does not run (" + FFMPEG_PROBLEMS[0] + "). "
                "If it is a Chocolatey/Scoop launcher, rebuild so the real ffmpeg.exe is bundled")
    return "FFmpeg not found (install it, or put ffmpeg.exe next to the app)"


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
@dataclass
class Loaded:
    image: Image.Image
    note: str = ""  # shown to the user, e.g. "embedded preview used"
    icc: bytes | None = None  # colour profile of the source
    mode: str = "RGB"  # mode of the source (decides whether its profile can be kept)
    pre_scale: float = 1.0  # 0.5 when a RAW was already decoded at half size


MAX_SCAN_BYTES = 600 * 1024 * 1024  # largest RAW file we will scan for an embedded preview


def _tiff_orientation(path: Path) -> int:
    """Orientation tag from the first directory of a TIFF-based RAW (DNG ...), 1 when unknown.
    Read directly from the header so it works even when Pillow cannot open the file."""
    import struct

    try:
        with open(_fs(path), "rb") as f:
            head = f.read(8)
            if head[:2] not in (b"II", b"MM") or len(head) < 8:
                return 1
            e = "<" if head[:2] == b"II" else ">"
            (off,) = struct.unpack(e + "I", head[4:8])
            f.seek(off)
            (n,) = struct.unpack(e + "H", f.read(2))
            for _ in range(min(n, 200)):
                tag, typ, cnt, val = struct.unpack(e + "HHI4s", f.read(12))
                if tag == 0x0112 and typ == 3:
                    return struct.unpack(e + "H", val[:2])[0] or 1
    except Exception:  # noqa: BLE001
        pass
    return 1


_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4, 16: 8}


def tiff_directories(data: bytes) -> list[dict]:
    """Walk the TIFF directories of a DNG-like file (main IFD, its SubIFDs and chained IFDs).
    Each entry: {tag: [int values]} for the tags that describe images. Never raises."""
    import struct

    out: list[dict] = []
    if data[:2] not in (b"II", b"MM") or len(data) < 8:
        return out
    e = "<" if data[:2] == b"II" else ">"
    todo = [struct.unpack(e + "I", data[4:8])[0]]
    seen: set[int] = set()
    want = {254, 256, 257, 258, 259, 262, 273, 277, 279, 322, 323, 324, 325, 330, 513, 514}
    while todo and len(out) < 40:
        off = todo.pop(0)
        if off in seen or off <= 0 or off + 2 > len(data):
            continue
        seen.add(off)
        try:
            (n,) = struct.unpack(e + "H", data[off:off + 2])
            tags: dict[int, list[int]] = {}
            for i in range(min(n, 300)):
                p = off + 2 + 12 * i
                tag, typ, cnt = struct.unpack(e + "HHI", data[p:p + 8])
                if tag not in want or typ not in (3, 4, 13, 8, 9):
                    continue
                size = _TYPE_SIZE[typ] * cnt
                start = p + 8 if size <= 4 else struct.unpack(e + "I", data[p + 8:p + 12])[0]
                if cnt > 4096 or start + size > len(data):
                    continue
                fmt = {3: "H", 8: "h", 4: "I", 13: "I", 9: "i"}[typ]
                tags[tag] = list(struct.unpack(e + fmt * cnt, data[start:start + size]))
            out.append(tags)
            nxt = struct.unpack(e + "I", data[off + 2 + 12 * n:off + 6 + 12 * n])[0]
            todo += tags.get(330, []) + [nxt]
        except Exception:  # noqa: BLE001
            continue
    return out


def describe_dng(path: Path) -> str:
    """Text description of the images inside a RAW file (for bug reports): `converter.py --inspect FILE`."""
    data = Path(_fs(path)).read_bytes()
    names = {2: "RGB", 6: "YCbCr", 1: "gray", 32803: "CFA(raw)", 34892: "LinearRaw", 0: "WhiteIsZero"}
    comp = {1: "none", 6: "old-JPEG", 7: "JPEG", 8: "deflate", 34892: "lossy-JPEG(DNG)", 52546: "JPEG-XL"}
    lines = [f"{path.name}: {len(data):,} bytes"]
    for i, t in enumerate(tiff_directories(data)):
        w, h = (t.get(256) or [0])[0], (t.get(257) or [0])[0]
        lines.append(f"  image {i}: {w}x{h}  subfile={(t.get(254) or ['-'])[0]}  "
                     f"photometric={names.get((t.get(262) or [-1])[0], (t.get(262) or ['?'])[0])}  "
                     f"compression={comp.get((t.get(259) or [-1])[0], (t.get(259) or ['?'])[0])}  "
                     f"samples={(t.get(277) or ['?'])[0]}  tiled={324 in t}")
    return "\n".join(lines)


def describe_compact(path: Path) -> str:
    """One short line listing what a RAW file contains (shown in the error when nothing is usable)."""
    try:
        data = Path(_fs(path)).read_bytes()
    except OSError:
        return ""
    comp = {1: "raw", 6: "oldJPEG", 7: "JPEG", 8: "deflate", 34892: "lossyJPEG", 52546: "JPEG-XL"}
    photo = {2: "RGB", 6: "YCbCr", 1: "gray", 32803: "CFA", 34892: "linear"}
    parts = []
    for t in tiff_directories(data)[:6]:
        w, h = (t.get(256) or [0])[0], (t.get(257) or [0])[0]
        if w:
            c, p = (t.get(259) or [0])[0], (t.get(262) or [0])[0]
            parts.append(f"{w}x{h} {photo.get(p, p)}/{comp.get(c, c)}{'/tiled' if 324 in t else ''}")
    jpgs, pos = [], 0
    while len(jpgs) < 8:
        pos = data.find(b"\xff\xd8\xff", pos)
        if pos < 0:
            break
        try:
            with Image.open(io.BytesIO(data[pos:])) as im:
                if im.format == "JPEG":
                    jpgs.append(f"{im.width}x{im.height} {im.mode}")
        except Exception:  # noqa: BLE001
            pass
        pos += 3
    return "contents: " + "; ".join(parts) + (" | JPEGs: " + ", ".join(jpgs) if jpgs else "")


def _structured_preview(data: bytes) -> Image.Image | None:
    """The largest full-colour JPEG preview that the file's own directories declare."""
    best: tuple[int, Image.Image] | None = None
    for t in tiff_directories(data):
        photo = (t.get(262) or [0])[0]
        comp = (t.get(259) or [0])[0]
        if 324 in t or photo not in (2, 6) or comp not in (6, 7):
            continue  # tiles / raw sensor data / lossless-JPEG raw: not a preview
        if 513 in t and 514 in t:
            off, ln = t[513][0], t[514][0]
        elif 273 in t and 279 in t and len(t[273]) == 1:
            off, ln = t[273][0], t[279][0]
        else:
            continue
        try:
            with Image.open(io.BytesIO(data[off:off + ln])) as im:
                if im.format != "JPEG" or im.mode not in ("RGB", "YCbCr"):
                    continue
                im.load()
                img = im.convert("RGB")
        except Exception:  # noqa: BLE001
            continue
        if best is None or img.width * img.height > best[0]:
            best = (img.width * img.height, img)
    return best[1] if best else None


def _tiff_preview(path: Path) -> Image.Image | None:
    """Colour image stored as a normal TIFF page (e.g. JPEG-in-TIFF strips with shared tables, as in
    iPhone ProRAW DNGs): let Pillow's TIFF reader decode it. Raw / JPEG-XL pages fail and are skipped."""
    best: tuple[int, Image.Image] | None = None
    try:
        with Image.open(_fs(path)) as im:
            if im.format != "TIFF":
                return None
            for n in range(min(getattr(im, "n_frames", 1), 8)):
                try:
                    im.seek(n)
                    if im.mode not in ("RGB", "YCbCr") or im.width * im.height < 160 * 120:
                        continue
                    im.load()
                    cand = im.convert("RGB")
                    if best is None or cand.width * cand.height > best[0]:
                        best = (cand.width * cand.height, cand)
                except Exception:  # noqa: BLE001
                    continue
    except Exception:  # noqa: BLE001
        return None
    return best[1] if best else None


def extract_embedded_jpeg(path: Path) -> Image.Image | None:
    """Find the best JPEG preview inside a RAW file without using the RAW decoder.

    1. previews declared by the file's TIFF structure (full colour, not raw sensor data);
    2. otherwise any full-colour JPEG found by scanning for JPEG headers. Greyscale JPEGs are
       ignored on purpose: inside a DNG they are raw sensor / depth data and look washed out."""
    if path.stat().st_size > MAX_SCAN_BYTES:
        return None
    data = Path(_fs(path)).read_bytes()
    img = _structured_preview(data)
    if img is None:
        img = _tiff_preview(path)
    if img is None:
        best: tuple[int, int] | None = None  # (pixels, offset) of the largest colour JPEG found
        pos, tries = 0, 0
        while tries < 64:
            pos = data.find(b"\xff\xd8\xff", pos)
            if pos < 0:
                break
            tries += 1
            try:
                with Image.open(io.BytesIO(data[pos:])) as im:
                    px = im.width * im.height
                    if im.format == "JPEG" and im.mode in ("RGB", "YCbCr") and px >= 160 * 120 \
                            and (best is None or px > best[0]):
                        best = (px, pos)
            except Exception:  # noqa: BLE001
                pass
            pos += 3
        if best is None:
            return None
        try:
            with Image.open(io.BytesIO(data[best[1]:])) as im:
                im.load()
                img = im.convert("RGB")
        except Exception:  # noqa: BLE001
            return None
    own = int(img.getexif().get(0x0112, 1) or 1)
    img = ImageOps.exif_transpose(img) or img
    if own == 1:  # the preview carries no rotation of its own: use the RAW file's
        T = Image.Transpose
        method = {2: T.FLIP_LEFT_RIGHT, 3: T.ROTATE_180, 4: T.FLIP_TOP_BOTTOM, 5: T.TRANSPOSE,
                  6: T.ROTATE_270, 7: T.TRANSVERSE, 8: T.ROTATE_90}.get(_tiff_orientation(path))
        if method is not None:
            img = img.transpose(method)
    return img


def _preview_loaded(path: Path, why: str) -> Loaded | None:
    img = extract_embedded_jpeg(path)
    if img is None:
        return None
    return Loaded(img, note=f"RAW not supported by LibRaw ({why}): embedded preview used, "
                            f"{img.size[0]}x{img.size[1]}")


def _load_raw(path: Path, half: bool = False) -> Loaded:
    """Develop a RAW file. Order: LibRaw -> LibRaw's own preview -> JPEG found inside the file."""
    if rawpy is None:
        raise RuntimeError("RAW support is missing: the 'rawpy' package is not installed")
    try:
        raw_ctx = rawpy.imread(str(_fs(path)))
    except Exception as open_error:  # noqa: BLE001
        # e.g. "Unsupported file format or not RAW file": newer iPhone ProRAW DNGs (JPEG XL)
        why = (str(open_error).strip() or type(open_error).__name__)[:60]
        fallback = _preview_loaded(path, why)
        if fallback is not None:
            return fallback
        raise RuntimeError(f"DNG: {describe_compact(path)} | no colour preview; LibRaw: "
                           f"{str(open_error)[:50]}"[:420]) from None
    failure: Exception | None = None
    thumb_note = ""
    with raw_ctx as raw:
        try:
            rgb = raw.postprocess(use_camera_wb=True, output_bps=8, half_size=half)
            return Loaded(Image.fromarray(rgb), pre_scale=0.5 if half else 1.0)
        except Exception as decode_error:  # noqa: BLE001
            failure = decode_error  # (the name itself is deleted when this block ends)
            # Demosaicing failed: fall back to the preview JPEG embedded in the RAW file
            try:
                thumb = raw.extract_thumb()
                if thumb.format == rawpy.ThumbFormat.JPEG:
                    img = Image.open(io.BytesIO(thumb.data))
                    img.load()
                    img = ImageOps.exif_transpose(img)
                else:
                    img = Image.fromarray(thumb.data)
                return Loaded(img, note="RAW could not be decoded: embedded low-resolution preview used")
            except Exception as thumb_error:  # noqa: BLE001
                thumb_note = f"thumb: {type(thumb_error).__name__}"
    fallback = _preview_loaded(path, "decode failed")
    if fallback is not None:
        return fallback
    raise RuntimeError(f"DNG: {describe_compact(path)} | no colour preview; LibRaw: "
                       f"{str(failure)[:50]} {thumb_note}"[:420]) from None


HDR_TONEMAP = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
               "zscale=t=bt709:m=bt709:r=pc,format=gbrp")


def is_hdr_video(ffmpeg: str, path: Path) -> bool:
    """True for HLG / PQ footage (iPhone Dolby Vision / HDR video): FFmpeg lists the transfer in its banner."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        p = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)], stdin=subprocess.DEVNULL,
                           capture_output=True, creationflags=flags, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    text = p.stderr.decode("utf-8", "replace").lower()
    return "arib-std-b67" in text or "smpte2084" in text


def _run_ffmpeg_frame(ffmpeg: str, path: Path, seconds: float, tonemap: bool = False) -> subprocess.CompletedProcess:
    cmd = [ffmpeg, "-v", "error", "-nostdin"]
    if seconds > 0:
        cmd += ["-ss", f"{seconds:.3f}"]
    cmd += ["-i", str(path), "-an", "-sn", "-frames:v", "1"]
    if tonemap:
        cmd += ["-vf", HDR_TONEMAP]
    cmd += ["-pix_fmt", "rgb24", "-f", "image2pipe", "-vcodec", "png", "-"]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        # stdin=DEVNULL matters: a windowed (no-console) .exe has no valid stdin handle and
        # subprocess.run would otherwise fail with "WinError 6: The handle is invalid".
        return subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True,
                              creationflags=flags, timeout=VIDEO_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"FFmpeg took longer than {VIDEO_TIMEOUT} s (corrupt file or slow drive?)") from None
    except OSError as e:
        raise RuntimeError(f"FFmpeg could not be started: {e}") from None


def _last_line(data: bytes) -> str:
    lines = [ln.strip() for ln in data.decode("utf-8", "replace").splitlines() if ln.strip()]
    return lines[-1][:160] if lines else ""


def _load_video_frame(path: Path, seconds: float) -> Loaded:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("Video needs FFmpeg: " + ffmpeg_problem())
    note = ""
    tonemapped = False
    proc = None
    if is_hdr_video(ffmpeg, path):  # HDR looks flat and washed out unless it is tone-mapped to SDR
        proc = _run_ffmpeg_frame(ffmpeg, path, seconds, tonemap=True)
        if proc.returncode == 0 and proc.stdout:
            tonemapped = True
        else:
            proc = None  # this FFmpeg build has no zscale/tonemap: use the plain frame
    if proc is None:
        proc = _run_ffmpeg_frame(ffmpeg, path, seconds)
    if (proc.returncode != 0 or not proc.stdout) and seconds > 0:
        # Asked for a moment after the end of the clip: use the first frame instead of failing
        retry = _run_ffmpeg_frame(ffmpeg, path, 0.0)
        if retry.returncode == 0 and retry.stdout:
            proc, note = retry, f"clip is shorter than {seconds:g} s: first frame used"
    if proc.returncode != 0 or not proc.stdout:
        reason = _last_line(proc.stderr) or "no video stream found"
        raise RuntimeError(f"FFmpeg could not read a frame: {reason}")
    img = Image.open(io.BytesIO(proc.stdout))
    img.load()
    if tonemapped:
        note = (note + " · " if note else "") + "HDR tone-mapped"
    return Loaded(img, note=note)


def load_image(path: Path, video_seconds: float = 0.0, half: bool = False) -> Loaded:
    ext = path.suffix.lower()
    if ext in RAW_EXTS:
        return _load_raw(path, half)
    if ext in VIDEO_EXTS:
        return _load_video_frame(path, video_seconds)
    if ext in HEIF_EXTS and pillow_heif is None:
        raise RuntimeError("HEIC/HEIF support is missing: the 'pillow-heif' package is not installed")
    with Image.open(path) as im:
        im.load()
        icc = im.info.get("icc_profile")
        mode = im.mode
        img = ImageOps.exif_transpose(im)  # a copy, safe to use after the file is closed
    return Loaded(img, icc=icc, mode=mode)


# --------------------------------------------------------------------------
# Conversion
# --------------------------------------------------------------------------
def _has_alpha(img: Image.Image) -> bool:
    return img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)


def _prepare(img: Image.Image, keep_alpha: bool) -> Image.Image:
    """Normalise the mode. JPEG flattens transparency onto white; others may keep it."""
    if img.mode in ("I;16", "I;16L", "I;16B", "I"):
        img = img.point(lambda i: i * (1 / 256)).convert("L")
    if _has_alpha(img):
        rgba = img.convert("RGBA")
        if keep_alpha:
            return rgba
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def chroma_damage(img: Image.Image) -> float:
    """Fraction of pixels whose colour would change visibly under 4:2:0 subsampling.

    Simulates what JPEG does (halve the colour resolution, then scale it back up)
    and counts the pixels whose Cb/Cr colour error exceeds AUTO_PIXEL_ERROR.
    Smooth photos score close to 0; thin coloured lines, coloured text and
    screenshots score high.
    """
    from PIL import ImageChops

    w, h = img.size
    if w < 2 or h < 2:
        return 0.0
    _, cb, cr = img.convert("YCbCr").split()
    half = ((w + 1) // 2, (h + 1) // 2)
    diffs = []
    for ch in (cb, cr):
        approx = ch.resize(half, Image.Resampling.BOX).resize((w, h), Image.Resampling.BILINEAR)
        diffs.append(ImageChops.difference(ch, approx))
    worst = ImageChops.lighter(diffs[0], diffs[1])
    hist = worst.histogram()
    return sum(hist[AUTO_PIXEL_ERROR + 1:]) / float(w * h)


def damage_limit(sensitivity: int) -> float:
    """Damage fraction above which an image gets 4:4:4. Sensitivity 1-100:
    higher = more eager to choose 4:4:4 (1 -> ~10 %, 50 -> 1 %, 100 -> 0.1 %)."""
    s = max(1, min(100, int(sensitivity)))
    return 10 ** (-1 - 2 * s / 100)


def detect_subsampling(img: Image.Image, sensitivity: int = 50) -> tuple[str, float]:
    """Return ("4:4:4" | "4:2:0", damage_fraction) for an RGB image."""
    dmg = chroma_damage(img)
    return ("4:4:4" if dmg > damage_limit(sensitivity) else "4:2:0"), dmg


@dataclass
class Result:
    src: Path
    status: str  # "ok" | "skipped" | "error"
    dst: Path | None = None
    message: str = ""
    in_size: int = 0
    out_size: int = 0


_PLAN_LOCK = threading.Lock()  # output names are planned one at a time, even with several workers


# Tags that describe how the RAW pixels are stored (not the photo) or are huge: never copied into a JPEG.
_RAW_EXIF_DROP = {0x00FE, 0x00FF, 0x0100, 0x0101, 0x0102, 0x0103, 0x0106, 0x0111, 0x0115, 0x0116,
                  0x0117, 0x011C, 0x0142, 0x0143, 0x0144, 0x0145, 0x014A, 0x0201, 0x0202, 0x02BC, 0x8649, 0x8773}
_EXIF_IFD_DROP = {0x927C, 0xA002, 0xA003, 0x9286}  # MakerNote (can exceed JPEG's 64 KB limit), pixel dims, comments


def read_raw_exif(path: Path, preview: Image.Image | None = None) -> bytes:
    """Camera, lens, date, exposure ... from a RAW file, as JPEG-ready EXIF bytes (b"" when none is found).

    Most RAW formats (DNG, ARW, NEF ...) are TIFF files: Pillow reads their first directory directly.
    Otherwise the EXIF of an embedded preview JPEG is used. Never raises."""
    candidates = []
    try:
        with Image.open(_fs(path)) as im:
            candidates.append(im.getexif())
    except Exception:  # noqa: BLE001
        pass
    if preview is not None:
        try:
            candidates.append(preview.getexif())
        except Exception:  # noqa: BLE001
            pass
    def thumb_exif():
        """Last resort: EXIF of the preview JPEG that LibRaw finds inside the file."""
        if rawpy is None:
            return
        try:
            with rawpy.imread(str(_fs(path))) as raw:
                thumb = raw.extract_thumb()
                if thumb.format == rawpy.ThumbFormat.JPEG:
                    with Image.open(io.BytesIO(thumb.data)) as t:
                        yield t.getexif()
        except Exception:  # noqa: BLE001
            return

    import itertools

    for ex in itertools.chain(candidates, thumb_exif()):
        try:
            if not ex or not any(t in ex for t in (0x010F, 0x0110, 0x0132)):  # make / model / date
                try:
                    if not ex.get_ifd(0x8769):
                        continue
                except Exception:  # noqa: BLE001
                    continue
            out = Image.Exif()
            for tag, val in ex.items():
                if tag in _RAW_EXIF_DROP or tag >= 0xC000 or tag in (0x8769, 0x8825, 0xA005):  # DNG blobs, sub-IFDs
                    continue
                out[tag] = val
            sub = ex.get_ifd(0x8769)
            if sub:
                target = out.get_ifd(0x8769)
                for tag, val in sub.items():
                    if tag not in _EXIF_IFD_DROP:
                        target[tag] = val
            gps = ex.get_ifd(0x8825)
            if gps:
                out.get_ifd(0x8825).update(gps)
            out[0x0112] = 1  # the picture is already upright
            data = out.tobytes()
            if len(data) < 60000:  # a JPEG EXIF block cannot exceed 64 KB
                return data
        except Exception:  # noqa: BLE001
            continue
    return b""


def _strip_gps_bytes(data: bytes) -> bytes:
    """EXIF bytes with the GPS block removed."""
    try:
        ex = Image.Exif()
        ex.load(data)
        if 0x8825 in ex:
            del ex[0x8825]
        return ex.tobytes()
    except Exception:  # noqa: BLE001
        return b""


def plan_output(src: Path, out_dir: Path | None, used: set[str], fmt: str = "jpeg") -> Path:
    """Work out the destination path, avoiding clashes inside one batch."""
    out_ext = OUTPUT_FORMATS[fmt][1]
    folder = Path(out_dir) if out_dir else src.parent / DEFAULT_OUT_SUBDIR
    suffix = "_frame" if src.suffix.lower() in VIDEO_EXTS else ""
    dst = folder / f"{src.stem}{suffix}{out_ext}"
    try:
        if dst.resolve() == src.resolve():
            dst = folder / f"{src.stem}_converted{out_ext}"
    except OSError:
        pass
    base, n = dst, 1
    while str(dst).lower() in used:
        dst = base.with_name(f"{base.stem}_{n}{out_ext}")
        n += 1
    used.add(str(dst).lower())
    return dst


def build_save_kwargs(
    fmt: str,
    quality: int,
    progressive: bool,
    subsampling: str,
    optimize: bool,
    lossless: bool,
    png_level: int,
    tiff_compression: str,
) -> dict:
    """Translate the user-facing options into Pillow save() arguments."""
    pil_fmt = OUTPUT_FORMATS[fmt][0]
    kw: dict = {"format": pil_fmt}
    if fmt == "jpeg":
        kw.update(quality=int(quality), optimize=bool(optimize), progressive=bool(progressive))
        if subsampling in SUBSAMPLING:
            kw["subsampling"] = SUBSAMPLING[subsampling]
    elif fmt == "webp":
        kw.update(quality=int(quality), lossless=bool(lossless), method=6)
    elif fmt == "png":
        # Note: Pillow's optimize=True forces level 9 and would override png_level,
        # so PNG is controlled by compress_level alone.
        kw.update(compress_level=max(0, min(9, int(png_level))))
    elif fmt == "tiff":
        kw["compression"] = TIFF_COMPRESSIONS.get(tiff_compression, "tiff_lzw")
        if kw["compression"] == "jpeg":
            kw["quality"] = int(quality)
    return kw


def _atomic_save(img: Image.Image, dst: Path, kwargs: dict) -> None:
    """Write to a temporary file and rename it into place, so an interrupted or failed save
    can never leave a half-written file that later runs would treat as already converted."""
    tmp = dst.with_name(dst.name + ".part")
    try:
        try:
            img.save(_fs(tmp), **kwargs)  # format= is always given, so the .part suffix is harmless
        except OSError as e:
            # JPEG "optimize" needs the whole encoded image in one buffer. Very noisy / high-quality
            # images (high ISO at quality 95+) can outgrow Pillow's default: retry with a bigger one.
            if "broken data stream" not in str(e) and "Suspension" not in str(e):
                raise
            ImageFile.MAXBLOCK = max(ImageFile.MAXBLOCK, img.size[0] * img.size[1] * 4)
            img.save(_fs(tmp), **kwargs)
        os.replace(_fs(tmp), _fs(dst))
    except BaseException:
        try:
            os.remove(_fs(tmp))
        except OSError:
            pass
        raise


def convert_file(
    src: Path,
    out_dir: Path | None = None,
    quality: int = 85,
    resize_pct: int = 100,
    overwrite: bool = False,
    keep_exif: bool = True,
    video_seconds: float = 0.0,
    used: set[str] | None = None,
    fmt: str = "jpeg",
    progressive: bool = False,
    subsampling: str = AUTO,
    optimize: bool = True,
    lossless: bool = False,
    png_level: int = 6,
    tiff_compression: str = "lzw",
    sensitivity: int = 50,
    keep_date: bool = True,
    strip_gps: bool = False,
) -> Result:
    src = Path(src)
    used = used if used is not None else set()
    try:
        if fmt not in OUTPUT_FORMATS:
            raise ValueError(f"Unknown output format '{fmt}'")
        if src.is_dir():
            raise ValueError("This is a folder, not a file")
        if not src.is_file():
            raise FileNotFoundError(2, "not found", str(src))
        in_size = src.stat().st_size
        if in_size == 0:
            raise ValueError("The file is empty (0 bytes)")
        with _PLAN_LOCK:
            dst = plan_output(src, out_dir, used, fmt)
        if dst.exists() and dst.stat().st_size > 0 and not overwrite:
            return Result(src, "skipped", dst, "already exists", in_size, dst.stat().st_size)

        ext = src.suffix.lower()
        half = ext in RAW_EXTS and resize_pct <= 50 and rawpy is not None  # RAW: decode at half size (4x faster)
        loaded = load_image(src, video_seconds, half)
        img = loaded.image

        exif_bytes = b""
        if keep_exif and fmt in ("jpeg", "webp", "png") and ext not in RAW_EXTS | VIDEO_EXTS:
            try:
                exif = img.getexif()
                if exif:
                    exif[0x0112] = 1  # orientation already applied
                    if strip_gps and 0x8825 in exif:
                        del exif[0x8825]  # GPS location block
                    exif_bytes = exif.tobytes()
            except Exception:  # noqa: BLE001
                exif_bytes = b""

        if keep_exif and fmt in ("jpeg", "webp", "png") and ext in RAW_EXTS:
            exif_bytes = read_raw_exif(src, img)  # camera / lens / date taken for ARW, DNG, NEF ...
            if exif_bytes and strip_gps:
                exif_bytes = _strip_gps_bytes(exif_bytes)

        img = _prepare(img, keep_alpha=(fmt != "jpeg"))
        scale = resize_pct / 100.0 / loaded.pre_scale
        if abs(scale - 1.0) > 1e-9:
            w, h = img.size
            img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.LANCZOS)

        chroma_note = ""
        if fmt == "jpeg":
            if subsampling == AUTO:
                subsampling, _dmg = detect_subsampling(img, sensitivity)
                chroma_note = f" {subsampling} auto"
            else:
                chroma_note = f" {subsampling}"

        try:
            os.makedirs(_fs(dst.parent), exist_ok=True)
        except OSError as e:
            raise RuntimeError(f"Cannot create the output folder: {friendly_error(e)}") from None
        kwargs = build_save_kwargs(fmt, quality, progressive, subsampling, optimize,
                                   lossless, png_level, tiff_compression)
        if exif_bytes:
            kwargs["exif"] = exif_bytes
        # Keep the source's colour profile (e.g. iPhone Display P3) so colours don't shift.
        # Skipped for CMYK / greyscale / 16-bit sources, whose profile doesn't describe RGB output.
        if loaded.icc and loaded.mode in ("RGB", "RGBA", "P"):
            kwargs["icc_profile"] = loaded.icc
        _atomic_save(img, dst, kwargs)
        if keep_date:  # the converted file gets the original's "modified" time, so date sorting still works
            try:
                st = src.stat()
                os.utime(_fs(dst), (st.st_atime, st.st_mtime))
            except OSError:
                pass

        message = f"{img.size[0]}x{img.size[1]}{chroma_note}"
        if loaded.note:
            message += f" · {loaded.note}"
        return Result(src, "ok", dst, message, in_size, dst.stat().st_size)
    except Exception as e:  # noqa: BLE001
        return Result(src, "error", None, friendly_error(e))


def count_existing_outputs(files, out_dir: Path | None, fmt: str = "jpeg") -> int:
    """How many output files already exist (and would be replaced when overwriting)."""
    used: set[str] = set()
    n = 0
    for f in files:
        try:
            if plan_output(Path(f), out_dir, used, fmt).exists():
                n += 1
        except Exception:  # noqa: BLE001
            continue
    return n


def default_workers() -> int:
    """Files converted at the same time: a few cores, but capped because big RAW files use a lot of memory."""
    return max(1, min(4, (os.cpu_count() or 2) - 1))


def run_batch(jobs, opts: dict, workers: int = 1, on_start: Callable | None = None,
              on_done: Callable | None = None, stop: Callable[[], bool] | None = None) -> dict:
    """Convert (key, path, extra_options) jobs on several threads. Pillow, LibRaw and FFmpeg release
    the GIL while they work, so threads give real speed-ups without the pitfalls of extra processes.
    Callbacks run in the calling thread (on_start in the worker). Returns {"ok", "skipped", "error"}."""
    used: set[str] = set()
    stats = {"ok": 0, "skipped": 0, "error": 0}

    def task(key, path, extra):
        if stop is not None and stop():
            return None
        if on_start is not None:
            on_start(key)
        return key, convert_file(path, used=used, **{**opts, **extra})

    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
        futures = [pool.submit(task, *job) for job in jobs]
        for fut in as_completed(futures):
            res = fut.result()
            if res is None:
                continue
            key, r = res
            stats[r.status] += 1
            if on_done is not None:
                on_done(key, r)
    return stats


# --------------------------------------------------------------------------
# File discovery
# --------------------------------------------------------------------------
def collect_files(paths, recursive: bool = True) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()

    def add(p: Path):
        key = str(p.resolve()).lower()
        if key not in seen:
            seen.add(key)
            found.append(p)

    for raw_p in paths:
        p = Path(raw_p)
        if p.is_file():
            if p.suffix.lower() in ALL_EXTS:
                add(p)
        elif p.is_dir():
            if recursive:
                for root, dirs, files in os.walk(p):
                    dirs[:] = sorted(d for d in dirs if d not in _ALL_OUT_SUBDIRS)
                    for f in sorted(files):
                        fp = Path(root) / f
                        if fp.suffix.lower() in ALL_EXTS:
                            add(fp)
            else:
                for fp in sorted(p.iterdir()):
                    if fp.is_file() and fp.suffix.lower() in ALL_EXTS:
                        add(fp)
    return found


def human(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


# --------------------------------------------------------------------------
# Self-test: what actually works on THIS computer / THIS build
# --------------------------------------------------------------------------
def _sample_picture(w: int = 320, h: int = 240) -> Image.Image:
    from PIL import ImageDraw

    img = Image.new("RGB", (w, h), (30, 60, 120))
    d = ImageDraw.Draw(img)
    d.ellipse((60, 40, 260, 200), fill=(220, 80, 40))
    d.line((0, 0, w, h), fill=(255, 255, 255), width=3)
    return img


def _ffmpeg_version(ffmpeg: str) -> str:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    p = subprocess.run([ffmpeg, "-version"], stdin=subprocess.DEVNULL, capture_output=True,
                       creationflags=flags, timeout=30)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg exited with code {p.returncode}: {_tail(p.stderr, p.stdout) or 'no message'}")
    return p.stdout.decode("utf-8", "replace").splitlines()[0][:100]


def selftest(extra_files=()) -> list[tuple[str, str, str]]:
    """Run real conversions on generated samples. Returns (check, "PASS"|"FAIL"|"SKIP", detail) rows.
    Any extra_files (e.g. a real .ARW or .HEIC from your camera or phone) are converted too."""
    rows: list[tuple[str, str, str]] = []

    def check(name, fn):
        try:
            status, detail = fn()
        except Exception as e:  # noqa: BLE001
            status, detail = "FAIL", friendly_error(e)
        rows.append((name, status, detail))

    import PIL

    frozen = getattr(sys, "frozen", False)
    rows.append(("Environment", "PASS",
                 f"Python {sys.version.split()[0]} · Pillow {PIL.__version__} · "
                 f"{'packaged .exe' if frozen else 'running from source'} · {sys.platform} · build {BUILD_ID}"))

    with tempfile.TemporaryDirectory(prefix="imgconv_selftest_") as tmp:
        tmpdir = Path(tmp)
        out = tmpdir / "out"
        sample = _sample_picture()
        png = tmpdir / "sample.png"
        sample.save(png)

        # --- output formats
        def out_fmt(fmt):
            def run():
                r = convert_file(png, out, overwrite=True, fmt=fmt)
                if r.status != "ok" or r.dst is None:
                    return "FAIL", r.message
                with Image.open(r.dst) as im:
                    if im.size != sample.size:
                        return "FAIL", f"wrong size {im.size}"
                return "PASS", f"{human(r.in_size)} -> {human(r.out_size)}"
            return run

        for fmt in OUTPUT_FORMATS:
            check(f"Output: {fmt.upper()}", out_fmt(fmt))

        # --- input image formats
        def in_fmt(ext, pil_name):
            def run():
                p = tmpdir / f"in_{ext.lstrip('.')}{ext}"
                sample.save(p, format=pil_name)
                r = convert_file(p, out, overwrite=True)
                return ("PASS", r.message) if r.status == "ok" else ("FAIL", r.message)
            return run

        for ext, pil_name in ((".jpg", "JPEG"), (".png", "PNG"), (".tif", "TIFF"), (".webp", "WEBP"),
                              (".bmp", "BMP")):
            check(f"Input: {ext}", in_fmt(ext, pil_name))

        # --- colour profile kept
        def icc_check():
            from PIL import ImageCms

            prof = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
            p = tmpdir / "profile.png"
            sample.save(p, icc_profile=prof)
            r = convert_file(p, out, overwrite=True)
            if r.status != "ok" or r.dst is None:
                return "FAIL", r.message
            with Image.open(r.dst) as im:
                return ("PASS", "colour profile kept") if im.info.get("icc_profile") else ("FAIL", "profile lost")

        check("Colour profile (ICC)", icc_check)

        # --- HEIC / HEIF
        def heic_check():
            if pillow_heif is None:
                return "SKIP", "pillow-heif is not installed: HEIC/HEIF files cannot be opened"
            p = tmpdir / "sample.heic"
            try:
                sample.save(p, format="HEIF")
            except Exception as e:  # noqa: BLE001
                return "SKIP", f"library loaded (v{pillow_heif.__version__}) but cannot create a test file: {e}"
            r = convert_file(p, out, overwrite=True)
            return ("PASS", f"pillow-heif {pillow_heif.__version__}: {r.message}") if r.status == "ok" \
                else ("FAIL", r.message)

        check("HEIC / HEIF", heic_check)

        # --- RAW
        def raw_check():
            if rawpy is None:
                return "SKIP", "rawpy is not installed: RAW files (ARW, DNG ...) cannot be opened"
            return "PASS", (f"rawpy {getattr(rawpy, '__version__', '?')}, LibRaw "
                            f"{getattr(rawpy, 'libraw_version', '?')} loaded "
                            f"(pass a real sample file to test decoding)")

        check("RAW library", raw_check)

        def preview_check():
            fake = tmpdir / "fake.dng"
            buf = io.BytesIO()
            sample.save(buf, format="JPEG")
            fake.write_bytes(b"II*\x00\x08\x00\x00\x00" + b"\x00" * 64 + b"\xff\xd8\xff\xc3junk" + b"\x00" * 300
                             + buf.getvalue())
            img = extract_embedded_jpeg(fake)
            if img is None or img.size != sample.size:
                return "FAIL", "could not find the JPEG preview inside a DNG-like file"
            return "PASS", "preview JPEG found inside RAW-like file (used when LibRaw cannot read a DNG)"

        check("RAW preview fallback", preview_check)

        def batch_check():
            folder = tmpdir / "batch"
            jobs = []
            for sub in ("a", "b"):
                (folder / sub).mkdir(parents=True, exist_ok=True)
                for i in range(4):
                    p = folder / sub / f"pic_{i}.png"  # same names in two folders: outputs must not clash
                    sample.save(p)
                    jobs.append((len(jobs), p, {}))
            stats = run_batch(jobs, dict(out_dir=folder / "out", overwrite=True), workers=3)
            names = {q.name for q in (folder / "out").iterdir()}
            if stats["ok"] != 8 or len(names) != 8:
                return "FAIL", f"parallel batch gave {stats} and {len(names)} distinct output files (expected 8)"
            src = folder / "a" / "pic_0.png"
            os.utime(src, (1_500_000_000, 1_500_000_000))
            r = convert_file(src, folder / "dated", overwrite=True)
            if r.dst is None or int(r.dst.stat().st_mtime) != 1_500_000_000:
                return "FAIL", "the original file date was not kept"
            return "PASS", "8 files on 3 threads without name clashes; original date kept"

        check("Parallel batch", batch_check)

        # --- FFmpeg + video containers
        ffmpeg = find_ffmpeg()

        def ffmpeg_check():
            if not ffmpeg:
                return "FAIL" if FFMPEG_PROBLEMS else "SKIP", "video files cannot be read: " + ffmpeg_problem()
            return "PASS", f"{ffmpeg} · {_ffmpeg_version(ffmpeg)}"

        check("FFmpeg", ffmpeg_check)

        def make_clip(ext):
            p = tmpdir / f"clip{ext}"
            cmd = [ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=2",
                   "-c:v", "mpeg4", "-pix_fmt", "yuv420p"]
            if ext == ".m4v":
                cmd += ["-f", "mp4"]
            cmd.append(str(p))
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            pr = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, creationflags=flags, timeout=60)
            if pr.returncode != 0 or not p.exists():
                raise RuntimeError("could not create a test clip: " + _last_line(pr.stderr))
            return p

        def video_check(ext):
            def run():
                if not ffmpeg:
                    return "SKIP", "FFmpeg not found"
                clip = make_clip(ext)
                r = convert_file(clip, out, overwrite=True)
                if r.status != "ok":
                    return "FAIL", r.message
                r2 = convert_file(clip, out, overwrite=True, video_seconds=1.0)
                if r2.status != "ok":
                    return "FAIL", f"frame at 1 s: {r2.message}"
                r3 = convert_file(clip, out, overwrite=True, video_seconds=30.0)  # beyond the end
                if r3.status != "ok":
                    return "FAIL", f"frame past the end: {r3.message}"
                return "PASS", "first frame, frame at 1 s, and past-the-end fallback all OK"
            return run

        for ext in (".mp4", ".mov", ".m4v", ".avi", ".mkv"):
            check(f"Video: {ext}", video_check(ext))

        # --- error handling: bad input must give a message, never a crash
        def bad_input():
            bad = []
            for name, data in (("empty.png", b""), ("garbage.png", b"definitely not an image"),
                               ("empty.mp4", b""), ("garbage.heic", b"nope"), ("garbage.arw", b"nope")):
                p = tmpdir / name
                p.write_bytes(data)
                r = convert_file(p, out, overwrite=True)
                if r.status != "error" or not r.message:
                    bad.append(f"{name} -> {r.status}")
            r = convert_file(tmpdir / "missing.jpg", out)
            if r.status != "error":
                bad.append("missing file not reported")
            if bad:
                return "FAIL", "; ".join(bad)
            return "PASS", "corrupt, empty and missing files each give a readable error message"

        check("Error handling", bad_input)

        # --- your own sample files
        for f in extra_files:
            f = Path(f)

            def run(f=f):
                r = convert_file(f, out, overwrite=True)
                return ("PASS", f"{r.message} ({human(r.in_size)} -> {human(r.out_size)})") \
                    if r.status == "ok" else ("FAIL", r.message)

            check(f"Sample: {f.name}", run)
    return rows


def format_report(rows) -> str:
    width = max(len(r[0]) for r in rows)
    lines = ["jpeg_is_king self-test", "=" * 22]
    for name, status, detail in rows:
        lines.append(f"[{status}] {name.ljust(width)}  {detail}")
    n = {s: sum(1 for r in rows if r[1] == s) for s in ("PASS", "FAIL", "SKIP")}
    lines += ["", f"Result: {n['PASS']} passed, {n['FAIL']} failed, {n['SKIP']} skipped"]
    if n["SKIP"]:
        lines.append("Skipped items are formats this computer / build cannot handle (see the detail).")
    return "\n".join(lines)


def run_selftest_cli(extra_files=()) -> int:
    """Print the report (when there is a console) and also save selftest.txt next to the program."""
    rows = selftest(extra_files)
    text = format_report(rows)
    try:
        if sys.stdout:  # a windowed .exe has no console
            print(text)
    except Exception:  # noqa: BLE001
        pass
    folder = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    try:
        (folder / "selftest.txt").write_text(text + "\n", encoding="utf-8")
    except OSError:
        pass
    return 1 if any(r[1] == "FAIL" for r in rows) else 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Convert RAW/HEIC/TIFF/PNG/video to JPEG, WebP, PNG or TIFF")
    ap.add_argument("--inspect", action="store_true", help="describe the images inside RAW/DNG files and exit")
    ap.add_argument("inputs", nargs="*", help="files and/or folders")
    ap.add_argument("-o", "--out", help=f"output folder (default: a '{DEFAULT_OUT_SUBDIR}' folder next to each file)")
    ap.add_argument("-f", "--format", choices=list(OUTPUT_FORMATS), default="jpeg", help="output format (default jpeg)")
    ap.add_argument("-q", "--quality", type=int, default=85, help="quality 1-100 for JPEG/WebP/TIFF-jpeg (default 85)")
    ap.add_argument("-s", "--resize", type=int, default=100, help="resize percent 10-100 (default 100)")
    ap.add_argument("-r", "--recursive", action="store_true", help="scan folders recursively")
    ap.add_argument("--overwrite", action="store_true", help="overwrite existing output files")
    ap.add_argument("--no-exif", action="store_true", help="do not copy EXIF data")
    ap.add_argument("--video-time", type=float, default=0.0, help="video frame position in seconds (default 0)")
    ap.add_argument("--progressive", action="store_true", help="JPEG: progressive encoding")
    ap.add_argument("--subsampling", choices=SUBSAMPLING_CHOICES, default=AUTO,
                    help="JPEG: chroma subsampling. 'auto' (default) picks 4:4:4 or 4:2:0 per image; "
                         "4:4:4 = best colour, biggest file")
    ap.add_argument("--sensitivity", type=int, default=50,
                    help="JPEG auto subsampling: 1-100, higher = more images get 4:4:4 (default 50)")
    ap.add_argument("--no-optimize", action="store_true", help="JPEG: disable the extra optimisation pass")
    ap.add_argument("--lossless", action="store_true", help="WebP: lossless mode (quality then means effort)")
    ap.add_argument("--png-level", type=int, default=6, help="PNG: zlib compression level 0-9 (default 6)")
    ap.add_argument("--tiff-compression", choices=list(TIFF_COMPRESSIONS), default="lzw",
                    help="TIFF: compression method (default lzw)")
    ap.add_argument("--no-keep-date", action="store_true", help="do not copy the original's modified date")
    ap.add_argument("--strip-gps", action="store_true", help="remove GPS location from copied EXIF data")
    ap.add_argument("-j", "--workers", type=int, default=0,
                    help="files converted at the same time (default: automatic, up to 4)")
    ap.add_argument("--selftest", action="store_true",
                    help="check this installation (formats, FFmpeg, RAW / HEIC libraries); "
                         "any inputs given are converted as extra samples")
    a = ap.parse_args(argv)
    if a.inspect:
        for f in a.inputs:
            print(describe_dng(Path(f)))
        return 0

    if a.selftest:
        return run_selftest_cli(a.inputs)
    if not a.inputs:
        ap.error("give at least one file or folder (or use --selftest)")

    quality = max(1, min(100, a.quality))
    resize = max(10, min(100, a.resize))
    files = collect_files(a.inputs, a.recursive)
    if not files:
        print("No supported files found.")
        return 1

    opts = dict(
        out_dir=Path(a.out) if a.out else None, quality=quality, resize_pct=resize, overwrite=a.overwrite,
        keep_exif=not a.no_exif, video_seconds=a.video_time, fmt=a.format, progressive=a.progressive,
        subsampling=a.subsampling, optimize=not a.no_optimize, lossless=a.lossless, png_level=a.png_level,
        tiff_compression=a.tiff_compression, sensitivity=max(1, min(100, a.sensitivity)),
        keep_date=not a.no_keep_date, strip_gps=a.strip_gps,
    )
    done = [0]

    def report(key, r):
        done[0] += 1
        tag = {"ok": "OK  ", "skipped": "SKIP", "error": "FAIL"}[r.status]
        extra = f"{human(r.in_size)} -> {human(r.out_size)}" if r.status == "ok" else r.message
        print(f"[{done[0]}/{len(files)}] {tag} {r.src.name}  {extra}")

    stats = run_batch([(i, f, {}) for i, f in enumerate(files)], opts,
                      a.workers if a.workers > 0 else default_workers(), on_done=report)
    errors = stats["error"]
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
