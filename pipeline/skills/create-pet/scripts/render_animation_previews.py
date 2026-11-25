#!/usr/bin/env python3
"""Render lightweight animated QA previews from extracted ChatGPT pet frames."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

LOOK_POSE_HOLD_MS = 110

ROW_DURATIONS = {
    "idle": [280, 110, 110, 140, 140, 320],
    "running-right": [120, 120, 120, 120, 120, 120, 120, 220],
    "running-left": [120, 120, 120, 120, 120, 120, 120, 220],
    "waving": [140, 140, 140, 280],
    "jumping": [140, 140, 140, 140, 280],
    "failed": [140, 140, 140, 140, 140, 140, 140, 240],
    "waiting": [150, 150, 150, 150, 150, 260],
    "running": [120, 120, 120, 120, 120, 220],
    "review": [150, 150, 150, 150, 150, 280],
}
IMAGE_SUFFIXES = {".png", ".webp", ".jpg", ".jpeg"}


def frame_files(state_dir: Path) -> list[Path]:
    if not state_dir.is_dir():
        return []
    return sorted(path for path in state_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES)


def load_frames(frames_root: Path, state: str, expected_count: int) -> list[Image.Image]:
    files = frame_files(frames_root / state)
    if len(files) != expected_count:
        raise SystemExit(
            f"{state} preview needs {expected_count} frames, found {len(files)} under {frames_root / state}"
        )
    frames = []
    for path in files:
        with Image.open(path) as opened:
            frames.append(opened.convert("RGBA"))
    return frames


def _quantize_gif_frame(frame: Image.Image) -> tuple[Image.Image, int | None]:
    if "A" not in frame.mode:
        rgb = frame.convert("RGB")
        return rgb.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE), None

    rgba = frame.convert("RGBA")
    alpha = rgba.getchannel("A")
    # Unpremultiply/composite semi-transparent edge pixels cleanly against deep navy matte
    matte = Image.new("RGBA", rgba.size, (10, 15, 36, 255))
    matte.alpha_composite(rgba)
    rgb = matte.convert("RGB")
    quantized = rgb.quantize(colors=255, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
    palette = quantized.getpalette() or [0] * (255 * 3)
    palette = (palette + [0] * 768)[:765] + [0, 0, 0]
    quantized.putpalette(palette)

    mask = alpha.point(lambda a: 255 if a < 96 else 0)
    quantized.paste(255, mask=mask)
    return quantized, 255


def save_preview(frames: list[Image.Image], durations: list[int], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    processed = [_quantize_gif_frame(frame) for frame in frames]
    gif_frames = [item[0] for item in processed]
    transparency = processed[0][1]
    save_kwargs: dict[str, object] = {
        "save_all": True,
        "append_images": gif_frames[1:],
        "duration": durations,
        "loop": 0,
        "disposal": 2,
        "optimize": True,
    }
    if transparency is not None:
        save_kwargs["transparency"] = transparency
    gif_frames[0].save(output, **save_kwargs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames-root", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    frames_root = Path(args.frames_root).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    previews = []
    for state, durations in ROW_DURATIONS.items():
        frames = load_frames(frames_root, state, len(durations))
        output = output_dir / f"{state}.gif"
        save_preview(frames, durations, output)
        previews.append({"state": state, "path": str(output), "frames": len(frames)})

    result = {"ok": True, "output_dir": str(output_dir), "previews": previews}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
