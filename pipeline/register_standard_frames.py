"""Register extracted state frames to the shared Nazar baseline with zero ground jitter."""

import argparse
from pathlib import Path

from PIL import Image


def register_row(paths, *, jumping):
    poses = []
    for path in paths:
        with Image.open(path) as opened:
            poses.append(opened.convert("RGBA"))
    bounds = [pose.getbbox() for pose in poses]
    if not bounds or any(box is None for box in bounds):
        raise ValueError("All frames in the row must contain visible artwork.")

    scale = 0.95
    target_baseline = 195
    bottoms = [box[3] for box in bounds]
    jump_baseline = max(bottoms)
    for path, pose, (left, top, right, bottom) in zip(paths, poses, bounds, strict=True):
        subject = pose.crop((left, top, right, bottom))
        subject = subject.resize(
            (round(subject.width * scale), round(subject.height * scale)),
            Image.Resampling.LANCZOS,
        )
        x = round(96 + (left - 96) * scale)
        if jumping:
            # Preserve intentional vertical airborne arc while landing cleanly on target_baseline
            y = round(target_baseline + (top - jump_baseline) * scale)
        else:
            # Lock grounded states cleanly to target_baseline to eliminate 1-3px foot bounce
            y = target_baseline - subject.height
        if not (3 <= y and y + subject.height <= 205):
            raise ValueError(f"Baseline registration would clip {path}")
        canvas = Image.new("RGBA", pose.size)
        canvas.alpha_composite(subject, (x, y))
        yield path, canvas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frames_root", type=Path)
    args = parser.parse_args()

    registered = []
    for row in sorted(path for path in args.frames_root.iterdir() if path.is_dir()):
        paths = sorted(row.glob("*.png"))
        registered.extend(register_row(paths, jumping=row.name == "jumping"))

    for path, canvas in registered:
        canvas.save(path, optimize=True, compress_level=9)
    print(f"Registered {len(registered)} frames.")


if __name__ == "__main__":
    main()
