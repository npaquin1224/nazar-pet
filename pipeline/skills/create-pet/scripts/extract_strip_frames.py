#!/usr/bin/env python3
"""Extract generated horizontal row strips into 192x208 sprite frames (vectorized + anti-aliased)."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

CELL_WIDTH = 192
CELL_HEIGHT = 208
ROW_FRAME_COUNTS = {
    "idle": 6,
    "running-right": 8,
    "running-left": 8,
    "waving": 4,
    "jumping": 5,
    "failed": 8,
    "waiting": 6,
    "running": 6,
    "review": 6,
}


def parse_states(raw: str) -> list[str]:
    if raw.strip().lower() == "all":
        return list(ROW_FRAME_COUNTS)
    states = [item.strip() for item in raw.split(",") if item.strip()]
    unknown = sorted(set(states) - set(ROW_FRAME_COUNTS))
    if unknown:
        raise SystemExit(f"unknown state(s): {', '.join(unknown)}")
    return states


def parse_hex_color(value: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise SystemExit(f"invalid chroma key color: {value}; expected #RRGGBB")
    return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))


def load_chroma_key(decoded_dir: Path, override: str | None) -> tuple[int, int, int]:
    if override:
        return parse_hex_color(override)
    request_path = decoded_dir.parent / "pet_request.json"
    if request_path.is_file():
        request = json.loads(request_path.read_text(encoding="utf-8"))
        chroma_key = request.get("chroma_key")
        if isinstance(chroma_key, dict) and isinstance(chroma_key.get("hex"), str):
            return parse_hex_color(chroma_key["hex"])
    return parse_hex_color("#00FF00")


def remove_chroma_background(
    image: Image.Image,
    chroma_key: tuple[int, int, int],
    threshold: float,
    feather: float = 14.0,
) -> Image.Image:
    """Vectorized chroma keying with sub-pixel smooth anti-aliased alpha ramp."""
    arr = np.asarray(image.convert("RGBA"), dtype=np.float32).copy()
    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3]
    key = np.array(chroma_key, dtype=np.float32)

    dist = np.linalg.norm(rgb - key, axis=2)
    low = max(0.0, threshold - feather)
    high = threshold + feather

    # Smooth linear ramp across [low, high] for anti-aliased silhouette edges
    ramp = np.clip((dist - low) / max(1e-6, high - low), 0.0, 1.0)
    new_alpha = np.minimum(alpha, ramp * 255.0)

    # Decontaminate semi-transparent edge pixels against chroma key spill
    semi = (new_alpha > 0.0) & (new_alpha < 255.0)
    if np.any(semi):
        a_norm = np.clip(new_alpha[semi, None] / 255.0, 0.08, 1.0)
        unmixed = (rgb[semi] - (1.0 - a_norm) * key) / a_norm
        rgb[semi] = np.clip(unmixed, 0.0, 255.0)

    zero_mask = new_alpha <= 1.0
    rgb[zero_mask] = 0.0
    new_alpha[zero_mask] = 0.0

    arr[:, :, :3] = np.rint(rgb)
    arr[:, :, 3] = np.rint(new_alpha)
    return Image.fromarray(arr.astype(np.uint8), mode="RGBA")


def fit_to_cell(image: Image.Image) -> Image.Image:
    bbox = image.getbbox()
    target = Image.new("RGBA", (CELL_WIDTH, CELL_HEIGHT), (0, 0, 0, 0))
    if bbox is None:
        return target

    sprite = image.crop(bbox)
    max_width = CELL_WIDTH - 10
    max_height = CELL_HEIGHT - 10
    scale = min(max_width / sprite.width, max_height / sprite.height, 1.0)
    if scale != 1.0:
        sprite = sprite.resize(
            (max(1, round(sprite.width * scale)), max(1, round(sprite.height * scale))),
            Image.Resampling.LANCZOS,
        )
    left = (CELL_WIDTH - sprite.width) // 2
    top = (CELL_HEIGHT - sprite.height) // 2
    target.alpha_composite(sprite, (left, top))
    return target


def fit_viewport_to_cell(image: Image.Image) -> Image.Image:
    target = Image.new("RGBA", (CELL_WIDTH, CELL_HEIGHT), (0, 0, 0, 0))
    if image.getbbox() is None:
        return target

    viewport = image.copy()
    max_width = CELL_WIDTH - 10
    max_height = CELL_HEIGHT - 10
    scale = min(max_width / viewport.width, max_height / viewport.height, 1.0)
    if scale != 1.0:
        viewport = viewport.resize(
            (max(1, round(viewport.width * scale)), max(1, round(viewport.height * scale))),
            Image.Resampling.LANCZOS,
        )
    left = (CELL_WIDTH - viewport.width) // 2
    top = (CELL_HEIGHT - viewport.height) // 2
    target.alpha_composite(viewport, (left, top))
    return target


def connected_components(image: Image.Image) -> list[dict[str, object]]:
    """Fast vectorized 4-connected component labeling via scipy.ndimage."""
    alpha = np.asarray(image.getchannel("A"))
    mask = alpha > 16
    labeled, count = ndimage.label(mask)
    if count == 0:
        return []

    slices = ndimage.find_objects(labeled)
    areas = ndimage.sum(mask, labeled, index=range(1, count + 1))
    components: list[dict[str, object]] = []
    for label_idx, (slc, area_val) in enumerate(zip(slices, areas), start=1):
        if slc is None:
            continue
        y_slc, x_slc = slc
        min_y, max_y = int(y_slc.start), int(y_slc.stop)
        min_x, max_x = int(x_slc.start), int(x_slc.stop)
        sub_mask = labeled[y_slc, x_slc] == label_idx
        components.append(
            {
                "label": label_idx,
                "mask": sub_mask,
                "area": int(area_val),
                "bbox": (min_x, min_y, max_x, max_y),
                "center_x": (min_x + max_x) / 2.0,
            }
        )
    return components


def component_group_image(
    source: Image.Image,
    components: list[dict[str, object]],
    padding: int = 4,
) -> Image.Image:
    src_arr = np.asarray(source.convert("RGBA"))
    height, width = src_arr.shape[:2]
    min_x = max(0, min(c["bbox"][0] for c in components) - padding)
    min_y = max(0, min(c["bbox"][1] for c in components) - padding)
    max_x = min(width, max(c["bbox"][2] for c in components) + padding)
    max_y = min(height, max(c["bbox"][3] for c in components) + padding)

    out_arr = np.zeros((max_y - min_y, max_x - min_x, 4), dtype=np.uint8)
    for c in components:
        cx0, cy0, cx1, cy1 = c["bbox"]
        sub_mask = c["mask"]
        dst_y0, dst_y1 = cy0 - min_y, cy1 - min_y
        dst_x0, dst_x1 = cx0 - min_x, cx1 - min_x
        out_arr[dst_y0:dst_y1, dst_x0:dst_x1][sub_mask] = src_arr[cy0:cy1, cx0:cx1][sub_mask]
    return Image.fromarray(out_arr, mode="RGBA")


def component_frame_groups(
    strip: Image.Image,
    frame_count: int,
) -> list[list[dict[str, object]]] | None:
    components = connected_components(strip)
    if not components:
        return None

    largest_area = max(component["area"] for component in components)
    seed_threshold = max(120, largest_area * 0.20)
    seeds = [component for component in components if component["area"] >= seed_threshold]
    if len(seeds) < frame_count:
        seeds = sorted(components, key=lambda component: component["area"], reverse=True)[
            :frame_count
        ]
    if len(seeds) < frame_count:
        return None

    seeds = sorted(
        sorted(seeds, key=lambda component: component["area"], reverse=True)[:frame_count],
        key=lambda component: component["center_x"],
    )
    seed_ids = {id(seed) for seed in seeds}
    groups: list[list[dict[str, object]]] = [[seed] for seed in seeds]
    noise_threshold = max(12, largest_area * 0.002)

    for component in components:
        if id(component) in seed_ids or component["area"] < noise_threshold:
            continue
        nearest_index = min(
            range(len(seeds)),
            key=lambda index: abs(seeds[index]["center_x"] - component["center_x"]),
        )
        groups[nearest_index].append(component)

    return groups


def extract_component_frames(strip: Image.Image, frame_count: int) -> list[Image.Image] | None:
    groups = component_frame_groups(strip, frame_count)
    if groups is None:
        return None
    return fit_registered_component_groups(strip, groups)


def component_bounds(components: list[dict[str, object]]) -> tuple[int, int, int, int]:
    return (
        min(component["bbox"][0] for component in components),
        min(component["bbox"][1] for component in components),
        max(component["bbox"][2] for component in components),
        max(component["bbox"][3] for component in components),
    )


def fit_registered_component_groups(
    strip: Image.Image,
    groups: list[list[dict[str, object]]],
) -> list[Image.Image]:
    """Preserve one row-wide scale and every pose's original vertical displacement."""
    padding = 4
    bboxes = [component_bounds(group) for group in groups]
    shared_top = max(0, min(bbox[1] for bbox in bboxes) - padding)
    shared_bottom = min(strip.height, max(bbox[3] for bbox in bboxes) + padding)
    viewport_width = max(bbox[2] - bbox[0] for bbox in bboxes) + padding * 2
    viewport_height = max(1, shared_bottom - shared_top)
    frames = []

    for group, bbox in zip(groups, bboxes, strict=True):
        grouped = component_group_image(strip, group, padding=padding)
        grouped_top = max(0, bbox[1] - padding)
        viewport = Image.new("RGBA", (viewport_width, viewport_height), (0, 0, 0, 0))
        left = (viewport_width - grouped.width) // 2
        viewport.alpha_composite(grouped, (left, grouped_top - shared_top))
        frames.append(fit_viewport_to_cell(viewport))

    return frames


def extract_slot_frames(strip: Image.Image, frame_count: int) -> list[Image.Image]:
    slot_width = strip.width / frame_count
    frames = []
    for index in range(frame_count):
        left = round(index * slot_width)
        right = round((index + 1) * slot_width)
        crop = strip.crop((left, 0, right, strip.height))
        frames.append(fit_to_cell(crop))
    return frames


def extract_stable_slot_frames(strip: Image.Image, frame_count: int) -> list[Image.Image]:
    groups = component_frame_groups(strip, frame_count)
    if groups is not None:
        return fit_registered_component_groups(strip, groups)

    padding = 4
    bbox = strip.getbbox()
    if bbox is None:
        return [
            Image.new("RGBA", (CELL_WIDTH, CELL_HEIGHT), (0, 0, 0, 0)) for _ in range(frame_count)
        ]

    shared_top = max(0, bbox[1] - padding)
    shared_bottom = min(strip.height, bbox[3] + padding)
    slot_width = strip.width / frame_count
    frames = []
    for index in range(frame_count):
        left = round(index * slot_width)
        right = round((index + 1) * slot_width)
        crop = strip.crop((left, shared_top, right, shared_bottom))
        frames.append(fit_viewport_to_cell(crop))
    return frames


def extract_state(
    strip_path: Path,
    state: str,
    output_root: Path,
    chroma_key: tuple[int, int, int],
    threshold: float,
    method: str,
) -> dict[str, object]:
    frame_count = ROW_FRAME_COUNTS[state]
    with Image.open(strip_path) as opened:
        strip = remove_chroma_background(opened, chroma_key, threshold)

    state_dir = output_root / state
    state_dir.mkdir(parents=True, exist_ok=True)

    frames = None
    used_method = method
    if method in {"auto", "components"}:
        frames = extract_component_frames(strip, frame_count)
        if frames is None and method == "components":
            raise SystemExit(f"could not find {frame_count} sprite components in {strip_path}")
        if frames is not None:
            used_method = "components"

    if frames is None:
        if method == "stable-slots":
            frames = extract_stable_slot_frames(strip, frame_count)
            used_method = "stable-slots"
        else:
            frames = extract_slot_frames(strip, frame_count)
            used_method = "slots"

    outputs = []
    for index, frame in enumerate(frames):
        output = state_dir / f"{index:02d}.png"
        frame.save(output, optimize=True, compress_level=9)
        outputs.append(str(output))
    return {"state": state, "frames": outputs, "method": used_method}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decoded-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--states", default="all")
    parser.add_argument("--chroma-key", help="Override chroma key as #RRGGBB.")
    parser.add_argument("--key-threshold", type=float, default=96.0)
    parser.add_argument(
        "--method",
        choices=("auto", "components", "slots", "stable-slots"),
        default="auto",
        help="Use connected sprite components when possible, raw equal slots, or row-stable slot viewports.",
    )
    args = parser.parse_args()

    decoded_dir = Path(args.decoded_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    chroma_key = load_chroma_key(decoded_dir, args.chroma_key)
    states = parse_states(args.states)
    manifest = []
    for state in states:
        strip_path = decoded_dir / f"{state}.png"
        if not strip_path.is_file():
            raise SystemExit(f"missing generated strip for {state}: {strip_path}")
        manifest.append(
            extract_state(
                strip_path,
                state,
                output_dir,
                chroma_key,
                args.key_threshold,
                args.method,
            )
        )

    (output_dir / "frames-manifest.json").write_text(
        json.dumps(
            {
                "ok": True,
                "chroma_key": {
                    "hex": f"#{chroma_key[0]:02X}{chroma_key[1]:02X}{chroma_key[2]:02X}",
                    "rgb": list(chroma_key),
                    "threshold": args.key_threshold,
                },
                "rows": manifest,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "frames_root": str(output_dir), "states": states}, indent=2))


if __name__ == "__main__":
    main()
