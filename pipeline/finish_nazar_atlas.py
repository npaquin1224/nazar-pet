"""Clean Nazar's rim and ease the final gaze pose on its registered atlas."""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt


CELL_WIDTH = 192
CELL_HEIGHT = 208
EDGE_WIDTH = 2
MAGENTA_KEY = np.array([1.0, 0.0, 1.0])


def clean_cell(cell):
    """Unmix only edge colors consistent with local foreground and magenta."""
    alpha = cell[..., 3]
    distance = distance_transform_edt(alpha > 0)
    edge = (distance > 0) & (distance <= EDGE_WIDTH)
    foreground = (distance > EDGE_WIDTH) & (alpha == 255)
    if not edge.any() or not foreground.any():
        return 0

    nearest = distance_transform_edt(~foreground, return_distances=False, return_indices=True)
    yy, xx = np.where(edge)
    reference = cell[nearest[0, yy, xx], nearest[1, yy, xx], :3] / 255.0
    observed = cell[yy, xx, :3] / 255.0
    key_delta = MAGENTA_KEY - reference
    difference = observed - reference
    length_squared = np.sum(key_delta * key_delta, axis=1)
    fraction = np.sum(difference * key_delta, axis=1) / np.maximum(length_squared, 1e-9)
    residual = np.linalg.norm(difference - fraction[:, None] * key_delta, axis=1)
    contaminated = (
        (fraction >= 0.12)
        & (residual <= 0.08)
        & (observed[:, 0] > reference[:, 0] + 0.06)
        & (observed[:, 2] >= reference[:, 2] - 0.02)
    )
    # Preserve a little of the observed color and clamp ill-conditioned mixtures.
    removal = np.minimum(fraction[contaminated] * 0.85, 0.75)[:, None]
    unmixed = (observed[contaminated] - removal * MAGENTA_KEY) / (1 - removal)
    cell[yy[contaminated], xx[contaminated], :3] = np.rint(np.clip(unmixed, 0, 1) * 255)
    return int(contaminated.sum())


def adjust_wrap_eye(cell):
    """Move the existing 337.5-degree iris towards 0 within the fixed aperture."""
    # Row, left and right aperture limits, and horizontal iris travel in pixels.
    guides = (
        (65, 83, 111, 0),
        (70, 63, 122, 9),
        (77, 54, 135, 9),
        (89, 48, 143, 9),
        (105, 45, 145, 9),
        (120, 46, 143, 9),
        (135, 53, 137, 9),
        (146, 62, 130, 4),
        (153, 78, 116, 0),
    )
    rows, left_edges, right_edges, shifts = np.array(guides).T
    x = np.arange(CELL_WIDTH)
    changed = 0
    for y in range(rows[0] + 1, rows[-1]):
        left = np.interp(y, rows, left_edges)
        right = np.interp(y, rows, right_edges)
        shift = np.interp(y, rows, shifts)
        iris_left = left + 5
        iris_right = min(121, right - 16)
        inside = (x > left) & (x < right)
        sample_x = np.interp(
            x[inside],
            [left, iris_left + shift, iris_right + shift, right],
            [left, iris_left, iris_right, right],
        )
        original = cell[y, inside, :3].copy()
        for channel in range(3):
            cell[y, inside, channel] = np.rint(np.interp(sample_x, x, cell[y, :, channel]))
        changed += int(np.any(original != cell[y, inside, :3], axis=1).sum())
    return changed


def adjust_waiting_eye(cell, lift):
    """Lift the concentric eye within the existing waiting pose's aperture."""
    guides = (
        (52, 92, 124), (58, 84, 133), (64, 77, 141), (71, 72, 147),
        (79, 68, 151), (89, 66, 153), (99, 65, 153), (110, 67, 152),
        (120, 72, 146), (130, 78, 136), (137, 88, 127), (142, 99, 114),
    )
    columns, tops, bottoms = np.array(guides).T
    y = np.arange(CELL_HEIGHT)
    changed = 0
    for x in range(columns[0] + 1, columns[-1]):
        top = np.interp(x, columns, tops)
        bottom = np.interp(x, columns, bottoms)
        taper = min((x - columns[0]) / 15, (columns[-1] - x) / 15, 1)
        shift = lift * taper * taper * (3 - 2 * taper)
        upper = top + (bottom - top) * 0.30
        lower = top + (bottom - top) * 0.91
        inside = (y > top) & (y < bottom)
        if not np.all(cell[inside, x, 3] == 255):
            raise ValueError("Waiting aperture no longer fits the registered eye")
        sample_y = np.interp(
            y[inside],
            [top, upper - shift, lower - shift, bottom],
            [top, upper, lower, bottom],
        )
        original = cell[inside, x, :3].copy()
        for channel in range(3):
            cell[inside, x, channel] = np.rint(np.interp(sample_y, y, cell[:, x, channel]))
        changed += int(np.any(original != cell[inside, x, :3], axis=1).sum())
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    with Image.open(args.input) as source:
        atlas = np.array(source.convert("RGBA"))
    height, width = atlas.shape[:2]
    if width != CELL_WIDTH * 8 or height != CELL_HEIGHT * 11:
        parser.error("expected a v2 Nazar atlas")

    changed_by_cell = {}
    for top in range(0, height, CELL_HEIGHT):
        for left in range(0, width, CELL_WIDTH):
            count = clean_cell(atlas[top:top + CELL_HEIGHT, left:left + CELL_WIDTH])
            if count:
                changed_by_cell[f"r{top // CELL_HEIGHT}c{left // CELL_WIDTH}"] = count

    wrap_cell = atlas[10 * CELL_HEIGHT:11 * CELL_HEIGHT, 7 * CELL_WIDTH:8 * CELL_WIDTH]
    gaze_pixels = adjust_wrap_eye(wrap_cell)
    waiting_lifts = (0, 8, 17, 17, 8, 0)
    waiting_pixels = {}
    for column, lift in enumerate(waiting_lifts):
        if lift:
            cell = atlas[6 * CELL_HEIGHT:7 * CELL_HEIGHT, column * CELL_WIDTH:(column + 1) * CELL_WIDTH]
            waiting_pixels[str(column)] = adjust_waiting_eye(cell, lift)
    Image.fromarray(atlas).save(args.output, optimize=True)
    report = {
        "ok": True,
        "edge_width": EDGE_WIDTH,
        "alpha_preserved": True,
        "changed_pixels": sum(changed_by_cell.values()),
        "changed_by_cell": changed_by_cell,
        "gaze": {"direction": "337.5", "changed_pixels": gaze_pixels},
        "waiting": {"iris_lift_pixels": waiting_lifts, "changed_by_frame": waiting_pixels},
    }
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
