#!/usr/bin/env python3
"""Refresh local dated images without changing progress or publishing anything."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def main():
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "config/project.json").read_text())
    as_of = datetime.now(ZoneInfo(config["timezone"])).replace(microsecond=0).isoformat()
    output = root / "exports/current"
    subprocess.run([
        sys.executable, str(root / "renderer/render.py"), str(root / "config/project.json"),
        "--as-of", as_of, "--output", str(output),
    ], check=True)
    stem = f"wallpaper-{as_of[:10]}"
    final = root / "final-entry"
    final.mkdir(exist_ok=True)
    shutil.copy2(output / f"{stem}.png", final / "final-lock-screen.png")
    shutil.copy2(output / f"{stem}-cover.png", final / "cover.png")
    print(f"Open {final / 'final-lock-screen.png'}")
    print("Inspect the new image, then replace the wallpaper manually.")
    print("Progress, reminders, device settings and public files were not changed.")
    print("For a new submission edition, regenerate the summary and review before publishing.")


if __name__ == "__main__":
    main()
