"""Image converter GUI (RAW / HEIC / video -> JPEG, WebP, PNG, TIFF).  Run: python app.py"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

import converter as cv

FORMAT_LABELS = {"JPEG": "jpeg", "WebP": "webp", "PNG": "png", "TIFF": "tiff"}
GLOBAL_CHOICE = "Global setting"

# ---------------------------------------------------------------------------
# Palette: white canvas, light-grey panel, one blue accent
# ---------------------------------------------------------------------------
C_BG = "#0f1115"
C_PANEL = "#161a21"
C_FIELD = "#1b202a"
C_LINE = "#2a303b"
C_TEXT = "#e6e8ee"
C_MUTED = "#9aa3b5"
C_FAINT = "#667085"
C_ACCENT = "#3b82f6"
C_ACCENT_H = "#2f6fdc"
C_ACCENT_D = "#27447a"
C_BTN = "#212733"
C_BTN_H = "#2d3544"
C_SEL = "#1f3a68"
C_OK = "#4ade80"
C_ERR = "#f87171"
C_WARN_BG = "#3b2f12"
C_WARN_FG = "#fbbf24"
C_TIP_BG = "#2d3544"
C_THUMB = "#3a4252"

# ---------------------------------------------------------------------------
# Help texts shown by the small "i" badges and button tooltips
# ---------------------------------------------------------------------------
TIPS = {
    "add_files": "Pick one or more files to add. Supported: RAW (ARW, DNG, CR2, CR3, NEF, RAF, ORF, RW2), "
                 "HEIC/HEIF, JPG, PNG, TIFF, WebP, BMP and video (MOV, MP4, M4V, AVI, MKV).",
    "add_folder": "Adds every supported file inside a folder (and its subfolders if 'Include subfolders' is on).",
    "recursive": "When on, 'Add folder' also scans all folders inside it. Folders named 'converted' "
                 "(this app's own output) are skipped.",
    "remove": "Removes the selected rows from the list. Nothing is deleted from your disk. Shortcut: Delete key.",
    "clear": "Empties the whole list (including files hidden by a search). Nothing is deleted from your disk.",
    "list": "Double-click a file (or select it and press Enter) to open the original and, if it has already "
            "been converted, the converted image too.\n\nThe 'Chroma override' column shows files that have "
            "their own JPEG colour setting ('—' = follows the global setting).",
    "search": "Type part of a file name to show only the matching files. Case doesn't matter.\n\n"
              "Several words must all match: 'dsc 017'.\nWildcards work: * = any text, ? = one character "
              "(e.g. 'dsc017*').\n\nClear the box to show everything again. Your selection, overrides and "
              "settings are kept.",
    "select_all": "Selects every file currently shown (the ones matching the search). Shortcut: Ctrl+A in the "
                  "list. Then use 'Settings for selected files' below.",
    "ov_chroma": "Give the selected files their own chroma subsampling instead of the global one.\n"
                 "'Global setting' = no override. JPEG output only.",
    "ov_sens": "Tick to give the selected files their own auto sensitivity (1-100). It only has an effect "
               "when their chroma subsampling is 'auto'.",
    "ov_apply": "Applies the chroma / sensitivity choices on this row to every selected file.",
    "ov_reset": "Removes the overrides from the selected files so they follow the global settings again.",
    "format": "JPEG: small and opens everywhere (lossy).\nWebP: about 25-35% smaller than JPEG at the same "
              "quality; newer apps only.\nPNG: lossless, keeps transparency, large for photos.\n"
              "TIFF: lossless / archival, large.",
    "quality": "1-100. Higher = better looking but larger. 80-90 is a good balance; below about 60 artefacts "
               "become visible.\n\nUsed by JPEG, lossy WebP and TIFF with 'jpeg' compression. PNG ignores it.",
    "resize": "Scales width and height to this percentage of the original (10-100%). 50% keeps a quarter of "
              "the pixels. Applied before compression, so files get much smaller.",
    "progressive": "Progressive JPEGs load in passes (blurry to sharp) and are often 2-5% smaller. Very old "
                   "software may not support them.",
    "chroma": "How much colour detail a JPEG keeps.\n\n4:4:4 = full colour detail (largest). Best for text, thin "
              "coloured lines and screenshots.\n4:2:0 = half colour resolution (smallest). Fine for photos.\n"
              "4:2:2 = in between.\nAuto = checks each image and picks 4:4:4 or 4:2:0 for you.",
    "sensitivity": "Only used when chroma is 'auto'. Higher = more images get 4:4:4 (safer for colour, bigger "
                   "files). Lower = more get 4:2:0 (smaller files). Default 50.\n\nThe value shown is the share "
                   "of pixels that would visibly change colour before an image gets 4:4:4. Lower it for very "
                   "noisy high-ISO photos.",
    "optimize": "Extra pass that finds a smaller encoding at identical quality. Slightly slower, usually "
                "2-10% smaller. Leave it on.",
    "lossless": "Saves WebP with no quality loss (much bigger than lossy WebP). The quality slider is ignored.",
    "png": "0 = fastest and largest, 9 = slowest and smallest. PNG is always lossless: the pixels are identical "
           "at every level.",
    "tiff": "lzw / deflate: lossless (deflate is usually smaller).\njpeg: lossy, uses the quality slider.\n"
            "none: uncompressed, very large.",
    "out_dir": "Where converted files are saved. Empty = a 'converted' folder next to each original. "
               "If two files would get the same name, the second becomes name_1, name_2 ...",
    "overwrite": "Off: files that already exist in the output folder are skipped.\nOn: they are replaced.",
    "exif": "Copies camera info (date, camera model, GPS ...) into the new file. Works for non-RAW sources "
            "(HEIC, JPG, PNG, TIFF) when saving JPEG, WebP or PNG. RAW and video sources don't carry it over.",
    "keep_date": "Gives each converted file the original's 'modified' date, so sorting by date still works.",
    "strip_gps": "Removes the GPS location from the copied EXIF data (handy before sharing photos). "
                 "Other camera info is kept when 'Keep EXIF data' is on.",
    "workers": "How many files are converted at the same time. Auto uses a few CPU cores. Lower it if the "
               "computer runs out of memory with very large RAW files.",
    "video": "Which second of a video to grab as the picture (0 = first frame). Applies to MOV, MP4, M4V, "
             "AVI and MKV.",
    "convert": "Converts the files in the list. While a search is active the button says 'Convert shown' and "
               "only the matching files are converted. Stop halts the files still waiting; ones already in progress finish.",
    "open_out": "Opens the output folder you chose, or the folder of the selected / most recently converted "
                "file.",
}


def tip_position(wx, wy, ww, wh, tw, th, sw, sh, margin=8):
    """Where to put a tooltip (tw x th) for a widget at (wx, wy, ww, wh) on a sw x sh screen:
    below the widget by default, moved left / above it if it would run off the screen."""
    x, y = wx, wy + wh + 6
    if x + tw > sw - margin:
        x = max(margin, sw - tw - margin)
    if y + th > sh - margin:
        y = max(margin, wy - th - 6)
    return x, y




class Tooltip:
    """Dark text bubble shown while the mouse is over a widget.
    delay > 0 waits that many ms first (used for buttons); toggle=True lets a click open / close it."""

    def __init__(self, widget, text: str, wrap: int = 340, delay: int = 0, toggle: bool = True):
        self.widget, self.text, self.wrap = widget, text, wrap
        self.delay, self.toggle_on_click = delay, toggle
        self.tip = None
        self._job = None
        widget.bind("<Enter>", self._enter, add="+")
        widget.bind("<Leave>", self._leave, add="+")
        widget.bind("<ButtonPress-1>", self._press, add="+")

    def _enter(self, _event=None):
        if self.tip is not None or self._job is not None:
            return
        if self.delay > 0:
            self._job = self.widget.after(self.delay, self._delayed)
        else:
            self.show()

    def _delayed(self):
        self._job = None
        self.show()

    def _cancel(self):
        if self._job is not None:
            try:
                self.widget.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def _leave(self, _event=None):
        self._cancel()
        self.hide()

    def _press(self, _event=None):
        self._cancel()
        if self.toggle_on_click and self.tip is None:
            self.show()
        else:
            self.hide()

    def show(self, _event=None):
        if self.tip is not None:
            return
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        try:
            tip.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        tk.Label(tip, text=self.text, justify="left", wraplength=self.wrap, background=C_TIP_BG,
                 foreground="white", borderwidth=0, padx=10, pady=7).pack()
        tip.update_idletasks()
        w = self.widget
        x, y = tip_position(w.winfo_rootx(), w.winfo_rooty(), w.winfo_width(), w.winfo_height(),
                            tip.winfo_reqwidth(), tip.winfo_reqheight(),
                            w.winfo_screenwidth(), w.winfo_screenheight())
        tip.wm_geometry(f"+{x}+{y}")
        self.tip = tip

    def hide(self, _event=None):
        if self.tip is not None:
            try:
                self.tip.destroy()
            except tk.TclError:
                pass
            self.tip = None


class InfoBadge(tk.Canvas):
    """Small outlined 'i' circle; hover or click shows its explanation."""

    def __init__(self, parent, text: str, bg: str, family: str, size: int = 16):
        super().__init__(parent, width=size, height=size, highlightthickness=0, borderwidth=0,
                         background=bg, cursor="question_arrow")
        pad = max(2, size // 8)
        self._ring = self.create_oval(pad, pad, size - pad, size - pad, outline=C_FAINT, width=1)
        self._glyph = self.create_text(size // 2, size // 2, text="i", fill=C_FAINT,
                                       font=(family, 8, "bold"))
        self.tooltip = Tooltip(self, text, delay=0, toggle=True)
        self.bind("<Enter>", lambda _e: self._tint(C_ACCENT), add="+")
        self.bind("<Leave>", lambda _e: self._tint(C_FAINT), add="+")

    def _tint(self, color: str):
        self.itemconfigure(self._ring, outline=color)
        self.itemconfigure(self._glyph, fill=color)


def resource_path(name: str) -> Path:
    """File shipped with the program (inside the .exe when packaged)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def enable_dpi_awareness():
    """Crisp (not bitmap-scaled) text on high-DPI Windows screens. Call before creating the window."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass


SETTINGS_KEYS = ("fmt_label", "quality", "resize", "overwrite", "keep_exif", "recursive", "out_dir", "video_time",
                 "progressive", "subsampling", "sensitivity", "optimize", "lossless", "png_level", "tiff_comp",
                 "keep_date", "strip_gps", "workers")
WORKER_CHOICES = ["auto", "1", "2", "3", "4", "6", "8"]


def settings_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    folder = Path(base) / "jpeg_is_king" if os.environ.get("APPDATA") else Path(base)
    return folder / ("settings.json" if os.environ.get("APPDATA") else ".jpeg_is_king.json")


def load_settings() -> dict:
    try:
        import json

        data = json.loads(settings_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001  (missing / unreadable / corrupt file: start with defaults)
        return {}


def save_settings(data: dict) -> None:
    try:
        import json

        p = settings_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:  # noqa: BLE001  (read-only profile etc.: settings just are not remembered)
        pass


def startup_log(message: str) -> None:
    """Tiny start-up trace (%APPDATA%\\jpeg_is_king\\startup.log, last 60 lines) to diagnose odd launches."""
    try:
        import time

        path = settings_path().with_name("startup.log")
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        lines.append(f"{time.strftime('%H:%M:%S')} pid={os.getpid()} {message}")
        path.write_text("\n".join(lines[-60:]) + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def work_area(root) -> tuple[int, int, int, int]:
    """(x, y, width, height) of the usable screen area (taskbar excluded) on the monitor the mouse is on,
    so the window opens where the user is looking, whatever the monitor layout."""
    sw, sh = int(root.winfo_screenwidth()), int(root.winfo_screenheight())
    if sys.platform.startswith("win"):
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32  # type: ignore[attr-defined]

            class MonitorInfo(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                            ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

            user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
            user32.MonitorFromPoint.restype = wintypes.HANDLE
            user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
            pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            info = MonitorInfo()
            info.cbSize = ctypes.sizeof(MonitorInfo)
            if user32.GetMonitorInfoW(user32.MonitorFromPoint(pt, 2), ctypes.byref(info)):  # 2 = nearest monitor
                r = info.rcWork
                if r.right - r.left > 300 and r.bottom - r.top > 300:
                    return r.left, r.top, r.right - r.left, r.bottom - r.top
        except Exception:  # noqa: BLE001
            pass
    return 0, 0, sw, sh


def compute_window(area: tuple[int, int, int, int], scale: float, saved: tuple[int, int] | None = None):
    """Window size and position for any screen (720p ... 4K, ultrawide 21:9, any DPI scale).
    Returns (w, h, x, y, min_w, min_h). The window is always centred in the work area."""
    ax, ay, aw, ah = area

    def px(v: float) -> int:
        return int(round(v * scale))

    max_w, max_h = int(aw * 0.96), int(ah * 0.92)  # leave room for the title bar and window borders
    if saved:
        w, h = saved
    else:  # grows on big screens, but never becomes absurdly wide on ultrawide ones
        w = min(max(px(1180), int(aw * 0.55)), px(1600))
        h = min(max(px(780), int(ah * 0.70)), px(1000))
    w, h = max(min(w, max_w), min(px(900), max_w)), max(min(h, max_h), min(px(560), max_h))
    x = ax + (aw - w) // 2
    y = ay + max(0, (ah - h) // 2 - px(10))  # slightly above centre: the title bar sits above the client area
    return w, h, x, y, min(px(1000), w), min(px(640), h)


class App(tk.Tk):
    # ---- remembered settings ------------------------------------------------
    def _settings_vars(self) -> dict:
        return {k: getattr(self, k) for k in SETTINGS_KEYS}

    def _load_settings(self) -> None:
        """Restore the last-used options. Every value is checked: a bad file never breaks start-up."""
        data = load_settings()
        choices = {"fmt_label": list(FORMAT_LABELS), "subsampling": [cv.AUTO] + list(cv.SUBSAMPLING_CHOICES),
                   "tiff_comp": list(cv.TIFF_COMPRESSIONS), "workers": WORKER_CHOICES}
        ranges = {"quality": (1, 100), "resize": (10, 100), "sensitivity": (1, 100), "png_level": (0, 9),
                  "video_time": (0.0, 36000.0)}
        for key, var in self._settings_vars().items():
            if key not in data:
                continue
            val = data[key]
            try:
                if key in choices:
                    if val in choices[key]:
                        var.set(val)
                elif key in ranges:
                    lo, hi = ranges[key]
                    var.set(type(var.get())(min(hi, max(lo, float(val)))))
                elif key == "out_dir":
                    if isinstance(val, str):
                        var.set(val)
                elif isinstance(val, bool):
                    var.set(val)
            except (tk.TclError, ValueError, TypeError):
                continue
        size = data.get("size")
        if isinstance(size, list) and len(size) == 2 and all(isinstance(n, int) for n in size):
            self._place_window((size[0], size[1]))

    def _place_window(self, saved) -> None:
        """Size the window for this screen and centre it (always, whatever the last position was)."""
        try:
            w, h, x, y, mw, mh = compute_window(work_area(self), self.scale, saved)
            self.minsize(mw, mh)
            self.geometry(f"{w}x{h}+{x}+{y}")
            self._size = (w, h)
        except Exception:  # noqa: BLE001
            pass

    def _save_settings(self) -> None:
        data = {k: v.get() for k, v in self._settings_vars().items()}
        try:
            data["size"] = [int(self.winfo_width()), int(self.winfo_height())]
        except tk.TclError:
            pass
        save_settings(data)

    def _on_close(self) -> None:
        self._save_settings()
        self.destroy()

    # ---- drag and drop (needs the optional tkinterdnd2 package) -------------
    def _enable_dnd(self) -> None:
        self.dnd_on = False
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD

            TkinterDnD._require(self)
            self.drop_target_register(DND_FILES)  # type: ignore[attr-defined]
            self.dnd_bind("<<Drop>>", self._on_drop)  # type: ignore[attr-defined]
            self.dnd_on = True
        except Exception:  # noqa: BLE001  (package missing: the Add buttons still work)
            pass

    def _on_drop(self, event) -> None:
        if self.worker and self.worker.is_alive():
            return
        try:
            paths = [p for p in self.tk.splitlist(event.data) if p]
        except tk.TclError:
            return
        if paths and self._add_paths(paths) == 0:
            messagebox.showinfo("Nothing found", "No supported files in what you dropped.")

    def _show_main(self) -> None:
        """Show the (single) main window. Called once, after the window is fully built."""
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:  # noqa: BLE001
            pass

    def _splash_done(self) -> None:
        startup_log("animation finished")
        try:
            self.focus_force()
        except Exception:  # noqa: BLE001
            pass

    def _center(self) -> None:
        """Always open in the middle of the screen, whatever Windows would pick."""
        try:
            w, h = self._size
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            x, y = max(0, (sw - w) // 2), max(0, (sh - h) // 2 - self.S(20))  # a little up: taskbar room
            self.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:  # noqa: BLE001
            pass

    def _start_splash(self) -> None:
        """Show the main window once. Unless disabled, the start-up animation plays inside it (click or
        press a key to skip; --no-splash turns it off)."""
        self._center()
        self.update_idletasks()  # lay everything out while the window is still hidden
        if "--no-splash" in sys.argv or os.environ.get("JPEG_IS_KING_NO_SPLASH"):
            self._show_main()
            return
        try:
            import splash

            splash.run_splash(self, self.scale, resource_path("icon.png"), self.fam, C_BG, C_LINE, self._splash_done)
            self.update_idletasks()  # the cover is in place before the window appears
        except Exception:  # noqa: BLE001
            pass
        self._show_main()
        startup_log("window shown")

    def _dark_titlebar(self) -> None:
        """Dark window frame on Windows 10/11 (ignored elsewhere)."""
        if not sys.platform.startswith("win"):
            return
        try:
            import ctypes

            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())  # type: ignore[attr-defined]
            on = ctypes.c_int(1)
            for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (Win10 20H1+ / older builds)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), 4)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass

    def _set_icon(self) -> None:
        """Window / taskbar icon. Never fatal: a missing icon file just leaves the default."""
        try:
            if sys.platform.startswith("win"):
                self.iconbitmap(default=str(resource_path("icon.ico")))
            else:
                self._icon_img = tk.PhotoImage(file=str(resource_path("icon.png")))
                self.iconphoto(True, self._icon_img)
        except Exception:  # noqa: BLE001
            pass

    def __init__(self):
        super().__init__()
        self.withdraw()
        startup_log(f"start argv={sys.argv[1:]}")  # stay invisible while the window is built; it is shown once, fully drawn (_show_main)
        self.scale = max(1.0, float(self.winfo_fpixels("1i")) / 96.0)  # UI scale factor (DPI)
        self.title("jpeg_is_king")
        self._set_icon()
        self._dark_titlebar()
        self._place_window(None)

        self.items: dict[str, Path] = {}
        self.order: list[str] = []  # row ids in insertion order
        self.results: dict[str, Path] = {}  # row id -> converted file
        self.overrides: dict[str, dict] = {}  # row id -> {"chroma": str, "sens": int}
        self._counter = 0
        self._filter_job = None
        self._selbar_shown = False
        self.q: queue.Queue = queue.Queue()
        self.stop_flag = threading.Event()
        self.worker: threading.Thread | None = None

        self.fmt_label = tk.StringVar(value="JPEG")
        self.quality = tk.IntVar(value=85)
        self.resize = tk.IntVar(value=100)
        self.overwrite = tk.BooleanVar(value=False)
        self.keep_exif = tk.BooleanVar(value=True)
        self.recursive = tk.BooleanVar(value=True)
        self.out_dir = tk.StringVar(value="")
        self.video_time = tk.DoubleVar(value=0.0)

        # per-format options
        self.progressive = tk.BooleanVar(value=False)
        self.subsampling = tk.StringVar(value=cv.AUTO)
        self.sensitivity = tk.IntVar(value=50)
        self.optimize = tk.BooleanVar(value=True)
        self.lossless = tk.BooleanVar(value=False)
        self.png_level = tk.IntVar(value=6)
        self.tiff_comp = tk.StringVar(value="lzw")
        self.keep_date = tk.BooleanVar(value=True)
        self.strip_gps = tk.BooleanVar(value=False)
        self.workers = tk.StringVar(value="auto")

        # search + per-file override controls
        self.search = tk.StringVar(value="")
        self.ov_chroma = tk.StringVar(value=GLOBAL_CHOICE)
        self.ov_sens_on = tk.BooleanVar(value=False)
        self.ov_sens = tk.IntVar(value=70)

        self._load_settings()
        self._setup_style()
        self._build()
        self._enable_dnd()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # Keep the value labels in step with the sliders. (Must be wired up here, after _build has
        # created the labels; moving a slider writes its variable, which triggers this.)
        for var in (self.quality, self.resize, self.sensitivity, self.png_level):
            var.trace_add("write", lambda *_: self._labels())
        self._labels()
        self._update_state()
        self._refresh_counts()
        self._start_splash()

    def S(self, px: int) -> int:
        """Scale a pixel size for the screen's DPI."""
        return int(round(px * self.scale))

    # ------------------------------------------------------------- styling
    def _setup_style(self):
        S = self.S
        fams = set(tkfont.families(self))
        fam = next((f for f in ("Segoe UI Variable Text", "Segoe UI", "SF Pro Text", "Helvetica Neue",
                                "Inter", "Ubuntu", "DejaVu Sans") if f in fams), None)
        if fam is None:
            fam = tkfont.nametofont("TkDefaultFont").actual("family")
        self.fam = fam
        self.F = (fam, 10)
        self.F_SMALL = (fam, 9)
        self.F_CAP = (fam, 8, "bold")
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(name).configure(family=fam, size=10)
            except tk.TclError:
                pass

        self.configure(background=C_BG)
        self.option_add("*TCombobox*Listbox.font", self.F)
        self.option_add("*TCombobox*Listbox.background", C_FIELD)
        self.option_add("*TCombobox*Listbox.foreground", C_TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", C_SEL)
        self.option_add("*TCombobox*Listbox.selectForeground", C_TEXT)
        self.option_add("*TCombobox*Listbox.borderWidth", 0)

        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure(".", font=self.F, background=C_BG, foreground=C_TEXT, bordercolor=C_LINE,
                     troughcolor=C_LINE, focuscolor=C_BG, lightcolor=C_BG, darkcolor=C_BG)

        # Same widgets on the white canvas ("") and on the grey side panel ("Panel.")
        for pre, bg in (("", C_BG), ("Panel.", C_PANEL)):
            st.configure(pre + "TFrame", background=bg)
            st.configure(pre + "TLabel", background=bg, foreground=C_TEXT)
            st.configure(pre + "Muted.TLabel", background=bg, foreground=C_MUTED, font=self.F_SMALL)
            st.configure(pre + "Cap.TLabel", background=bg, foreground=C_MUTED, font=self.F_CAP)
            st.configure(pre + "TCheckbutton", background=bg, foreground=C_TEXT, focuscolor=bg,
                         indicatorbackground=C_FIELD, indicatorforeground=C_FIELD)
            st.map(pre + "TCheckbutton", background=[("active", bg)],
                   indicatorbackground=[("selected", C_ACCENT), ("pressed", C_BTN_H)],
                   indicatorforeground=[("selected", "white")])
            st.configure(pre + "Horizontal.TScale", background=C_ACCENT, troughcolor=C_LINE,
                         bordercolor=bg, lightcolor=C_ACCENT, darkcolor=C_ACCENT)
        st.configure("Line.TFrame", background=C_LINE)
        st.configure("Warn.TLabel", background=C_WARN_BG, foreground=C_WARN_FG, padding=(S(16), S(7)))
        st.configure("TSeparator", background=C_LINE)

        # Buttons: neutral by default, blue for the one primary action, ghost for quiet actions
        st.configure("TButton", padding=(S(14), S(7)), relief="flat", borderwidth=0, background=C_BTN,
                     foreground=C_TEXT, focuscolor=C_BTN)
        st.map("TButton", background=[("disabled", C_PANEL), ("pressed", C_BTN_H), ("active", C_BTN_H)],
               foreground=[("disabled", C_FAINT)])
        st.configure("Accent.TButton", background=C_ACCENT, foreground="white", padding=(S(22), S(9)),
                     focuscolor=C_ACCENT)
        st.map("Accent.TButton", background=[("disabled", C_ACCENT_D), ("pressed", C_ACCENT_H),
                                             ("active", C_ACCENT_H)],
               foreground=[("disabled", "white")])
        st.configure("AccentSm.TButton", background=C_ACCENT, foreground="white", padding=(S(14), S(5)),
                     focuscolor=C_ACCENT)
        st.map("AccentSm.TButton", background=[("pressed", C_ACCENT_H), ("active", C_ACCENT_H)])
        st.configure("Ghost.TButton", background=C_BG, foreground=C_MUTED, padding=(S(10), S(7)),
                     focuscolor=C_BG)
        st.map("Ghost.TButton", background=[("active", C_BTN), ("pressed", C_BTN_H)],
               foreground=[("active", C_TEXT), ("disabled", C_FAINT)])
        st.configure("Panel.Browse.TButton", padding=(S(12), S(6)))

        # Segmented format switch
        st.configure("Seg.Toolbutton", padding=(0, S(7)), anchor="center", relief="flat", borderwidth=0,
                     background=C_BTN, foreground=C_TEXT, focuscolor=C_BTN)
        st.map("Seg.Toolbutton", background=[("selected", C_ACCENT), ("active", C_BTN_H)],
               foreground=[("selected", "white")])

        # Inputs
        st.configure("TEntry", fieldbackground=C_FIELD, bordercolor=C_LINE, lightcolor=C_LINE,
                     darkcolor=C_LINE, padding=(S(8), S(6)), relief="flat", insertcolor=C_TEXT)
        st.map("TEntry", bordercolor=[("focus", C_ACCENT)], lightcolor=[("focus", C_ACCENT)],
               darkcolor=[("focus", C_ACCENT)])
        st.configure("TCombobox", fieldbackground=C_FIELD, background=C_BTN, bordercolor=C_LINE,
                     lightcolor=C_LINE, darkcolor=C_LINE, arrowcolor=C_MUTED, padding=(S(8), S(5)),
                     selectbackground=C_FIELD, selectforeground=C_TEXT)
        st.map("TCombobox", fieldbackground=[("readonly", C_FIELD)], bordercolor=[("focus", C_ACCENT)],
               lightcolor=[("focus", C_ACCENT)], darkcolor=[("focus", C_ACCENT)],
               foreground=[("disabled", C_FAINT)])
        st.configure("TSpinbox", fieldbackground=C_FIELD, bordercolor=C_LINE, lightcolor=C_LINE,
                     darkcolor=C_LINE, arrowcolor=C_MUTED, padding=(S(6), S(4)), insertcolor=C_TEXT)

        # Table
        st.configure("Treeview", background=C_BG, fieldbackground=C_BG, foreground=C_TEXT,
                     rowheight=S(30), borderwidth=0, relief="flat")
        st.map("Treeview", background=[("selected", C_SEL)], foreground=[("selected", C_TEXT)])
        st.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        st.configure("Treeview.Heading", background=C_PANEL, foreground=C_MUTED, relief="flat",
                     borderwidth=0, padding=(S(8), S(8)), font=self.F_SMALL)
        st.map("Treeview.Heading", background=[("active", C_BTN)])

        # Progress + scrollbar
        st.configure("Horizontal.TProgressbar", troughcolor=C_LINE, background=C_ACCENT,
                     bordercolor=C_LINE, lightcolor=C_ACCENT, darkcolor=C_ACCENT, thickness=S(6))
        for orient in ("Vertical", "Horizontal"):
            st.configure(orient + ".TScrollbar", background=C_THUMB, troughcolor=C_BG, bordercolor=C_BG,
                         lightcolor=C_THUMB, darkcolor=C_THUMB, arrowcolor=C_MUTED, arrowsize=S(12))
            st.map(orient + ".TScrollbar", background=[("active", C_FAINT)])

    # ---- small widget helpers ---------------------------------------------
    def _badge(self, parent, key: str, pre: str = ""):
        return InfoBadge(parent, TIPS[key], C_PANEL if pre else C_BG, self.fam, self.S(16))

    def _hdr(self, parent, text: str, key: str, pre: str = ""):
        """A label followed by an info badge."""
        f = ttk.Frame(parent, style=pre + "TFrame")
        ttk.Label(f, text=text, style=pre + "TLabel").pack(side="left")
        self._badge(f, key, pre).pack(side="left", padx=(6, 0))
        return f

    def _check(self, parent, text: str, var, key: str, pre: str = "", command=None):
        f = ttk.Frame(parent, style=pre + "TFrame")
        kw = {"command": command} if command else {}
        cb = ttk.Checkbutton(f, text=text, variable=var, style=pre + "TCheckbutton", **kw)
        cb.pack(side="left")
        self._badge(f, key, pre).pack(side="left", padx=(6, 0))
        return f, cb

    def _slider(self, parent, title: str, key: str, var, lo: int, hi: int, pre: str = "", length=None):
        """Title + info badge + value on one line, slider below. Returns (frame, value_label)."""
        f = ttk.Frame(parent, style=pre + "TFrame")
        f.columnconfigure(0, weight=1)
        head = ttk.Frame(f, style=pre + "TFrame")
        head.grid(row=0, column=0, sticky="ew")
        ttk.Label(head, text=title, style=pre + "TLabel").pack(side="left")
        self._badge(head, key, pre).pack(side="left", padx=(6, 0))
        val = ttk.Label(head, style=pre + "Muted.TLabel")
        val.pack(side="right")
        kw = {"length": length} if length else {}
        sc = ttk.Scale(f, from_=lo, to=hi, orient="horizontal", variable=var, style=pre + "Horizontal.TScale",
                       command=lambda v, var=var: var.set(int(round(float(v)))), **kw)
        sc.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        return f, val

    def _tip(self, widget, key: str):
        """Hover explanation for a button (appears after a short delay)."""
        Tooltip(widget, TIPS[key], delay=550, toggle=False)

    # ------------------------------------------------------------------ UI
    def _build(self):
        S = self.S

        warn = []
        if cv.rawpy is None:
            warn.append("rawpy not installed: ARW / DNG disabled")
        if cv.pillow_heif is None:
            warn.append("pillow-heif not installed: HEIC / HEIF disabled")
        if not cv.find_ffmpeg():
            warn.append("Video disabled: " + cv.ffmpeg_problem()[:110])
        if warn:
            ttk.Label(self, text="     ".join(warn), style="Warn.TLabel").pack(side="top", fill="x")

        # bottom action bar (packed first so it keeps its place when the window shrinks)
        bottom = ttk.Frame(self, padding=(S(18), S(12)))
        bottom.pack(side="bottom", fill="x")
        ttk.Separator(self, orient="horizontal").pack(side="bottom", fill="x")

        self.go_btn = ttk.Button(bottom, text="Convert", style="Accent.TButton", command=self.start)
        self.go_btn.pack(side="right")
        self._tip(self.go_btn, "convert")
        self.stop_btn = ttk.Button(bottom, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="right", padx=(0, 8))
        open_btn = ttk.Button(bottom, text="Open output folder", command=self.open_output_folder)
        open_btn.pack(side="right", padx=(0, 8))
        self._tip(open_btn, "open_out")
        self.summary = ttk.Label(bottom, text="", style="Muted.TLabel")
        self.summary.pack(side="left")
        self.progress = ttk.Progressbar(bottom, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=16)

        main = ttk.Frame(self)
        main.pack(side="top", fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.columnconfigure(2, minsize=S(330))
        main.rowconfigure(0, weight=1)

        left = ttk.Frame(main, padding=(S(18), S(16), S(16), S(14)))
        left.grid(row=0, column=0, sticky="nsew")
        ttk.Separator(main, orient="vertical").grid(row=0, column=1, sticky="ns")
        side = self._scrolling_panel(main, row=0, column=2)

        self._build_files(left)
        self._build_sidebar(side)
        self._finish_panel()

    # ---- scrollable settings panel ---------------------------------------
    def _scrolling_panel(self, parent, row: int, column: int):
        """A panel that scrolls (mouse wheel + a bar that appears only when needed) when the window
        is too short to show every setting. Returns the frame to put the settings in."""
        S = self.S
        host = ttk.Frame(parent, style="Panel.TFrame")
        host.grid(row=row, column=column, sticky="nsew")
        self._side_host = host
        self._side_canvas = tk.Canvas(host, background=C_PANEL, highlightthickness=0, borderwidth=0,
                                      width=S(330), yscrollincrement=S(24))
        self._side_bar = ttk.Scrollbar(host, orient="vertical", command=self._side_canvas.yview)
        self._side_bar_shown = False
        self._side_canvas.configure(yscrollcommand=self._on_side_scroll)
        self._side_canvas.pack(side="left", fill="both", expand=True)
        side = ttk.Frame(self._side_canvas, style="Panel.TFrame", padding=(S(22), S(18)))
        self._side_win = self._side_canvas.create_window((0, 0), window=side, anchor="nw")
        side.bind("<Configure>", lambda e: self._side_layout())
        self._side_canvas.bind("<Configure>", lambda e: self._side_layout())
        self._side_frame = side
        self.bind_all("<MouseWheel>", self._side_wheel, add="+")
        self.bind_all("<Button-4>", self._side_wheel, add="+")  # Linux
        self.bind_all("<Button-5>", self._side_wheel, add="+")
        return side

    def _finish_panel(self) -> None:
        """Make the panel at least as wide as its content, then lay it out."""
        try:
            self.update_idletasks()
            self._side_canvas.configure(width=max(self.S(330), int(self._side_frame.winfo_reqwidth())))
        except Exception:  # noqa: BLE001
            pass
        self._side_layout()

    def _side_layout(self) -> None:
        try:
            cw, ch = int(self._side_canvas.winfo_width()), int(self._side_canvas.winfo_height())
            need = int(self._side_frame.winfo_reqheight())
            self._side_canvas.itemconfigure(self._side_win, width=cw)
            self._side_canvas.configure(scrollregion=(0, 0, cw, max(need, ch)))
            if need <= ch:
                self._side_canvas.yview_moveto(0)
        except Exception:  # noqa: BLE001
            pass

    def _on_side_scroll(self, lo, hi) -> None:
        self._side_bar.set(lo, hi)
        needed = float(lo) > 0.0 or float(hi) < 1.0
        if needed and not self._side_bar_shown:
            self._side_bar.pack(side="right", fill="y")
            self._side_bar_shown = True
        elif not needed and self._side_bar_shown:
            self._side_bar.pack_forget()
            self._side_bar_shown = False

    def _side_wheel(self, e) -> None:
        """Scroll the settings panel when the pointer is over it (and it is scrollable)."""
        if not self._side_bar_shown:
            return
        try:
            w = self.winfo_containing(e.x_root, e.y_root)
            while w is not None and w is not self._side_host:
                w = w.master
            if w is None:
                return
            step = -1 if (getattr(e, "num", 0) == 4 or getattr(e, "delta", 0) > 0) else 1
            self._side_canvas.yview_scroll(step * 2, "units")
        except Exception:  # noqa: BLE001
            pass

    def _build_files(self, left):
        S = self.S

        # toolbar
        bar = ttk.Frame(left)
        bar.pack(side="top", fill="x")
        b = ttk.Button(bar, text="Add files…", command=self.add_files)
        b.pack(side="left")
        self._tip(b, "add_files")
        b = ttk.Button(bar, text="Add folder…", command=self.add_folder)
        b.pack(side="left", padx=(8, 0))
        self._tip(b, "add_folder")
        b = ttk.Button(bar, text="Clear", style="Ghost.TButton", command=self.clear)
        b.pack(side="right")
        self._tip(b, "clear")
        b = ttk.Button(bar, text="Remove", style="Ghost.TButton", command=self.remove_selected)
        b.pack(side="right")
        self._tip(b, "remove")
        self._badge(bar, "list").pack(side="right", padx=(0, 6))

        # search row
        srow = ttk.Frame(left)
        srow.pack(side="top", fill="x", pady=(12, 10))
        self._badge(srow, "search").pack(side="right", padx=(8, 0))
        b = ttk.Button(srow, text="Select shown", style="Ghost.TButton", command=self.select_all_shown)
        b.pack(side="right")
        self._tip(b, "select_all")
        self.count_lbl = ttk.Label(srow, text="", style="Muted.TLabel")
        self.count_lbl.pack(side="right", padx=(8, 4))
        ttk.Button(srow, text="✕", style="Ghost.TButton", width=3,
                   command=lambda: self.search.set("")).pack(side="right")
        self.search_entry = ttk.Entry(srow, textvariable=self.search)
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.search.trace_add("write", lambda *_: self._schedule_filter())

        # table (1px border via a coloured frame with 1px padding)
        self.table_frame = ttk.Frame(left, style="Line.TFrame", padding=1)
        self.table_frame.pack(side="top", fill="both", expand=True)
        inner = ttk.Frame(self.table_frame)
        inner.pack(fill="both", expand=True)
        cols = ("name", "folder", "type", "size", "chroma", "status")
        self.tree = ttk.Treeview(inner, columns=cols, show="headings", selectmode="extended")
        spec = (("name", "Name", 190, "w", False), ("folder", "Folder", 170, "w", False),
                ("type", "Type", 52, "center", False), ("size", "Size", 72, "e", False),
                ("chroma", "Chroma", 78, "center", False), ("status", "Status", 230, "w", False))
        for c, title, w, anchor, stretch in spec:
            self.tree.heading(c, text=title, anchor="w" if anchor == "w" else "center")
            self.tree.column(c, width=S(w), minwidth=S(40), anchor=anchor, stretch=stretch)  # type: ignore[arg-type]
        self.tree.tag_configure("ok", foreground=C_OK)
        self.tree.tag_configure("err", foreground=C_ERR)
        self.tree.tag_configure("skip", foreground=C_MUTED)
        self.tree.tag_configure("busy", foreground=C_ACCENT)
        self.tree.bind("<Double-1>", self.on_row_open)
        self.tree.bind("<Return>", self.on_row_open)
        self.tree.bind("<Control-a>", lambda e: (self.select_all_shown(), "break")[1])
        self.tree.bind("<Delete>", lambda e: self.remove_selected())
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._sel_label())
        sb = ttk.Scrollbar(inner, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(inner, orient="horizontal", command=self.tree.xview)
        self._hsb, self._hsb_shown = hsb, False
        self.tree.configure(yscrollcommand=sb.set, xscrollcommand=self._on_hscroll)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._status_w = S(230)
        self._cols = cols
        # No column is "stretch": ttk would hand extra width to it and snap a dragged column back.
        # Instead the Status column fills whatever space is left over.
        self.tree.bind("<Configure>", lambda e: self._fill_status())
        self.tree.bind("<ButtonRelease-1>", lambda e: self.after_idle(self._fill_status))
        self.empty_lbl = ttk.Label(self.table_frame, text="", style="Muted.TLabel")

        # bar for the selected files (only shown while files are selected and the format is JPEG)
        self.selbar = ttk.Frame(left, padding=(0, S(10), 0, 0))
        self.sel_lbl = ttk.Label(self.selbar, text="0 selected", style="Muted.TLabel")
        self.sel_lbl.pack(side="left", padx=(0, 14))
        self._hdr(self.selbar, "Chroma", "ov_chroma").pack(side="left", padx=(0, 6))
        ttk.Combobox(self.selbar, textvariable=self.ov_chroma, values=[GLOBAL_CHOICE] + cv.SUBSAMPLING_CHOICES,
                     state="readonly", width=14).pack(side="left", padx=(0, 16))
        f, _cb = self._check(self.selbar, "Sensitivity", self.ov_sens_on, "ov_sens")
        f.pack(side="left")
        ttk.Scale(self.selbar, from_=1, to=100, orient="horizontal", length=S(110), variable=self.ov_sens,
                  command=lambda v: self.ov_sens.set(int(round(float(v))))).pack(side="left", padx=(8, 4))
        self.ov_sens_lbl = ttk.Label(self.selbar, width=4, style="Muted.TLabel")
        self.ov_sens_lbl.pack(side="left")
        self.ov_sens.trace_add("write", lambda *_: self.ov_sens_lbl.config(text=f"{self.ov_sens.get()}"))
        self.ov_sens_lbl.config(text=f"{self.ov_sens.get()}")
        b = ttk.Button(self.selbar, text="Apply", style="AccentSm.TButton", command=self.apply_overrides)
        b.pack(side="right")
        self._tip(b, "ov_apply")
        b = ttk.Button(self.selbar, text="Reset", style="Ghost.TButton", command=self.reset_overrides)
        b.pack(side="right", padx=(0, 6))
        self._tip(b, "ov_reset")

    def _build_sidebar(self, side):
        P = "Panel."
        side.columnconfigure(0, weight=1)
        r = 0

        # ---- conversion
        ttk.Label(side, text="CONVERSION", style="Panel.Cap.TLabel").grid(row=r, column=0, sticky="w")
        r += 1
        fhead = self._hdr(side, "Format", "format", P)
        fhead.grid(row=r, column=0, sticky="w", pady=(10, 6))
        r += 1
        seg = ttk.Frame(side, style="Panel.TFrame")
        seg.grid(row=r, column=0, sticky="ew", pady=(0, 16))
        for i, label in enumerate(FORMAT_LABELS):
            seg.columnconfigure(i, weight=1, uniform="seg")
            ttk.Radiobutton(seg, text=label, value=label, variable=self.fmt_label, style="Seg.Toolbutton",
                            command=self._update_state).grid(row=0, column=i, sticky="ew")
        r += 1

        self.blk_quality, self.q_val = self._slider(side, "Quality", "quality", self.quality, 1, 100, P)
        self.blk_quality.grid(row=r, column=0, sticky="ew", pady=(0, 14))
        r += 1
        blk, self.r_val = self._slider(side, "Resize", "resize", self.resize, 10, 100, P)
        blk.grid(row=r, column=0, sticky="ew", pady=(0, 14))
        r += 1

        # JPEG-only block
        self.blk_jpeg = ttk.Frame(side, style="Panel.TFrame")
        self.blk_jpeg.columnconfigure(0, weight=1)
        self._hdr(self.blk_jpeg, "Chroma subsampling", "chroma", P).grid(row=0, column=0, sticky="w")
        self.w_sub = ttk.Combobox(self.blk_jpeg, textvariable=self.subsampling, values=cv.SUBSAMPLING_CHOICES,
                                  state="readonly")
        self.w_sub.grid(row=1, column=0, sticky="ew", pady=(6, 12))
        self.w_sub.bind("<<ComboboxSelected>>", lambda _e: self._update_state())
        self.blk_sens, self.sens_val = self._slider(self.blk_jpeg, "Auto sensitivity", "sensitivity",
                                                    self.sensitivity, 1, 100, P)
        self.blk_sens.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        self.sens_cap = ttk.Label(self.blk_sens, style="Panel.Muted.TLabel", wraplength=self.S(280),
                                  justify="left")
        self.sens_cap.grid(row=2, column=0, sticky="w", pady=(2, 0))
        f, _cb = self._check(self.blk_jpeg, "Progressive", self.progressive, "progressive", P)
        f.grid(row=3, column=0, sticky="w", pady=(0, 4))
        f, _cb = self._check(self.blk_jpeg, "Optimize", self.optimize, "optimize", P)
        f.grid(row=4, column=0, sticky="w")
        self.blk_jpeg.grid(row=r, column=0, sticky="ew", pady=(0, 14))
        r += 1

        # WebP / PNG / TIFF blocks (one of them at a time)
        self.blk_webp = ttk.Frame(side, style="Panel.TFrame")
        f, _cb = self._check(self.blk_webp, "Lossless", self.lossless, "lossless", P,
                             command=self._update_state)
        f.pack(anchor="w")
        self.blk_webp.grid(row=r, column=0, sticky="ew", pady=(0, 14))
        r += 1

        self.blk_png, self.png_val = self._slider(side, "Compression level", "png", self.png_level, 0, 9, P)
        self.blk_png.grid(row=r, column=0, sticky="ew", pady=(0, 14))
        r += 1

        self.blk_tiff = ttk.Frame(side, style="Panel.TFrame")
        self.blk_tiff.columnconfigure(0, weight=1)
        self._hdr(self.blk_tiff, "Compression", "tiff", P).grid(row=0, column=0, sticky="w")
        self.w_tiff = ttk.Combobox(self.blk_tiff, textvariable=self.tiff_comp, values=list(cv.TIFF_COMPRESSIONS),
                                   state="readonly")
        self.w_tiff.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.w_tiff.bind("<<ComboboxSelected>>", lambda _e: self._update_state())
        self.blk_tiff.grid(row=r, column=0, sticky="ew", pady=(0, 14))
        r += 1

        ttk.Separator(side, orient="horizontal").grid(row=r, column=0, sticky="ew", pady=(4, 16))
        r += 1

        # ---- output
        ttk.Label(side, text="OUTPUT", style="Panel.Cap.TLabel").grid(row=r, column=0, sticky="w")
        r += 1
        self._hdr(side, "Folder", "out_dir", P).grid(row=r, column=0, sticky="w", pady=(10, 6))
        r += 1
        frow = ttk.Frame(side, style="Panel.TFrame")
        frow.grid(row=r, column=0, sticky="ew")
        ttk.Button(frow, text="Browse…", style="Panel.Browse.TButton", command=self.pick_out).pack(side="right",
                                                                                                   padx=(8, 0))
        ttk.Entry(frow, textvariable=self.out_dir).pack(side="left", fill="x", expand=True)
        r += 1
        ttk.Label(side, text=f"Empty = a '{cv.DEFAULT_OUT_SUBDIR}' folder next to each original",
                  style="Panel.Muted.TLabel", wraplength=self.S(280), justify="left").grid(
            row=r, column=0, sticky="w", pady=(6, 12))
        r += 1
        for text, var, key in (("Overwrite existing files", self.overwrite, "overwrite"),
                               ("Keep EXIF data", self.keep_exif, "exif"),
                               ("Remove GPS location", self.strip_gps, "strip_gps"),
                               ("Keep original date", self.keep_date, "keep_date"),
                               ("Include subfolders", self.recursive, "recursive")):
            f, _cb = self._check(side, text, var, key, P)
            f.grid(row=r, column=0, sticky="w", pady=(0, 4))
            r += 1
        vrow = ttk.Frame(side, style="Panel.TFrame")
        vrow.grid(row=r, column=0, sticky="w", pady=(8, 0))
        self._hdr(vrow, "Video frame at", "video", P).pack(side="left")
        ttk.Spinbox(vrow, from_=0, to=36000, increment=0.5, width=6, textvariable=self.video_time).pack(
            side="left", padx=(10, 6))
        ttk.Label(vrow, text="s", style="Panel.Muted.TLabel").pack(side="left")
        r += 1
        wrow = ttk.Frame(side, style="Panel.TFrame")
        wrow.grid(row=r, column=0, sticky="w", pady=(10, 0))
        self._hdr(wrow, "Parallel files", "workers", P).pack(side="left")
        ttk.Combobox(wrow, textvariable=self.workers, values=WORKER_CHOICES, state="readonly", width=6).pack(
            side="left", padx=(10, 0))

    def _labels(self):
        self.q_val.config(text=f"{self.quality.get()}%")
        self.r_val.config(text=f"{self.resize.get()}%")
        self.png_val.config(text=f"{self.png_level.get()}")
        s = self.sensitivity.get()
        self.sens_val.config(text=f"{s}")
        self.sens_cap.config(text=f"Uses 4:4:4 when more than {cv.damage_limit(s) * 100:.2g}% of pixels "
                                  f"would shift colour.")

    def _fmt(self) -> str:
        return FORMAT_LABELS.get(self.fmt_label.get(), "jpeg")

    @staticmethod
    def _show(widget, on: bool):
        if on:
            widget.grid()
        else:
            widget.grid_remove()

    def _update_state(self):
        """Show only the options that apply to the chosen format (hidden, not greyed out)."""
        f = self._fmt()
        jpeg, webp, png, tiff = f == "jpeg", f == "webp", f == "png", f == "tiff"
        tiff_jpeg = tiff and self.tiff_comp.get() == "jpeg"
        self._show(self.blk_quality, jpeg or (webp and not self.lossless.get()) or tiff_jpeg)
        self._show(self.blk_jpeg, jpeg)
        self._show(self.blk_sens, self.subsampling.get() == cv.AUTO)
        self._show(self.blk_webp, webp)
        self._show(self.blk_png, png)
        self._show(self.blk_tiff, tiff)
        self._sel_label()

    # --------------------------------------------------------- search filter
    @staticmethod
    def _name_matches(name: str, terms: list[str]) -> bool:
        """All space-separated terms must match the file name (case-insensitive).
        A term may use * and ? wildcards, e.g. 'dsc017*'."""
        import fnmatch

        for t in terms:
            if "*" in t or "?" in t:
                if not fnmatch.fnmatchcase(name, f"*{t}*"):
                    return False
            elif t not in name:
                return False
        return True

    def _schedule_filter(self):
        if self._filter_job is not None:
            self.after_cancel(self._filter_job)
        self._filter_job = self.after(150, self._apply_filter)

    def _apply_filter(self):
        self._filter_job = None
        terms = self.search.get().lower().split()
        show = [i for i in self.order if self._name_matches(self.items[i].name.lower(), terms)]
        show_set = set(show)
        attached = set(self.tree.get_children(""))

        hide = [i for i in self.order if i not in show_set and i in attached]
        if hide:
            try:  # hidden files must never stay selected (Remove / Apply act on the selection)
                self.tree.selection_remove(*hide)
            except tk.TclError:
                pass
            self.tree.detach(*hide)
            attached -= set(hide)
        for idx, iid in enumerate(show):
            if iid not in attached:
                self.tree.move(iid, "", idx)
        self._refresh_counts(len(show), bool(terms))

    def _refresh_counts(self, shown: int | None = None, filtered: bool | None = None):
        if shown is None:
            shown = len(self.tree.get_children(""))
        if filtered is None:
            filtered = bool(self.search.get().split())
        total = len(self.order)
        self.count_lbl.config(text=f"{shown} of {total}" if total else "")
        self.summary.config(text=f"{total} file{'s' if total != 1 else ''}" if total else "")
        self.go_btn.config(text=f"Convert {shown} shown" if filtered and total else "Convert")
        if not total:
            self.empty_lbl.config(text="Add files or a folder to get started" + (", or drop them here" if getattr(self, "dnd_on", False) else ""))
            self.empty_lbl.place(relx=0.5, rely=0.5, anchor="center")
        elif shown == 0:
            self.empty_lbl.config(text="No files match your search")
            self.empty_lbl.place(relx=0.5, rely=0.5, anchor="center")
        else:
            self.empty_lbl.place_forget()
        self._sel_label()

    def _sel_label(self):
        n = len(self.tree.selection())
        self.sel_lbl.config(text=f"{n} selected")
        want = n > 0 and self._fmt() == "jpeg"
        if want and not self._selbar_shown:
            self.selbar.pack(side="bottom", fill="x", before=self.table_frame)
            self._selbar_shown = True
        elif not want and self._selbar_shown:
            self.selbar.pack_forget()
            self._selbar_shown = False

    def select_all_shown(self):
        self.tree.selection_set(self.tree.get_children(""))

    # ------------------------------------------------------ per-file overrides
    def _ov_text(self, iid: str) -> str:
        ov = self.overrides.get(iid)
        if not ov:
            return "—"
        text = ov.get("chroma") or "global"
        if ov.get("sens") is not None:
            text += f" s{ov['sens']}"
        return text

    def apply_overrides(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("No files selected",
                                "Select files in the list first (tip: search by name, then 'Select shown').")
            return
        choice = self.ov_chroma.get()
        sens = int(self.ov_sens.get()) if self.ov_sens_on.get() else None
        for iid in sel:
            ov = self.overrides.setdefault(iid, {})
            if choice != GLOBAL_CHOICE:
                ov["chroma"] = choice
            else:
                ov.pop("chroma", None)
            if sens is not None:
                ov["sens"] = sens
            else:
                ov.pop("sens", None)
            if not ov:
                self.overrides.pop(iid, None)
            self.tree.set(iid, "chroma", self._ov_text(iid))

    def reset_overrides(self):
        for iid in self.tree.selection():
            self.overrides.pop(iid, None)
            self.tree.set(iid, "chroma", self._ov_text(iid))

    # ------------------------------------------------------------ file list
    def _add_paths(self, paths):
        existing = {str(p).lower() for p in self.items.values()}
        added = 0
        for p in cv.collect_files(paths, self.recursive.get()):
            if str(p).lower() in existing:
                continue
            self._counter += 1
            iid = f"i{self._counter}"
            self.items[iid] = p
            self.order.append(iid)
            size = cv.human(p.stat().st_size)
            self.tree.insert("", "end", iid=iid,
                             values=(p.name, str(p.parent), p.suffix.upper().lstrip("."), size, "—", "Queued"))
            added += 1
        self._apply_filter()
        return added

    def add_files(self):
        exts = " ".join(f"*{e}" for e in sorted(cv.ALL_EXTS))
        exts += " " + " ".join(f"*{e.upper()}" for e in sorted(cv.ALL_EXTS))
        paths = filedialog.askopenfilenames(title="Select files",
                                            filetypes=[("Supported files", exts), ("All files", "*.*")])
        if paths:
            self._add_paths(paths)

    def add_folder(self):
        d = filedialog.askdirectory(title="Select folder")
        if d:
            n = self._add_paths([d])
            if n == 0:
                messagebox.showinfo("Nothing found", "No supported files in that folder.")

    def remove_selected(self):
        sel = list(self.tree.selection())
        for iid in sel:
            self.items.pop(iid, None)
            self.results.pop(iid, None)
            self.overrides.pop(iid, None)
            self.tree.delete(iid)
        gone = set(sel)
        self.order = [i for i in self.order if i not in gone]
        self._refresh_counts()

    def clear(self):
        if self.worker and self.worker.is_alive():
            return
        # Rows hidden by the search are detached (not children of the root), so delete by id.
        for iid in list(self.order):
            self.tree.delete(iid)
        self.items.clear()
        self.order.clear()
        self.results.clear()
        self.overrides.clear()
        self.progress["value"] = 0
        self._refresh_counts(0, bool(self.search.get().split()))

    def pick_out(self):
        d = filedialog.askdirectory(title="Output folder")
        if d:
            self.out_dir.set(d)

    # ------------------------------------------------------------ open things
    @staticmethod
    def _open(path: Path):
        """Open a file or folder with the system's default application."""
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Could not open", f"{path}\n\n{e}")

    def on_row_open(self, event=None):
        """Double-click / Enter on a row: open the source, and the converted file if it exists."""
        if event is not None and event.type == tk.EventType.ButtonPress:
            iid = self.tree.identify_row(event.y)
        else:
            sel = self.tree.selection()
            iid = sel[0] if sel else ""
        if not iid or iid not in self.items:
            return
        src = self.items[iid]
        if src.exists():
            self._open(src)
        else:
            messagebox.showwarning("Missing file", f"Source file not found:\n{src}")
        dst = self.results.get(iid)
        if dst is not None and dst.exists():
            self._open(dst)

    def open_output_folder(self):
        typed = self.out_dir.get().strip()
        if typed:
            folder = Path(typed)
            folder.mkdir(parents=True, exist_ok=True)
            self._open(folder)
            return
        # No fixed output folder: use the one belonging to the selected (or latest) converted file
        sel = [i for i in self.tree.selection() if i in self.results]
        if sel:
            dst = self.results[sel[0]]
        elif self.results:
            dst = list(self.results.values())[-1]
        else:
            messagebox.showinfo("Nothing converted yet",
                                "Convert some files first, or choose an output folder.")
            return
        self._open(dst.parent)

    # ----------------------------------------------------------- conversion
    def _build_jobs(self):
        """Files currently shown in the list (search filter applied), with their per-file overrides."""
        jobs = []
        for iid in self.tree.get_children(""):
            ov = self.overrides.get(iid, {})
            extra = {}
            if ov.get("chroma"):
                extra["subsampling"] = ov["chroma"]
            if ov.get("sens") is not None:
                extra["sensitivity"] = ov["sens"]
            jobs.append((iid, self.items[iid], extra))
        return jobs

    def _confirm_overwrite(self, jobs, out_dir, fmt) -> bool:
        """Overwrite is destructive: say how many existing files will be replaced and ask once per session."""
        if getattr(self, "_overwrite_ok", False):
            return True
        existing = cv.count_existing_outputs([p for _, p, _ in jobs], out_dir, fmt)
        if existing == 0:
            return True
        ok = messagebox.askyesno(
            "Replace existing files?",
            f"{existing} file{'s' if existing != 1 else ''} in the output folder will be replaced "
            f"by new conversions.\n\nThe old versions cannot be recovered. Continue?")
        self._overwrite_ok = bool(ok)  # asked once per session; turn Overwrite off to keep existing files
        return bool(ok)

    def start(self):
        if not self.items:
            messagebox.showinfo("No files", "Add some files first.")
            return
        jobs = self._build_jobs()
        if not jobs:
            messagebox.showinfo("No files match", "No files match the current search.")
            return
        out = Path(self.out_dir.get()) if self.out_dir.get().strip() else None
        try:
            video_seconds = max(0.0, float(self.video_time.get() or 0))
        except (tk.TclError, ValueError):
            video_seconds = 0.0
        opts = dict(
            out_dir=out,
            quality=self.quality.get(),
            resize_pct=self.resize.get(),
            overwrite=self.overwrite.get(),
            keep_exif=self.keep_exif.get(),
            video_seconds=video_seconds,
            fmt=self._fmt(),
            progressive=self.progressive.get(),
            subsampling=self.subsampling.get(),
            sensitivity=self.sensitivity.get(),
            optimize=self.optimize.get(),
            lossless=self.lossless.get(),
            png_level=max(0, min(9, int(self.png_level.get()))),
            tiff_compression=self.tiff_comp.get(),
            keep_date=self.keep_date.get(),
            strip_gps=self.strip_gps.get(),
        )
        if opts["overwrite"] and not self._confirm_overwrite(jobs, out, opts["fmt"]):
            return
        w = self.workers.get()
        workers = cv.default_workers() if w == "auto" else max(1, int(w))
        self._save_settings()
        for iid, _, _ in jobs:
            self.results.pop(iid, None)
            self._status(iid, "Queued", "")
        self.progress.config(maximum=len(jobs), value=0)
        self.stop_flag.clear()
        self.go_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.summary.config(text="Converting…")
        self.worker = threading.Thread(target=self._work, args=(jobs, opts, workers), daemon=True)
        self.worker.start()
        self.after(100, self._poll)

    def stop(self):
        self.stop_flag.set()
        self.stop_btn.config(state="disabled")

    def _work(self, jobs, opts, workers):
        stats = {"ok": 0, "skipped": 0, "error": 0}
        try:
            stats = cv.run_batch(jobs, opts, workers,
                                 on_start=lambda iid: self.q.put(("status", iid, "Converting…", "busy")),
                                 on_done=lambda iid, r: self.q.put(("done", iid, r)),
                                 stop=self.stop_flag.is_set)
        finally:
            self.q.put(("finished", stats))

    def _fill_status(self) -> None:
        try:
            others = sum(int(self.tree.column(c, "width")) for c in self._cols if c != "status")
            self.tree.column("status", width=max(self._status_w, self.tree.winfo_width() - others))
        except Exception:  # noqa: BLE001
            pass

    def _on_hscroll(self, lo, hi):
        """Show the sideways scrollbar only while the table is wider than the window."""
        self._hsb.set(lo, hi)
        needed = float(lo) > 0.0 or float(hi) < 1.0
        if needed and not self._hsb_shown:
            self._hsb.pack(side="bottom", fill="x", before=self.tree)
            self._hsb_shown = True
        elif not needed and self._hsb_shown:
            self._hsb.pack_forget()
            self._hsb_shown = False

    def _status(self, iid: str, text: str, tag: str):
        try:
            self.tree.set(iid, "status", text)
            self.tree.item(iid, tags=(tag,) if tag else ())
            need = tkfont.nametofont("TkDefaultFont").measure(text) + self.S(40)
            if need > self._status_w:  # widen the column so the whole message can be scrolled into view
                self._status_w = need
                self._fill_status()
        except tk.TclError:  # row was removed while converting
            pass

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "status":
                    self._status(msg[1], msg[2], msg[3])
                elif kind == "done":
                    iid, r = msg[1], msg[2]
                    if r.dst is not None and r.status in ("ok", "skipped"):
                        self.results[iid] = r.dst
                    if r.status == "ok":
                        self._status(iid, f"✓  {cv.human(r.in_size)} → {cv.human(r.out_size)}  ·  {r.message}", "ok")
                    elif r.status == "skipped":
                        self._status(iid, "Skipped (already exists)", "skip")
                    else:
                        self._status(iid, f"✕  {r.message}", "err")
                    self.progress["value"] += 1
                elif kind == "finished":
                    s = msg[1]
                    self.go_btn.config(state="normal")
                    self.stop_btn.config(state="disabled")
                    self._refresh_counts()
                    parts = [f"{s['ok']} converted"]
                    if s["skipped"]:
                        parts.append(f"{s['skipped']} skipped")
                    if s["error"]:
                        parts.append(f"{s['error']} failed")
                    self.summary.config(text="  ·  ".join(parts))
                    return
        except queue.Empty:
            pass
        self.after(100, self._poll)


def already_running() -> bool:
    """True if another copy of the program holds the window open (Windows only)."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes

        handle = ctypes.windll.kernel32.CreateMutexW(None, False, "JpegIsKing.SingleInstance")  # type: ignore[attr-defined]
        already = ctypes.windll.kernel32.GetLastError() == 183  # type: ignore[attr-defined]  # ERROR_ALREADY_EXISTS
        _MUTEX.append(handle)  # keep the handle alive for as long as this process runs
        return already
    except Exception:  # noqa: BLE001
        return False


_MUTEX: list = []


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()  # a frozen exe must never re-run itself as a "worker" and open more windows
    if "--inspect" in sys.argv[1:]:
        for f in sys.argv[1:]:
            if f != "--inspect":
                print(cv.describe_dng(Path(f)))
        sys.exit(0)
    if "--selftest" in sys.argv[1:]:
        # jpeg_is_king.exe --selftest [sample files...]  ->  writes selftest.txt next to the program, no window
        sys.exit(cv.run_selftest_cli([a for a in sys.argv[1:] if a != "--selftest"]))
    if already_running():
        sys.exit(0)
    enable_dpi_awareness()
    if sys.platform.startswith("win"):
        try:  # own taskbar identity, so Windows shows this icon instead of python.exe's
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("JpegIsKing.App")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    App().mainloop()
