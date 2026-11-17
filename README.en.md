# Matrix Wallpaper · 3.6

[Русское руководство](README.md)

Animated wallpaper that recreates an image with falling characters. Built for **XFCE on X11**, with desktop icons remaining visible and usable. Windows and Wayland/Hyprland are not supported by this version.

## Install with one command

Run as your normal user with curl installed:

```bash
curl -fsSL https://raw.githubusercontent.com/DanteFroMGiti/matrix-wallpaper/main/install-online.sh | bash
```

The installer downloads release 3.6.0, checks SHA-256, installs dependencies using pacman or apt-get, compiles the renderer and creates an application menu entry. Automatic dependency installation supports Arch/CachyOS/Manjaro and Debian/Ubuntu/Linux Mint. It may ask for your sudo password for system packages. XFCE/X11 with a compositor and a running user systemd must already be available. No GitHub account is required.

Open **Matrix Wallpaper** from the application menu, or run `~/.local/bin/matrix-wallpaper`. The wallpaper continues running when you close the editor.

## Language and guide

Choose **Русский** or **English** in the top left corner. The default is Russian. Switching takes effect immediately, including tooltips, dialogs, the searchable guide and the tray menu. The language is remembered between launches. Your current edits, image, text, profile names, monitor selection and resource limits are preserved. Applying wallpaper settings is not required to save the language.

Press **F1** or click **Guide** for the full manual in the selected language. Hover over controls for explanations, dependencies and examples. Search covers both guide topics and individual parameters. Ctrl+F focuses the guide search; Esc closes the guide.

## Basic workflow

1. Choose an image in **Appearance**.
2. Click **Matrix** for the ready-made film effect, or configure characters, colors and movement yourself.
3. Watch the live preview, then click **Apply to desktop**.

**Stream direction** controls the glowing rain. **Character movement** independently controls the letters; choose **Stationary** to stop their drift. The character field supports your own alphabet or one phrase per line, including SQL queries. Built-in Russian profanity remains Russian when the interface language changes.

Use **Crop and select subject** to position the image and paint a subject mask. **Preserve subject detail** controls how strongly the mask preserves detail. Profiles store image and mask copies and can be shared as `.mwp` files.

Desktop files, folders and links remain interactive. Drag a selection rectangle from an empty desktop area to show the original image inside it; release to restore the animation. This is separate from painting the subject mask.

**Effects and system** contains monitor selection, rain, reveal, frame rates and automatic pauses. **Tools** contains layers, music reaction, CPU control, portable profiles and schedules. **Export MP4** creates a video from the current preview, without desktop windows, icons or an audio track.

## Updates and manual installation

Run the same one-command installer to update. Existing wallpaper settings and personal images are retained.

Alternatively, download and extract the [latest release](https://github.com/DanteFroMGiti/matrix-wallpaper/releases/latest), then run:

```bash
python3 install.py --check
python3 install.py
```

The check lists missing dependencies. Other distributions can install these manually. The separate `install.py` dependency diagnostics and the online installer's terminal output currently use Russian; the application interface supports both languages.

After downloading the online installer, `bash install-online.sh --dry-run` shows its plan and `--skip-dependencies` skips system packages when they are already installed.

Uninstall with `python3 install.py --uninstall`; settings and images are kept. Add `--purge-data` only if you also want to delete personal application data.

Language preferences are stored separately in `~/.config/matrix-wallpaper/ui.json`. The release includes source code and a neutral default image. Personal photos, profiles and settings are not included.
