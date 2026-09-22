from __future__ import annotations

import argparse
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from cua_jev.config import load_local_env
from cua_jev.suites import SUITE_NAMES
from cua_jev.ui.manager import TASK_CATALOG, RunManager

PROFILE_LABELS = {"adaptive": "HYBRID ACTION SPACE", "visible": "GUI ONLY"}
PROFILE_FILES = {"adaptive": "hybrid", "visible": "gui-only"}


def _dependencies():
    try:
        import imageio_ffmpeg
        import numpy
        from PIL import Image, ImageDraw, ImageFont, ImageGrab
    except ImportError as exc:
        raise SystemExit('install the recorder with: python -m pip install -e ".[recording]"') from exc
    return imageio_ffmpeg, numpy, Image, ImageDraw, ImageFont, ImageGrab


def _font(image_font, size: int, *, mono: bool = False):
    candidates = (
        [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "consola.ttf"]
        if mono
        else [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"]
    )
    for path in candidates:
        if path.is_file():
            return image_font.truetype(str(path), size)
    return image_font.load_default()


def _draw_hud(frame, state: dict[str, Any], image, image_draw, image_font):
    overlay = image.new("RGBA", frame.size, (0, 0, 0, 0))
    draw = image_draw.Draw(overlay)
    width, height = frame.size
    panel_width = min(620, width - 48)
    x0, y0, x1, y1 = 24, height - 150, 24 + panel_width, height - 24
    draw.rounded_rectangle((x0, y0, x1, y1), radius=16, fill=(24, 24, 23, 232))
    draw.rounded_rectangle((x0 + 18, y0 + 18, x0 + 25, y0 + 25), radius=4, fill=(93, 166, 113, 255))
    label_font = _font(image_font, 15, mono=True)
    body_font = _font(image_font, 22)
    meta_font = _font(image_font, 14, mono=True)
    accent = (213, 125, 94, 255)
    muted = (180, 180, 172, 255)
    draw.text((x0 + 38, y0 + 13), "CUA-JEV", font=label_font, fill=accent)
    profile = str(state.get("profile_label", "PREPARING"))
    draw.text((x0 + 124, y0 + 13), profile, font=label_font, fill=muted)
    task = str(state.get("task", "")).upper()
    step = int(state.get("step", 0))
    total = int(state.get("total", 0))
    candidate = str(state.get("candidate", "Waiting for first decision"))
    draw.text((x0 + 18, y0 + 48), f"{task}  ·  STEP {step:02d} / {total:02d}", font=body_font, fill="white")
    draw.text((x0 + 18, y0 + 85), candidate[:54], font=meta_font, fill=muted)
    channel = str(state.get("channel", "—")).upper()
    status = str(state.get("status", "starting")).upper()
    badge = f"{channel}  ·  {status}"
    badge_box = draw.textbbox((0, 0), badge, font=meta_font)
    badge_width = badge_box[2] - badge_box[0] + 24
    draw.rounded_rectangle(
        (x1 - badge_width - 18, y0 + 12, x1 - 18, y0 + 39),
        radius=7,
        fill=(67, 67, 63, 255),
    )
    draw.text((x1 - badge_width - 6, y0 + 17), badge, font=meta_font, fill="white")
    return image.alpha_composite(frame.convert("RGBA"), overlay).convert("RGB")


class DesktopRecorder:
    def __init__(
        self, output: Path, state: dict[str, Any], *, fps: int = 12, max_width: int = 1920
    ) -> None:
        self.output = output
        self.state = state
        self.fps = fps
        self.max_width = max_width
        self.stop_event = threading.Event()
        self.error: BaseException | None = None
        self.thread = threading.Thread(target=self._capture, name="cua-jev-recorder", daemon=True)

    def start(self) -> None:
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=30)
        if self.thread.is_alive():
            raise RuntimeError("screen recorder did not stop")
        if self.error:
            raise RuntimeError(f"screen recording failed: {self.error}") from self.error

    def _capture(self) -> None:
        imageio_ffmpeg, numpy, image, image_draw, image_font, image_grab = _dependencies()
        writer = None
        try:
            first = image_grab.grab().convert("RGB")
            scale = min(1.0, self.max_width / first.width)
            width = int(first.width * scale) // 2 * 2
            height = int(first.height * scale) // 2 * 2
            writer = imageio_ffmpeg.write_frames(
                str(self.output),
                (width, height),
                fps=self.fps,
                codec="libx264",
                pix_fmt_in="rgb24",
                pix_fmt_out="yuv420p",
                quality=7,
                macro_block_size=2,
                output_params=["-movflags", "+faststart"],
            )
            writer.send(None)
            next_frame = time.perf_counter()
            while not self.stop_event.is_set():
                frame = image_grab.grab().convert("RGB")
                if frame.size != (width, height):
                    frame = frame.resize((width, height), image.Resampling.LANCZOS)
                frame = _draw_hud(frame, dict(self.state), image, image_draw, image_font)
                writer.send(numpy.asarray(frame).tobytes())
                next_frame += 1 / self.fps
                self.stop_event.wait(max(0.0, next_frame - time.perf_counter()))
        except BaseException as exc:
            self.error = exc
        finally:
            if writer is not None:
                writer.close()


def _update_state(state: dict[str, Any], detail: dict[str, Any]) -> None:
    events = detail.get("events") or []
    decisions = [event["payload"] for event in events if event.get("kind") == "decision"]
    receipts = [event["payload"] for event in events if event.get("kind") == "receipt"]
    state["step"] = len(decisions)
    state["status"] = detail.get("status", "running")
    if decisions:
        state["candidate"] = decisions[-1].get("candidate_id", "decision")
    if receipts:
        state["channel"] = receipts[-1].get("channel", "—")


def run_one(
    manager: RunManager,
    task: str,
    profile: str,
    output: Path | None,
    *,
    policy: str,
    fallback: bool,
    fps: int,
    max_width: int,
    tail_seconds: float,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "task": task,
        "profile_label": f"{policy.upper()} · {PROFILE_LABELS[profile]}",
        "total": TASK_CATALOG[task]["steps"],
        "step": 0,
        "candidate": "Preparing clean task state",
        "channel": "—",
        "status": "starting",
    }
    recorder = DesktopRecorder(output, state, fps=fps, max_width=max_width) if output else None
    try:
        if recorder:
            recorder.start()
            time.sleep(0.8)
        record = manager.create(
            {
                "task": task,
                "policy": policy,
                "visible_desktop": True,
                "execution_profile": profile,
                "policy_fallback": fallback,
            }
        )
        print(f"[{task}/{profile}] run={record['id']} started", flush=True)
        while True:
            detail = manager.detail(record["id"])
            _update_state(state, detail)
            if detail["status"] != "running":
                break
            time.sleep(0.25)
        if recorder:
            time.sleep(tail_seconds)
        print(
            f"[{task}/{profile}] status={detail['status']} success={detail['metrics']['success']} ",
            f"wall={detail['metrics']['wall_time_ms']}ms",
            flush=True,
        )
        return {
            "run_id": record["id"],
            "task": task,
            "profile": profile,
            "video": str(output) if output else None,
            "status": detail["status"],
            "metrics": detail["metrics"],
        }
    finally:
        if recorder:
            recorder.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run v2 paired experiments and record publishable demos")
    parser.add_argument("--task", choices=(*SUITE_NAMES, "all"), default="all")
    parser.add_argument("--profile", choices=("adaptive", "visible", "both"), default="both")
    parser.add_argument("--policy", choices=("jev", "rule"), default="jev")
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--no-record", action="store_true")
    parser.add_argument("--policy-fallback", action="store_true")
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--max-width", type=int, default=1920)
    parser.add_argument("--tail-seconds", type=float, default=1.5)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive")

    root = Path(__file__).resolve().parents[1]
    load_local_env(root / ".env")
    if args.policy == "jev" and not os.getenv("TYPESAFE_API_KEY"):
        parser.error("TYPESAFE_API_KEY is missing; add it to the ignored local .env file")
    _dependencies()

    tasks = SUITE_NAMES if args.task == "all" else (args.task,)
    profiles = ("adaptive", "visible") if args.profile == "both" else (args.profile,)
    output_dir = root / "artifacts" / "demos"
    manager = RunManager(root)
    results = []
    for task in tasks:
        for profile in profiles:
            for sample in range(args.samples):
                video = None
                if not args.no_record and sample == 0:
                    video = output_dir / f"{task}-{PROFILE_FILES[profile]}.mp4"
                results.append(
                    run_one(
                        manager,
                        task,
                        profile,
                        video,
                        policy=args.policy,
                        fallback=args.policy_fallback,
                        fps=args.fps,
                        max_width=args.max_width,
                        tail_seconds=args.tail_seconds,
                    )
                )
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = output_dir / "manifest.json"
    manifest.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    passed = all(item["metrics"]["success"] for item in results)
    print(f"manifest={manifest} passed={passed}", flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
