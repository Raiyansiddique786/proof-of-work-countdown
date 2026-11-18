LOCAL EXPORT TOOLS

Refresh.command or .venv/bin/python scripts/refresh.py creates current dated
images and updates final-entry/final-lock-screen.png and cover.png.
It never changes milestone status, the Mac wallpaper, reminders or public files.

The separate build_summary.py creates the one-page summary from the latest
export manifest. It requires ReportLab. The existing bundled Python runtime
has this dependency; another computer may install reportlab in its own venv.

Ordinary image refresh needs only requirements.txt (Pillow) and the bundled font.
After changing text/configuration, inspect the full export and reduced preview.
After a new release, copy only reviewed public files to the public repository.
Do not publish evidence/history or private local process logs.
