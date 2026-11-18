# jpeg_is_king: RAW / HEIC / Video → JPEG, WebP, PNG, TIFF converter

| Input | Result |
|---|---|
| `.ARW` `.DNG` (also `.CR2 .CR3 .NEF .RAF .ORF .RW2`) | RAW → image |
| `.HEIC` `.HEIF` | iPhone photos → image |
| `.TIFF` `.PNG` `.JPG` `.WEBP` `.BMP` | convert / compress |
| `.MOV` `.MP4` `.M4V` `.AVI` `.MKV` | one frame (default: first) → image |

## Output formats and options

| Format | Options |
|---|---|
| **JPEG** | quality 1–100, progressive, chroma subsampling (**auto** / 4:4:4 / 4:2:2 / 4:2:0), auto sensitivity, optimize |
| **WebP** | quality 1–100, lossless mode |
| **PNG** | compression level 0–9 (lossless, keeps transparency; 9 = smallest, slowest) |
| **TIFF** | compression: lzw / deflate / jpeg (uses quality) / none |

All formats also support the resize slider (10–100 %), overwrite / skip existing,
batch + folder import (optional subfolders). EXIF is kept for non-RAW files when
writing JPEG, WebP or PNG. JPEG flattens transparency onto white; WebP, PNG and
TIFF keep it.

## Auto chroma subsampling (JPEG)
JPEG stores colour at lower resolution than brightness (4:2:0). That is fine for photos but smears
thin coloured lines, coloured text and screenshots. In **auto** mode (the default) each image is
checked: the converter simulates 4:2:0 and measures how many pixels would visibly change colour.
If that share is above a limit, the image is saved as 4:4:4, otherwise as 4:2:0.

**Sensitivity (1–100)** sets the limit: higher = more images get 4:4:4.
1 → 10 %, 50 (default) → 1 %, 100 → 0.1 % of pixels damaged. Normal photos score well under 0.2 %,
line art / text / screenshots score several %. Very noisy high-ISO photos can score high; lower the
sensitivity for those. The Status column shows what was chosen, e.g. `6024x4024 4:2:0 auto`.

## Using the window
The window has two panes: your **files** on the left, the **conversion and output settings** on the
right. Only the settings that apply to the chosen format are shown.

- **Search** filters the list by file name (case-insensitive). Several words must all match
  (`dsc 017`), and `*` / `?` wildcards work (`dsc017*`). **Select shown** (or Ctrl+A) selects just
  the files that match.
- When files are selected and the format is JPEG, a bar appears under the list. Pick a chroma
  subsampling and/or a sensitivity and click **Apply** (**Reset** removes the override). The
  *Chroma* column shows which files have one. Overrides survive changing or clearing the search.
- While a search is active the button reads **Convert N shown** and only the matching files are
  converted; with an empty search it converts everything in the list.
- **Double-click a row** (or select it and press Enter) to open the source image; if it has been
  converted, the converted image opens too. **Remove** / the Delete key takes the selected rows out
  of the list (nothing is deleted from disk).
- **Open output folder** opens the chosen output folder, or the folder of the selected / latest
  converted file.
- Small **ⓘ** badges explain a setting when you hover or click them; buttons show a short tooltip
  after a moment. Status text turns green for converted files, red for errors.
- Dark theme throughout (including the Windows title bar). Text is rendered crisply on high-DPI screens.

## Run from source
```
pip install -r requirements.txt
python app.py                                          # GUI
python converter.py shots/ -q 80 -s 50 -r -o out       # JPEG, command line
python converter.py shots/ -f webp -q 80               # WebP
python converter.py shots/ --progressive --subsampling 4:4:4
python converter.py shots/ --subsampling auto --sensitivity 70   # auto is the default
python converter.py shots/ -f png --png-level 9
python converter.py shots/ -f tiff --tiff-compression deflate
```
Video needs `ffmpeg` on PATH (or `ffmpeg.exe` next to the scripts).

## Does it work on my computer? (self-test)
Format support depends on native libraries, so the program can test itself:

```
python converter.py --selftest                       # from source
python converter.py --selftest DSC01741.ARW IMG_0001.HEIC clip.MOV   # also convert your own samples
jpeg_is_king.exe --selftest DSC01741.ARW                # the built program (writes selftest.txt next to it)
```
It converts generated test images and videos (every output format, JPG/PNG/TIFF/WebP/BMP input, MP4/MOV/M4V/AVI/MKV
video, colour-profile handling, corrupt/empty/missing files) and prints `PASS`, `FAIL` or `SKIP` per item.
`SKIP` means that library is not available (rawpy for RAW, pillow-heif for HEIC, FFmpeg for video).
RAW and HEIC **decoding** is only proven when you pass a real sample file of that type.

| Format | Needs | Notes |
|---|---|---|
| RAW (ARW, DNG, CR2 ...) | `rawpy` (bundles LibRaw) | Tried in order: full RAW development, LibRaw's own preview, then the largest JPEG found inside the file. iPhone ProRAW DNGs that LibRaw rejects ("Unsupported file format or not RAW file") therefore still convert, but from the embedded preview (usually smaller than full size); the Status column says `embedded preview used` plus its size. Full-resolution development of those files needs a newer LibRaw (`pip install -U rawpy`) or exporting them from the Photos app / Lightroom as DNG without compression. |
| HEIC / HEIF | `pillow-heif` | The colour profile (e.g. iPhone Display P3) is kept. |
| Video | FFmpeg | A copy that does not run (e.g. a Chocolatey or Scoop launcher, error "Could not read shim file") is detected and skipped; the build follows the launcher to the real `ffmpeg.exe`, or downloads a standalone one. Frames past the end of a clip fall back to the first frame. HDR (HLG / Dolby Vision) footage is not tone-mapped, so its colours look flat. |

## Build the Windows .exe
Double-click `build_exe.bat` (or run `python build_exe.py`). The build:
1. checks that Pillow, rawpy, pillow-heif and PyInstaller are installed (a build without rawpy or
   pillow-heif would silently not open RAW / HEIC files, so it stops instead),
2. finds or downloads `ffmpeg.exe` and checks that it runs **when copied on its own** (Chocolatey/Scoop launchers fail this, so the real program is used instead),
3. builds `dist\jpeg_is_king.exe`,
4. runs the finished program with `--selftest` and shows the report (also saved as `dist\selftest.txt`).

Options: `--sample C:\photos\DSC01741.ARW` (repeatable) tests real files in step 4;
the program is built as a single flat folder (`dist\jpeg_is_king\jpeg_is_king.exe` with all its files beside it, no sub-folder; keep them together), which starts much faster than a single
file; `--onefile` builds one `dist\jpeg_is_king.exe` instead (easier to share, but it unpacks ~100 MB every time it starts); `--ffmpeg PATH` bundles your own FFmpeg
(a smaller build makes the exe smaller); `--console` keeps a console window for debugging.
Use Python 3.11-3.13: rawpy and pillow-heif may not have pre-built packages for newer versions.
Unsigned single-file programs are sometimes flagged by antivirus software; the `--onedir` build usually is not.

## Notes
- Without an output folder, files go to a `converted` folder next to each source.
- If two inputs share a name (e.g. `IMG_1.ARW` + `IMG_1.DNG`), the second gets `_1`.
- Video output is named `<name>_frame.<ext>`; set "Video frame at (s)" to grab a later frame.
- Files are written to a temporary `.part` file and renamed when complete, so a crash or a full disk never leaves a broken output file.
- When shrinking a RAW file to 50 % or less, it is decoded at half size (about 4x faster, same result).
- Images above 89 megapixels (large panoramas / scans) are opened normally.
- The app icon is drawn by `make_icon.py` (`python make_icon.py` rewrites `icon.ico` / `icon.png`); the build embeds it in the .exe and the window and taskbar use it.
- Long status or error messages: a sideways scroll bar appears under the list only when a message does not fit; scroll it to read the whole text.
- The settings panel on the right scrolls (mouse wheel, or the bar that appears) when the window is too short to show every setting.
- Start-up animation (plays inside the main window, which opens only once): the JPEG crown slices the other formats in half. Click or press any key to skip it; `--no-splash` (or the environment variable `JPEG_IS_KING_NO_SPLASH=1`) turns it off. If it cannot be shown, the app simply opens.
- Several files convert at the same time (**Parallel files**: auto = up to 4; lower it if very large RAW files use too much memory). `-j N` does the same on the command line.
- Your settings (format, quality, folders, options, window size) are remembered in `%APPDATA%\jpeg_is_king\settings.json`.
- Drop files or folders onto the window to add them (needs the optional `tkinterdnd2` package, installed by `requirements.txt`).
- **Remove GPS location** strips GPS from the copied EXIF data; **Keep original date** gives each output the original's modified date.
- HDR video (iPhone HLG / Dolby Vision) is tone-mapped to normal colours when your FFmpeg supports it; the status says `HDR tone-mapped`.
- Not implemented: full-resolution decoding of Apple ProRAW DNG (JPEG-XL). The preview inside the file is used instead; a plain decode of the raw data would look flatter than Apple's own rendering.
- If the program ever opens oddly, `%APPDATA%\jpeg_is_king\startup.log` records each start (with its process id) and when the window was shown.
- The window always opens centred on the monitor where your mouse is, sized for that screen (720p to 4K, ultrawide, any display scaling). Only its size is remembered, never its position.
- RAW files (ARW, DNG, NEF ...) keep their camera, lens, date-taken and exposure EXIF in the converted file (the large maker-notes and DNG-specific data are left out); GPS is removed when 'Remove GPS location' is on.
- With **Overwrite existing files** on, you are asked once per session how many existing files will be replaced.
