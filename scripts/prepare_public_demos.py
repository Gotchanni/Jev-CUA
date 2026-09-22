"""Make reviewed public copies of local demo recordings (never modify originals)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts" / "demos"
PUBLIC = ROOT / "website" / "media"
NAMES = (
    "edge-hybrid",
    "edge-gui-only",
    "excel-hybrid",
    "excel-gui-only",
    "vscode-hybrid",
    "vscode-gui-only",
    "explorer-hybrid",
    "explorer-gui-only",
)


def main() -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    for name in NAMES:
        source = SOURCE / f"{name}.mp4"
        target = PUBLIC / f"{name}.mp4"
        if not source.is_file():
            raise FileNotFoundError(source)
        if name.startswith("explorer-"):
            # The Explorer breadcrumb contains the host username and local run path.
            filters = "crop=iw:ih-65:0:65"
        elif name == "vscode-hybrid":
            # This short run stays on the welcome page: hide its Recent list.
            filters = "drawbox=x=570:y=448:w=520:h=150:color=white:t=fill"
        elif name == "vscode-gui-only":
            # Hide Recent at startup and the PowerShell module path in terminal output.
            filters = (
                "drawbox=x=570:y=448:w=520:h=150:color=white:t=fill:enable='lt(t,4)',"
                "drawbox=x=270:y=862:w=1360:h=84:color=white:t=fill:enable='gte(t,4)'"
            )
        else:
            filters = ""
        if not filters and name != "edge-gui-only":
            shutil.copy2(source, target)
            continue
        args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
        if name == "edge-gui-only":
            # The initial browser activation shows the desktop behind the window.
            args.extend(["-ss", "1.5"])
        args.extend(["-i", str(source)])
        if filters:
            args.extend(["-vf", filters])
        args.extend(
            [
                "-an",
                "-c:v",
                "libx264",
                "-crf",
                "23",
                "-preset",
                "medium",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(target),
            ]
        )
        subprocess.run(args, check=True)
        print(f"Prepared {target.name}")


if __name__ == "__main__":
    main()
