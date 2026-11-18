"""
Build a standalone Windows program with FFmpeg bundled inside, then test the result.

    python build_exe.py                          # one file: dist\\jpeg_is_king.exe
    python build_exe.py --onefile                # one .exe instead of a folder (slower to start)
    python build_exe.py --ffmpeg C:\\path\\ffmpeg.exe
    python build_exe.py --sample C:\\photos\\DSC01741.ARW --sample C:\\photos\\IMG_0001.HEIC

What it does, in order:
  1. Checks that Pillow, rawpy, pillow-heif and PyInstaller are installed. (A build made without
     rawpy / pillow-heif would silently produce a program that cannot open RAW / HEIC files.)
  2. Finds or downloads ffmpeg.exe and checks that it runs when copied on its own (Chocolatey and
     Scoop only install small launchers on PATH, which break when bundled: those are skipped).
  3. Builds the program with PyInstaller.
  4. Runs the finished program with --selftest, which converts generated test images and videos
     (and any --sample files you give it) and writes selftest.txt next to the program.
"""
import argparse
import importlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP_NAME = "jpeg_is_king"
FFMPEG_ZIP_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

# Pillow loads its file-format plugins dynamically, so PyInstaller cannot see them: list them.
PIL_PLUGINS = ["JpegImagePlugin", "PngImagePlugin", "TiffImagePlugin", "WebPImagePlugin",
               "BmpImagePlugin", "MpoImagePlugin", "GifImagePlugin", "IcoImagePlugin"]


def preflight(skip: bool) -> None:
    needed = [("PIL", "Pillow"), ("rawpy", "rawpy  (RAW files)"), ("pillow_heif", "pillow-heif  (HEIC/HEIF files)"),
              ("PyInstaller", "pyinstaller")]
    missing = []
    for module, label in needed:
        try:
            importlib.import_module(module)
        except Exception as e:  # noqa: BLE001
            missing.append(f"  - {label}: {type(e).__name__}: {e}")
    if missing and not skip:
        sys.exit("Cannot build: these packages are missing or broken:\n" + "\n".join(missing) +
                 "\n\nInstall them with:  python -m pip install -r requirements.txt\n"
                 "(If rawpy or pillow-heif fail to install, your Python version may be too new for their "
                 "pre-built packages: use Python 3.11-3.13.)\n"
                 "Use --skip-checks to build anyway without those formats.")
    if missing:
        print("WARNING: building without:\n" + "\n".join(missing))


def works_alone(path: Path) -> tuple[bool, str]:
    """Copy the file to an empty folder and run it there. This is how it will run inside the
    program, away from its package folder: Chocolatey / Scoop launchers ("shims") and builds that
    need DLLs next to them fail this test even though `ffmpeg -version` works in a terminal."""
    import converter as cv

    with tempfile.TemporaryDirectory(prefix="ffcheck_") as tmp:
        copy = Path(tmp) / path.name
        shutil.copy2(path, copy)
        ok, why = cv.ffmpeg_works(str(copy))
    return ok, why


def accept(path: Path, label: str) -> Path | None:
    """Return a bundle-able ffmpeg for `path` (following shims) or None, explaining why not."""
    import converter as cv

    for candidate in (path, cv.resolve_shim(str(path))):
        if not candidate:
            continue
        candidate = Path(candidate)
        ok, why = works_alone(candidate)
        if ok:
            if candidate != path:
                print(f"  {label}: {path} is a launcher (shim); using the real program {candidate}")
            return candidate
        print(f"  {label}: {candidate} cannot be bundled ({why})")
    return None


def download_ffmpeg() -> Path:
    print("Downloading a standalone FFmpeg (~80 MB) from gyan.dev ...")
    dest_dir = HERE / "ffmpeg"
    dest_dir.mkdir(exist_ok=True)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            zpath = Path(tmp) / "ffmpeg.zip"
            urllib.request.urlretrieve(FFMPEG_ZIP_URL, zpath)
            with zipfile.ZipFile(zpath) as z:
                member = next(n for n in z.namelist() if n.lower().endswith("/bin/ffmpeg.exe"))
                with z.open(member) as src, open(dest_dir / "ffmpeg.exe", "wb") as out:
                    shutil.copyfileobj(src, out)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Could not download FFmpeg ({e}).\nDownload the 'release essentials' zip from "
                 f"https://www.gyan.dev/ffmpeg/builds/ , unzip it, then run:\n"
                 f"  python build_exe.py --ffmpeg C:\\path\\to\\bin\\ffmpeg.exe")
    return dest_dir / "ffmpeg.exe"


def locate_ffmpeg(explicit: str | None) -> Path:
    """Find an ffmpeg that works when copied on its own; otherwise download one."""
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    if explicit:
        p = Path(explicit)
        if not p.is_file():
            sys.exit(f"ffmpeg not found at {p}")
        good = accept(p, "--ffmpeg")
        if good:
            return good
        sys.exit(f"{p} will not work inside the program (see above). Use the real ffmpeg.exe from the\n"
                 f"'bin' folder of a downloaded FFmpeg build, or omit --ffmpeg to download one.")
    print("Looking for ffmpeg ...")
    candidates = [HERE / exe, HERE / "ffmpeg" / exe]
    candidates += [Path(d.strip('"')) / exe for d in os.environ.get("PATH", "").split(os.pathsep) if d]
    seen = set()
    for c in candidates:
        if c.is_file() and str(c).lower() not in seen:
            seen.add(str(c).lower())
            good = accept(c, "found")
            if good:
                return good
    if os.name != "nt":
        sys.exit("No working ffmpeg found. Install ffmpeg or pass --ffmpeg PATH.")
    good = accept(download_ffmpeg(), "downloaded")
    if not good:
        sys.exit("The downloaded ffmpeg.exe does not run on this computer (see above).")
    return good


def built_program(onedir: bool) -> Path:
    exe = APP_NAME + (".exe" if os.name == "nt" else "")
    return HERE / "dist" / APP_NAME / exe if onedir else HERE / "dist" / exe


def run_selftest(program: Path, samples: list[str]) -> int:
    print(f"\nTesting the built program: {program.name} --selftest ...")
    report = program.parent / "selftest.txt"
    if report.exists():
        report.unlink()
    try:
        p = subprocess.run([str(program), "--selftest", *samples], timeout=600, stdin=subprocess.DEVNULL,
                           capture_output=True)
    except Exception as e:  # noqa: BLE001
        print(f"Could not run the built program: {e}")
        return 1
    if report.exists():
        print(report.read_text(encoding="utf-8"))
    else:
        print("The program did not write selftest.txt (exit code %s). stderr:\n%s" %
              (p.returncode, p.stderr.decode("utf-8", "replace")[-800:]))
        return 1
    return p.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ffmpeg", help="path to ffmpeg.exe to bundle")
    ap.add_argument("--console", action="store_true", help="keep a console window (for debugging)")
    ap.add_argument("--onefile", action="store_true",
                    help="build a single .exe instead of a folder (easier to share, but it unpacks ~100 MB "
                         "every time it starts, so it opens slowly)")
    ap.add_argument("--onedir", action="store_true", help="(default) build a folder: dist\\jpeg_is_king\\jpeg_is_king.exe")
    ap.add_argument("--sample", action="append", default=[],
                    help="a real .ARW / .HEIC / .MOV ... file to convert during the self-test (repeatable)")
    ap.add_argument("--skip-checks", action="store_true", help="build even if rawpy / pillow-heif are missing")
    ap.add_argument("--no-test", action="store_true", help="do not run the self-test after building")
    a = ap.parse_args()

    if os.name != "nt":
        print("Note: you are not on Windows - PyInstaller builds for the OS it runs on.")

    preflight(a.skip_checks)
    ffmpeg = locate_ffmpeg(a.ffmpeg)
    print(f"Bundling FFmpeg: {ffmpeg}  (tested on its own: it runs)")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile" if a.onefile else "--onedir",
        *([] if a.onefile else ["--contents-directory", "."]),  # launcher and its files in ONE folder (no _internal)
        "--name", APP_NAME,
        "--collect-all", "rawpy",
        "--collect-all", "pillow_heif",
        *(["--collect-all", "tkinterdnd2"] if importlib.util.find_spec("tkinterdnd2") else []),  # drag and drop
        "--add-binary", f"{ffmpeg}{os.pathsep}.",
    ]
    for plugin in PIL_PLUGINS:
        cmd += ["--hidden-import", f"PIL.{plugin}"]
    cmd += ["--hidden-import", "splash", "--hidden-import", "PIL.ImageTk", "--hidden-import", "PIL.ImageFont"]
    icon = HERE / "icon.ico"
    if not icon.exists() and (HERE / "make_icon.py").exists():
        subprocess.call([sys.executable, str(HERE / "make_icon.py")], cwd=HERE)
    if icon.exists():
        cmd += ["--icon", str(icon),
                "--add-data", f"{icon}{os.pathsep}.",
                "--add-data", f"{HERE / 'icon.png'}{os.pathsep}."]
    if not a.console:
        cmd.append("--windowed")
    cmd.append(str(HERE / "app.py"))
    subprocess.check_call(cmd, cwd=HERE)

    program = built_program(not a.onefile)
    print("\nBuilt ->", program)
    if a.no_test:
        return
    code = run_selftest(program, a.sample)
    if code != 0:
        sys.exit("\nSelf-test FAILED: see the [FAIL] lines above. The program was built, but do not rely on "
                 "the failing formats.")
    print("Self-test finished without failures. Skipped items (if any) are formats this build cannot handle.")


if __name__ == "__main__":
    main()
