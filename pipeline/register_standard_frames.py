#!/usr/bin/env python3
"""Register standard state frames to Nazar's canonical scale, center, and baseline."""

from __future__ import annotations

import argparse
from pathlib import Path
from statistics import median
import sys

from PIL import Image

SCRIPT_DIR = Path(__file__).resolve().parent
CREATE_SCRIPTS_DIR = SCRIPT_DIR / "skills" / "create-pet" / "scripts"
if str(CREATE_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(CREATE_SCRIPTS_DIR))

from extract_strip_frames import (  # noqa: E402
    CELL_HEIGHT,
    CELL_WIDTH,
    ROW_FRAME_COUNTS,
    component_bounds,
    component_frame_groups,
    component_group_image,
    load_chroma_key,
    remove_chroma_background,
)

TARGET_BASELINE = 194.0
TARGET_CENTER_X = 96.0
TARGET_SPHERE_WIDTH = 152.0
TARGET_DIRECTIONAL_HEIGHT = 164.0
SAFE_TOP_MARGIN = 5.0
SAFE_WIDTH_LIMIT = 178.0


def clear_transparent_rgb(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    raw = bytearray(rgba.tobytes())
    for idx in range(0, len(raw), 4):
        if raw[idx + 3] == 0:
            raw[idx] = 0
            raw[idx + 1] = 0
            raw[idx + 2] = 0
    return Image.frombytes("RGBA", rgba.size, bytes(raw))


def alpha_bbox(image: Image.Image, threshold: int = 24) -> tuple[int, int, int, int]:
    alpha = image.getchannel("A")
    box = alpha.point(lambda v: 255 if v >= threshold else 0).getbbox()
    if box is None:
        box = image.getbbox()
    if box is None:
        raise ValueError("All frames in the row must contain visible artwork.")
    return box


def upper_sphere_width(image: Image.Image, bbox: tuple[int, int, int, int]) -> float:
    left, top, right, bottom = bbox
    height = bottom - top
    alpha = image.getchannel("A")
    y_start = top + int(height * 0.15)
    y_end = max(y_start + 1, top + int(height * 0.45))
    widths: list[int] = []
    for y in range(y_start, y_end):
        xs = [x for x in range(left, right) if alpha.getpixel((x, y)) > 64]
        if xs:
            widths.append(max(xs) - min(xs) + 1)
    if not widths:
        return float(right - left)
    return float(max(widths))


def weighted_center_x(image: Image.Image, bbox: tuple[int, int, int, int]) -> float:
    left, top, right, bottom = bbox
    alpha = image.getchannel("A")
    # Anchor horizontally on the lower 60% of the body/feet so asymmetric raised limbs do not pull the torso sideways
    band_top = top + int((bottom - top) * 0.40)
    total_w = 0.0
    sum_x = 0.0
    for y in range(band_top, bottom):
        for x in range(left, right):
            a = alpha.getpixel((x, y))
            if a > 24:
                sum_x += (x + 0.5) * a
                total_w += a
    if total_w <= 0:
        return (left + right) / 2.0
    return sum_x / total_w


def transform_pose_to_cell(
    pose: Image.Image,
    *,
    scale: float,
    src_cx: float,
    src_bottom: float,
    dst_cx: float,
    dst_bottom: float,
) -> Image.Image:
    inv_s = 1.0 / scale
    tx = src_cx - dst_cx * inv_s
    ty = src_bottom - dst_bottom * inv_s
    placed = pose.transform(
        (CELL_WIDTH, CELL_HEIGHT),
        Image.Transform.AFFINE,
        (inv_s, 0.0, tx, 0.0, inv_s, ty),
        resample=Image.Resampling.BICUBIC,
    )
    return clear_transparent_rgb(placed)


def compute_row_scale(state: str, poses: list[Image.Image], bboxes: list[tuple[int, int, int, int]]) -> float:
    max_w = max(b[2] - b[0] for b in bboxes)
    heights = [b[3] - b[1] for b in bboxes]
    med_h = float(median(heights))

    if state in {"running-right", "running-left"}:
        desired = TARGET_DIRECTIONAL_HEIGHT / med_h
    elif state == "jumping":
        sphere_w = upper_sphere_width(poses[0], bboxes[0])
        desired = 150.0 / sphere_w
    else:
        sphere_w = upper_sphere_width(poses[0], bboxes[0])
        desired = TARGET_SPHERE_WIDTH / sphere_w

    max_grounded_h = max(heights) if state != "jumping" else max(heights[0], heights[-1])
    limits = [
        desired,
        SAFE_WIDTH_LIMIT / max(1, max_w),
        (TARGET_BASELINE - SAFE_TOP_MARGIN) / max(1, max_grounded_h),
    ]
    return min(limits)


def register_poses(
    state: str,
    paths: list[Path],
    poses: list[Image.Image],
    strip_bboxes: list[tuple[int, int, int, int]] | None = None,
) -> tuple[list[tuple[Path, Image.Image]], str]:
    local_bboxes = [alpha_bbox(pose) for pose in poses]
    scale = compute_row_scale(state, poses, local_bboxes)

    # Vertical displacements come from strip coordinates when extracting directly from decoded/,
    # or from local cell coordinates when registering already-extracted frames.
    ref_bboxes = strip_bboxes if strip_bboxes is not None else local_bboxes
    ref_bottoms = [float(b[3]) for b in ref_bboxes]
    row_cx_offsets = [weighted_center_x(p, lb) for p, lb in zip(poses, local_bboxes)]

    if state == "jumping":
        ground_ref = max(ref_bottoms)
        raw_lifts = [max(0.0, ground_ref - b_ref) for b_ref in ref_bottoms]
        peak_idx = max(range(len(raw_lifts)), key=lambda i: raw_lifts[i])
        peak_raw_lift = raw_lifts[peak_idx]
        apex_h_scaled = (local_bboxes[peak_idx][3] - local_bboxes[peak_idx][1]) * scale
        max_safe_lift = max(12.0, (TARGET_BASELINE - SAFE_TOP_MARGIN) - apex_h_scaled)
        lift_scale = min(scale, max_safe_lift / peak_raw_lift) if peak_raw_lift > 0 else scale
    else:
        ground_ref = float(median(ref_bottoms))
        lift_scale = scale

    outputs: list[tuple[Path, Image.Image]] = []
    for idx, (path, pose, lb, ref_b, src_cx) in enumerate(
        zip(paths, poses, local_bboxes, ref_bottoms, row_cx_offsets, strict=True)
    ):
        local_bottom = float(lb[3])
        if state == "jumping":
            lift_px = max(0.0, ground_ref - ref_b) * lift_scale
            if len(poses) == 5 and peak_idx == 2 and idx in (1, 3):
                # Carry two-thirds of the peak lift at the two in-between poses.
                lift_px = max(lift_px, peak_raw_lift * lift_scale * (2.0 / 3.0))
            dst_bottom = TARGET_BASELINE - lift_px
        else:
            delta_px = (ref_b - ground_ref) * scale
            # Clamp minor ground foot-contact jitter to <= 0.5px while preserving deliberate lean
            # Review pose index 3 stays grounded even as its silhouette compresses.
            if abs(delta_px) <= 1.6 or (state == "review" and idx == 3):
                delta_px = 0.0
            dst_bottom = min(float(CELL_HEIGHT - 4), TARGET_BASELINE + delta_px)

        canvas = transform_pose_to_cell(
            pose,
            scale=scale,
            src_cx=src_cx,
            src_bottom=local_bottom,
            dst_cx=TARGET_CENTER_X,
            dst_bottom=dst_bottom,
        )
        cb = canvas.getbbox()
        if cb is None or cb[1] < 2 or cb[3] > CELL_HEIGHT - 2:
            raise ValueError(f"Baseline registration would clip {path} (bbox={cb})")
        outputs.append((path, canvas))

    summary = (
        f"{state} baseline {round(ground_ref)} mapped to {round(TARGET_BASELINE)} "
        f"at shared row scale {scale:.4f}"
    )
    return outputs, summary


def load_from_decoded_strip(
    strip_path: Path,
    expected_count: int,
    chroma_key: tuple[int, int, int],
    threshold: float,
) -> tuple[list[Image.Image], list[tuple[int, int, int, int]]] | None:
    if not strip_path.is_file():
        return None
    with Image.open(strip_path) as opened:
        strip = remove_chroma_background(opened, chroma_key, threshold)
    groups = component_frame_groups(strip, expected_count)
    if groups is None:
        return None
    poses = [component_group_image(strip, group, padding=8) for group in groups]
    strip_bboxes = [component_bounds(group) for group in groups]
    return poses, strip_bboxes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frames_root", type=Path)
    parser.add_argument(
        "--decoded-dir",
        type=Path,
        default=None,
        help="Optional decoded/ strip directory for single-pass high-res registration.",
    )
    parser.add_argument("--from-frames-only", action="store_true")
    parser.add_argument("--chroma-key", default=None)
    parser.add_argument("--key-threshold", type=float, default=96.0)
    parser.add_argument("--report-out", type=Path, default=None)
    args = parser.parse_args()

    frames_root = args.frames_root.expanduser().resolve()
    repo_decoded = SCRIPT_DIR.parent / "decoded"
    decoded_dir = (
        None
        if args.from_frames_only
        else (
            args.decoded_dir.expanduser().resolve()
            if args.decoded_dir is not None
            else (repo_decoded if repo_decoded.is_dir() else None)
        )
    )
    chroma_key = (
        load_chroma_key(decoded_dir, args.chroma_key)
        if decoded_dir is not None
        else (255, 0, 255)
    )

    registered: list[tuple[Path, Image.Image]] = []
    summaries: list[str] = []

    for row_dir in sorted(path for path in frames_root.iterdir() if path.is_dir()):
        state = row_dir.name
        paths = sorted(row_dir.glob("*.png"))
        if not paths:
            continue

        decoded_loaded = None
        if decoded_dir is not None and state in ROW_FRAME_COUNTS:
            decoded_loaded = load_from_decoded_strip(
                decoded_dir / f"{state}.png",
                ROW_FRAME_COUNTS[state],
                chroma_key,
                args.key_threshold,
            )

        if decoded_loaded is not None and len(decoded_loaded[0]) == len(paths):
            poses, strip_bboxes = decoded_loaded
        else:
            poses = []
            for path in paths:
                with Image.open(path) as opened:
                    poses.append(opened.convert("RGBA"))
            strip_bboxes = None

        row_outputs, summary = register_poses(state, paths, poses, strip_bboxes)
        registered.extend(row_outputs)
        summaries.append(summary)

    for path, canvas in registered:
        canvas.save(path, format="PNG", optimize=True, compress_level=9)

    if args.report_out is not None:
        report_path = args.report_out.expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("\n".join(summaries) + "\n", encoding="utf-8")

    print(f"Registered {len(registered)} frames.")


if __name__ == "__main__":
    main()
