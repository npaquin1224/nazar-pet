#!/usr/bin/env python3
"""Remove chroma-key matte contamination from transparent sprite edges (vectorized linear-light)."""

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
ALGORITHM = "edge-local-chroma-spill-suppression-vectorized"


def parse_hex_color(value: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise SystemExit(f"invalid chroma key color: {value}; expected #RRGGBB")
    return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))


def srgb_to_linear_arr(arr: np.ndarray) -> np.ndarray:
    return np.where(arr <= 0.04045, arr / 12.92, ((arr + 0.055) / 1.055) ** 2.4)


def linear_to_srgb_arr(arr: np.ndarray) -> np.ndarray:
    arr = np.clip(arr, 0.0, 1.0)
    return np.where(arr <= 0.0031308, arr * 12.92, 1.055 * (arr ** (1.0 / 2.4)) - 0.055)


def atlas_edge_band_mask(alpha: np.ndarray, radius: int) -> np.ndarray:
    height, width = alpha.shape
    visible = alpha > 0
    struct = np.ones((radius * 2 + 1, radius * 2 + 1), dtype=bool)
    if width % CELL_WIDTH or height % CELL_HEIGHT:
        expanded = ndimage.binary_dilation(~visible, structure=struct)
        return visible & expanded

    boundary = np.zeros_like(visible)
    for top in range(0, height, CELL_HEIGHT):
        for left in range(0, width, CELL_WIDTH):
            cell_vis = visible[top : top + CELL_HEIGHT, left : left + CELL_WIDTH]
            if np.any(cell_vis):
                expanded = ndimage.binary_dilation(~cell_vis, structure=struct)
                boundary[top : top + CELL_HEIGHT, left : left + CELL_WIDTH] = cell_vis & expanded
    return boundary


def decontaminate_image(
    image: Image.Image,
    *,
    chroma_key: tuple[int, int, int],
    strength: float = 1.0,
    edge_radius: int = 5,
    spill_tolerance: float = 0.15,
    minimum_saturation: float = 0.1,
) -> tuple[Image.Image, dict[str, object]]:
    if not 0 <= strength <= 1:
        raise ValueError("strength must be between 0 and 1")
    if edge_radius < 1:
        raise ValueError("edge_radius must be at least 1")
    if spill_tolerance < 0:
        raise ValueError("spill_tolerance must not be negative")
    if minimum_saturation < 0:
        raise ValueError("minimum_saturation must not be negative")

    rgba = np.asarray(image.convert("RGBA")).copy()
    height, width = rgba.shape[:2]
    alpha = rgba[:, :, 3]
    boundary = atlas_edge_band_mask(alpha, edge_radius)

    rgb_norm = rgba[:, :, :3].astype(np.float32) / 255.0
    colors_linear = srgb_to_linear_arr(rgb_norm)
    key_linear = srgb_to_linear_arr(np.array(chroma_key, dtype=np.float32) / 255.0)

    c_max = colors_linear.max(axis=2)
    c_min = colors_linear.min(axis=2)
    sat = np.where(c_max > 0.0, (c_max - c_min) / np.maximum(c_max, 1e-12), 0.0)

    c_mean = colors_linear.mean(axis=2, keepdims=True)
    c_chroma = colors_linear - c_mean
    k_chroma = key_linear - key_linear.mean()
    denom = np.sqrt(np.sum(c_chroma ** 2, axis=2) * np.sum(k_chroma ** 2))
    sim = np.where(denom > 1e-12, np.sum(c_chroma * k_chroma, axis=2) / np.maximum(denom, 1e-12), -1.0)

    similarity_threshold = 1.0 - min(spill_tolerance, 1.0)
    pending = (alpha > 0) & boundary & (
        (alpha < 250) | ((sat >= minimum_saturation) & (sim >= similarity_threshold))
    )
    filled = (alpha > 0) & (~pending)
    out_linear = colors_linear.copy()

    # Cell-isolated 3x3 neighbor averaging prevents bleed across cell boundaries
    cell_w = CELL_WIDTH if width % CELL_WIDTH == 0 else width
    cell_h = CELL_HEIGHT if height % CELL_HEIGHT == 0 else height
    kernel = np.ones((3, 3), dtype=np.float32)
    kernel[1, 1] = 0.0

    for _ in range(edge_radius * 2 + 1):
        if not np.any(pending):
            break
        updated_any = False
        new_filled = filled.copy()
        new_pending = pending.copy()
        for top in range(0, height, cell_h):
            for left in range(0, width, cell_w):
                p_slice = pending[top : top + cell_h, left : left + cell_w]
                if not np.any(p_slice):
                    continue
                f_slice = filled[top : top + cell_h, left : left + cell_w]
                if not np.any(f_slice):
                    continue
                c_slice = out_linear[top : top + cell_h, left : left + cell_w]
                weight = ndimage.convolve(f_slice.astype(np.float32), kernel, mode="constant", cval=0.0)
                can_update = p_slice & (weight > 0)
                if not np.any(can_update):
                    continue
                updated_any = True
                ref = np.zeros_like(c_slice)
                for ch in range(3):
                    weighted_sum = ndimage.convolve(
                        c_slice[:, :, ch] * f_slice, kernel, mode="constant", cval=0.0
                    )
                    ref[:, :, ch] = np.where(can_update, weighted_sum / np.maximum(weight, 1e-6), c_slice[:, :, ch])
                c_slice[can_update] = c_slice[can_update] + (ref[can_update] - c_slice[can_update]) * strength
                new_filled[top : top + cell_h, left : left + cell_w][can_update] = True
                new_pending[top : top + cell_h, left : left + cell_w][can_update] = False
        filled = new_filled
        pending = new_pending
        if not updated_any:
            break

    if np.any(pending):
        lum = out_linear[pending].mean(axis=1, keepdims=True)
        out_linear[pending] = out_linear[pending] + (lum - out_linear[pending]) * strength

    out_srgb = np.rint(linear_to_srgb_arr(out_linear) * 255.0).astype(np.uint8)
    out_rgba = rgba.copy()
    out_rgba[:, :, :3] = out_srgb
    out_rgba[alpha == 0] = 0

    changed_mask = np.any(out_rgba != rgba, axis=2)
    decontaminated_pixels = int(np.sum(changed_mask & (alpha < 255)))
    spill_suppressed_pixels = int(np.sum(changed_mask))

    changed_by_cell: dict[str, int] = {}
    ys, xs = np.where(changed_mask)
    for r_idx, c_idx in zip(ys // CELL_HEIGHT, xs // CELL_WIDTH):
        key_name = f"r{int(r_idx)}c{int(c_idx)}"
        changed_by_cell[key_name] = changed_by_cell.get(key_name, 0) + 1

    output = Image.fromarray(out_rgba, mode="RGBA")
    return output, {
        "algorithm": ALGORITHM,
        "strength": strength,
        "edge_radius": edge_radius,
        "spill_tolerance": spill_tolerance,
        "minimum_saturation": minimum_saturation,
        "changed_pixels": spill_suppressed_pixels,
        "decontaminated_pixels": decontaminated_pixels,
        "spill_suppressed_pixels": spill_suppressed_pixels,
        "rejected_pixels": 0,
        "changed_by_cell": dict(
            sorted(changed_by_cell.items(), key=lambda item: item[1], reverse=True)
        ),
        "alpha_preserved": True,
    }


def save_image(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".webp":
        image.save(path, format="WEBP", lossless=True, quality=100, method=6, exact=True)
    else:
        image.save(path, optimize=True, compress_level=9)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input")
    parser.add_argument("--output", required=True)
    parser.add_argument("--webp-output")
    parser.add_argument("--json-out")
    parser.add_argument("--chroma-key", required=True)
    parser.add_argument("--strength", type=float, default=1)
    parser.add_argument("--edge-radius", type=int, default=5)
    parser.add_argument("--spill-tolerance", type=float, default=0.15)
    parser.add_argument("--minimum-saturation", type=float, default=0.1)
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    with Image.open(input_path) as opened:
        cleaned, report = decontaminate_image(
            opened,
            chroma_key=parse_hex_color(args.chroma_key),
            strength=args.strength,
            edge_radius=args.edge_radius,
            spill_tolerance=args.spill_tolerance,
            minimum_saturation=args.minimum_saturation,
        )

    output_path = Path(args.output).expanduser().resolve()
    save_image(cleaned, output_path)
    if args.webp_output:
        save_image(cleaned, Path(args.webp_output).expanduser().resolve())

    result = {
        "ok": True,
        "input": str(input_path),
        "output": str(output_path),
        "chroma_key": args.chroma_key.upper(),
        **report,
    }
    if args.json_out:
        json_path = Path(args.json_out).expanduser().resolve()
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
