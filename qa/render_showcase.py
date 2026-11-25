#!/usr/bin/env python3
"""Render high-fidelity motion, clip, and poster showcases for a v2 ChatGPT pet atlas.

This is a presentation layer only: it reads the validated atlas and never rewrites it.
Frames are supersampled, motion-inbetweened, and streamed straight into ffmpeg, so the
renderer holds a handful of frames in memory instead of the whole timeline.

Row order, frame counts, and canonical durations are imported from the bundled Pets
scripts so this file cannot drift from the atlas schema.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from scipy import ndimage

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "pipeline" / "skills" / "create-pet" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from make_contact_sheet import CELL_HEIGHT, CELL_WIDTH, ROW_NAMES, USED_COUNTS  # noqa: E402
from render_animation_previews import LOOK_POSE_HOLD_MS, ROW_DURATIONS  # noqa: E402

STATE_ROWS = {name: index for index, name in enumerate(ROW_NAMES)}

# Codex-flavoured framing of each state: (display name, what it means in product).
STATE_COPY = {
    "idle": ("idle", "ready when you are"),
    "running-right": ("running right", "moving out · tool call"),
    "running-left": ("running left", "moving back · undo"),
    "waving": ("waving", "hello, new session"),
    "jumping": ("jumping", "build started"),
    "failed": ("failed", "tests red · recovering"),
    "waiting": ("waiting", "needs your approval"),
    "running": ("working", "thinking through the task"),
    "review": ("review", "reading the diff"),
    "look 000-157.5": ("gaze I", "000 up → 157.5 down-right"),
    "look 180-337.5": ("gaze II", "180 down → 337.5 up-left"),
}

LOOK_LABELS = ["000", "022.5", "045", "067.5", "090", "112.5", "135", "157.5",
               "180", "202.5", "225", "247.5", "270", "292.5", "315", "337.5"]

THEMES = {
    "dark": {
        "top": (14, 20, 44),
        "bottom": (4, 6, 14),
        "fg": (226, 234, 250),
        "muted": (132, 150, 190),
        "glow": (64, 132, 255),
        "glow_alpha": 46,
        "ground_alpha": 78,
        "ground_rgb": (78, 120, 214),
    },
    "light": {
        "top": (252, 253, 255),
        "bottom": (224, 232, 246),
        "fg": (22, 32, 54),
        "muted": (104, 120, 150),
        "glow": (120, 170, 255),
        "glow_alpha": 30,
        "ground_alpha": 92,
        "ground_rgb": (22, 32, 62),
    },
}

FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"


@dataclass(frozen=True)
class Frame:
    """One output frame: a held pose, or an inbetween from pose to next_pose."""

    state: str
    pose: int
    next_pose: int | None = None
    step: int = 0
    steps: int = 0


# --------------------------------------------------------------------------------------
# atlas access


def load_atlas(path: Path) -> Image.Image:
    with Image.open(path) as opened:
        atlas = opened.convert("RGBA")
    if atlas.width != CELL_WIDTH * 8 or atlas.height % CELL_HEIGHT:
        raise SystemExit(f"unexpected atlas geometry {atlas.width}x{atlas.height}")
    return atlas


def row_cells(atlas: Image.Image, state: str) -> list[Image.Image]:
    index = STATE_ROWS[state]
    count = USED_COUNTS[index]
    return [
        atlas.crop(
            (
                column * CELL_WIDTH,
                index * CELL_HEIGHT,
                (column + 1) * CELL_WIDTH,
                (index + 1) * CELL_HEIGHT,
            )
        )
        for column in range(count)
    ]


def alpha_bbox_bottom(cell: Image.Image) -> int:
    box = cell.getchannel("A").point(lambda value: 255 if value > 16 else 0).getbbox()
    return box[3] if box else CELL_HEIGHT


def alpha_centroid(cell: Image.Image) -> tuple[float, float]:
    alpha = np.asarray(cell.getchannel("A"), dtype=np.float64)
    total = alpha.sum()
    if total <= 0:
        return (cell.width / 2, cell.height / 2)
    column_mass = alpha.sum(axis=0)
    row_mass = alpha.sum(axis=1)
    return (
        float((column_mass * np.arange(alpha.shape[1])).sum() / total),
        float((row_mass * np.arange(alpha.shape[0])).sum() / total),
    )


# --------------------------------------------------------------------------------------
# image helpers


def upscale(cell: Image.Image, scale: int) -> Image.Image:
    big = cell.resize((cell.width * scale, cell.height * scale), Image.Resampling.LANCZOS)
    # Recover the crisp plastic highlight edges the source art has at pet size.
    return big.filter(ImageFilter.UnsharpMask(radius=1.1 * scale / 2, percent=52, threshold=2))


CHROMA_KEY = (255, 0, 255)
HARD_CUT_SIMILARITY = 0.993
HARD_CUT_TRAVEL = 1.5
FRINGE_KEY_LIMIT = 110.0
FRINGE_DIP_LIMIT = 20.0
FRINGE_EDGE_WIDTH = 3
FRINGE_REPAIR_RADIUS = 3


def repair_chroma_fringe(cell: Image.Image) -> tuple[Image.Image, int]:
    """Soften magenta contamination that survives the atlas despill pass.

    Two detectors are unioned: near-key colour (bright magenta specks) and a local
    green dip (magenta mixed into the dark rim, which is no longer near the key but
    still reads pink once supersampled). Each hit is replaced with the mean of its
    clean neighbourhood so the rim gradient stays continuous. Alpha is never touched.
    """
    arr = np.array(cell, dtype=np.uint8)
    if arr.shape[2] != 4:
        return cell, 0
    rgb = arr[:, :, :3].astype(np.float64)
    alpha = arr[:, :, 3]
    key = np.array(CHROMA_KEY, dtype=np.float64)
    near_key = np.sqrt(((rgb - key) ** 2).sum(axis=2)) < FRINGE_KEY_LIMIT

    medians = [
        ndimage.median_filter(rgb[:, :, channel], size=5, mode="nearest")
        for channel in range(3)
    ]
    green_dip = (
        (medians[1] - rgb[:, :, 1] > FRINGE_DIP_LIMIT)
        & (rgb[:, :, 0] - medians[0] > 8)
        & (rgb[:, :, 2] - medians[2] > 8)
    )
    visible = alpha > 0
    silhouette = np.pad(ndimage.binary_fill_holes(visible), 1)
    distance = ndimage.distance_transform_edt(silhouette)[1:-1, 1:-1]
    candidates = visible & (distance <= FRINGE_EDGE_WIDTH) & (near_key | green_dip)
    if not candidates.any():
        return cell, 0
    clean = visible & ~(near_key | green_dip)
    if not clean.any():
        return cell, 0

    window = 2 * FRINGE_REPAIR_RADIUS + 1
    weights = ndimage.uniform_filter(clean.astype(np.float64), size=window)
    local = np.empty_like(rgb)
    for channel in range(3):
        local[:, :, channel] = ndimage.uniform_filter(
            np.where(clean, rgb[:, :, channel], 0.0), size=window
        )
    local /= np.maximum(weights, 1e-6)[:, :, None]

    ys, xs = np.nonzero(candidates)
    usable = weights[ys, xs] > 1e-6
    arr[ys[usable], xs[usable], :3] = np.rint(
        np.clip(local[ys[usable], xs[usable], :], 0, 255)
    ).astype(np.uint8)
    return Image.fromarray(arr, "RGBA"), int(usable.sum())


def shift(image: Image.Image, dx: float, dy: float) -> Image.Image:
    if abs(dx) < 0.02 and abs(dy) < 0.02:
        return image
    return image.transform(
        image.size,
        Image.Transform.AFFINE,
        (1.0, 0.0, -dx, 0.0, 1.0, -dy),
        resample=Image.Resampling.BICUBIC,
    )


def set_opacity(image: Image.Image, opacity: float) -> Image.Image:
    if opacity >= 0.998:
        return image
    alpha = image.getchannel("A").point(lambda value: int(round(value * opacity)))
    result = image.copy()
    result.putalpha(alpha)
    return result


def silhouette_similarity(first: Image.Image, second: Image.Image) -> float:
    a = np.asarray(first.getchannel("A")) > 16
    b = np.asarray(second.getchannel("A")) > 16
    union = np.logical_or(a, b).sum()
    if union == 0:
        return 1.0
    return float(np.logical_and(a, b).sum() / union)


def smoothstep(value: float) -> float:
    return value * value * (3.0 - 2.0 * value)


def stack(layers: list[Image.Image]) -> Image.Image:
    canvas = Image.new("RGBA", layers[0].size, (0, 0, 0, 0))
    for layer in layers:
        canvas.alpha_composite(layer)
    return canvas


def inbetween(first: Image.Image, second: Image.Image, step: int, steps: int) -> Image.Image:
    """Motion-compensated blend: park both poses on the same eased centroid, then fade."""
    progress = smoothstep(step / (steps + 1))
    cx_a, cy_a = alpha_centroid(first)
    cx_b, cy_b = alpha_centroid(second)
    target_x = cx_a + (cx_b - cx_a) * progress
    target_y = cy_a + (cy_b - cy_a) * progress
    a = set_opacity(shift(first, target_x - cx_a, target_y - cy_a), 1.0 - progress)
    b = set_opacity(shift(second, target_x - cx_b, target_y - cy_b), progress)
    return stack([a, b])


def gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]):
    column = Image.new("RGB", (1, size[1]))
    for y in range(size[1]):
        t = y / max(1, size[1] - 1)
        column.putpixel(
            (0, y), tuple(int(round(top[c] + (bottom[c] - top[c]) * t)) for c in range(3))
        )
    return column.resize(size, Image.Resampling.BILINEAR).convert("RGBA")


def radial_glow(
    size: tuple[int, int], center: tuple[float, float], radius: float, colour, alpha: int
) -> Image.Image:
    width, height = size
    ys, xs = np.indices((height, width))
    distance = np.hypot(xs - center[0], ys - center[1]) / max(1.0, radius)
    falloff = np.clip(1.0 - distance, 0.0, 1.0) ** 2.2
    layer = Image.new("RGBA", size, (*colour, 0))
    layer.putalpha(Image.fromarray((falloff * alpha).astype(np.uint8), "L"))
    return layer


def ellipse_shadow(
    size: tuple[int, int],
    center: tuple[float, float],
    radius: tuple[float, float],
    colour: tuple[int, int, int],
    alpha: int,
    blur: float,
) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse(
        (center[0] - radius[0], center[1] - radius[1], center[0] + radius[0], center[1] + radius[1]),
        fill=255,
    )
    mask = mask.filter(ImageFilter.GaussianBlur(blur))
    layer = Image.new("RGBA", size, (*colour, 0))
    layer.putalpha(mask.point(lambda value: int(value * alpha / 255)))
    return layer


_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    key = (path, size)
    cached = _FONT_CACHE.get(key)
    if cached is None:
        try:
            cached = ImageFont.truetype(path, size)
        except OSError:
            cached = ImageFont.load_default(size=size)
        _FONT_CACHE[key] = cached
    return cached


# --------------------------------------------------------------------------------------
# layout


@dataclass(frozen=True)
class Layout:
    scale: int
    width: int
    height: int
    pet_left: int
    pet_top: int
    band: int
    font_title: int
    font_body: int
    font_mono: int

    @property
    def pet_width(self) -> int:
        return CELL_WIDTH * self.scale

    @property
    def pet_height(self) -> int:
        return CELL_HEIGHT * self.scale


def make_layout(scale: int) -> Layout:
    pet_w, pet_h = CELL_WIDTH * scale, CELL_HEIGHT * scale
    margin_x = max(10, round(pet_w * 0.022))
    pet_top = max(10, round(pet_h * 0.030))
    band = max(72, round(pet_h * 0.105))
    width = pet_w + margin_x * 2
    height = pet_top + pet_h + band
    width -= width % 2
    height -= height % 2
    return Layout(
        scale=scale,
        width=width,
        height=height,
        pet_left=(width - pet_w) // 2,
        pet_top=pet_top,
        band=band,
        font_title=max(11, round(band * 0.23)),
        font_body=max(9, round(band * 0.155)),
        font_mono=max(8, round(band * 0.125)),
    )


class SceneRenderer:
    """Caches backgrounds, captions, shadows, and upscaled poses for one theme."""

    def __init__(self, atlas: Image.Image, theme: str, layout: Layout, shadow: bool = True) -> None:
        self.atlas = atlas
        self.theme_name = theme
        self.theme = THEMES[theme]
        self.layout = layout
        self.ground = shadow
        self._background = self._build_background()
        self._caption_cache: dict[str, Image.Image] = {}
        self._pose_cache: dict[tuple[str, int, int], Image.Image] = {}
        self._shadow_cache: dict[tuple[str, int], Image.Image] = {}
        self._native: dict[str, list[Image.Image]] = {}
        self._clean: dict[tuple[str, int], Image.Image] = {}
        self._cut_cache: dict[tuple[str, int, int], bool] = {}
        self.fringe_repaired = 0
        self._centroid: dict[tuple[str, int], tuple[float, float]] = {}
        self._bottom: dict[tuple[str, int], int] = {}
        self.feet_bottom = max(alpha_bbox_bottom(cell) for cell in self.cells("idle"))
        self.idle_centroid = alpha_centroid(self.cells("idle")[0])

    # -- sources
    def cells(self, state: str) -> list[Image.Image]:
        if state not in self._native:
            self._native[state] = row_cells(self.atlas, state)
        return self._native[state]

    def clean(self, state: str, index: int) -> Image.Image:
        key = (state, index)
        cached = self._clean.get(key)
        if cached is None:
            cached, repaired = repair_chroma_fringe(self.cells(state)[index])
            self.fringe_repaired += repaired
            self._clean[key] = cached
        return cached

    def pose(self, state: str, index: int) -> Image.Image:
        key = (state, index, self.layout.scale)
        cached = self._pose_cache.get(key)
        if cached is None:
            if len(self._pose_cache) > 24:
                self._pose_cache.pop(next(iter(self._pose_cache)))
            cached = upscale(self.clean(state, index), self.layout.scale)
            self._pose_cache[key] = cached
        return cached

    def centroid(self, state: str, index: int) -> tuple[float, float]:
        key = (state, index)
        if key not in self._centroid:
            x, y = alpha_centroid(self.cells(state)[index])
            self._centroid[key] = (x * self.layout.scale, y * self.layout.scale)
        return self._centroid[key]

    # -- background
    def _build_background(self) -> Image.Image:
        layout = self.layout
        size = (layout.width, layout.height)
        base = gradient(size, self.theme["top"], self.theme["bottom"])
        glow_center = (
            layout.pet_left + layout.pet_width * 0.5,
            layout.pet_top + layout.pet_height * 0.52,
        )
        base.alpha_composite(
            radial_glow(
                size,
                glow_center,
                layout.pet_width * 0.62,
                self.theme["glow"],
                self.theme["glow_alpha"],
            )
        )
        return base

    # -- captions
    def caption(self, state: str) -> Image.Image:
        if state in self._caption_cache:
            return self._caption_cache[state]
        layout = self.layout
        layer = Image.new("RGBA", (layout.width, layout.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        title, subtitle = STATE_COPY[state]
        x = layout.pet_left
        baseline = layout.pet_top + layout.pet_height + max(4, round(layout.band * 0.14))
        draw.text(
            (x, baseline),
            title,
            font=load_font(FONT_BOLD, max(14, round(layout.band * 0.34))),
            fill=(*self.theme["fg"], 255),
        )
        draw.text(
            (x, baseline + round(layout.band * 0.40)),
            subtitle,
            font=load_font(FONT_REGULAR, max(11, round(layout.band * 0.24))),
            fill=(*self.theme["muted"], 255),
        )
        mono = load_font(FONT_MONO, max(9, round(layout.band * 0.19)))
        draw.text(
            (layout.width - layout.pet_left - 4, layout.pet_top - round(layout.band * 0.05)),
            "NAZAR",
            font=load_font(FONT_BOLD, max(10, round(layout.band * 0.21))),
            fill=(*self.theme["fg"], 210),
            anchor="ra",
        )
        draw.text(
            (layout.width - layout.pet_left - 4, layout.pet_top + round(layout.band * 0.19)),
            "codex pet · v2 atlas",
            font=mono,
            fill=(*self.theme["muted"], 200),
            anchor="ra",
        )
        self._caption_cache[state] = layer
        return layer

    # -- shadow
    def shadow_layer(self, state: str, factor: int) -> Image.Image | None:
        if not self.ground:
            return None
        factor = int(round(factor / 10.0) * 10)
        key = (state, factor)
        if key in self._shadow_cache:
            return self._shadow_cache[key]
        layout = self.layout
        centre = (
            layout.pet_left + self.idle_centroid[0],
            layout.pet_top + self.feet_bottom * layout.scale + layout.scale * 1.5,
        )
        layer = ellipse_shadow(
            (layout.width, layout.height),
            centre,
            (layout.pet_width * 0.30, max(5, layout.pet_height * 0.042)),
            self.theme["ground_rgb"],
            int(self.theme["ground_alpha"] * factor / 100),
            blur=max(2.5, layout.scale * 3.4),
        )
        self._shadow_cache[key] = layer
        return layer

    def hard_cut(self, state: str, first: int, second: int) -> bool:
        """Blending is only plausible when the body silhouette actually travels.

        Blinks, lid settles, and gaze changes keep the silhouette identical, so a
        cross-fade would double-expose the eyelid or the iris. Those transitions stay
        discrete, which is also how the product plays them.
        """
        key = (state, first, second)
        cached = self._cut_cache.get(key)
        if cached is None:
            cells = self.cells(state)
            similarity = silhouette_similarity(cells[first], cells[second])
            travel = float(
                np.hypot(
                    *np.subtract(alpha_centroid(cells[first]), alpha_centroid(cells[second]))
                )
            )
            cached = similarity > HARD_CUT_SIMILARITY and travel < HARD_CUT_TRAVEL
            self._cut_cache[key] = cached
        return cached

    def lift_factor(self, state: str, index: int) -> int:
        key = (state, index)
        if key not in self._bottom:
            self._bottom[key] = alpha_bbox_bottom(self.cells(state)[index])
        lift = max(0, self.feet_bottom - self._bottom[key])
        return int(round(100 * max(0.32, 1.0 - lift / 42.0)))

    # -- frames
    def render(self, frame: Frame) -> Image.Image:
        layout = self.layout
        if frame.next_pose is None:
            pose = self.pose(frame.state, frame.pose)
        elif self.hard_cut(frame.state, frame.pose, frame.next_pose):
            keep_next = frame.step * 2 > frame.steps
            pose = self.pose(frame.state, frame.next_pose if keep_next else frame.pose)
        else:
            pose = inbetween(
                self.pose(frame.state, frame.pose),
                self.pose(frame.state, frame.next_pose),
                frame.step,
                frame.steps,
            )
        canvas = self._background.copy()
        shadow = self.shadow_layer(frame.state, self.lift_factor(frame.state, frame.pose))
        if shadow is not None:
            canvas.alpha_composite(shadow)
        canvas.alpha_composite(pose, (layout.pet_left, layout.pet_top))
        canvas.alpha_composite(self.caption(frame.state))
        return canvas


# --------------------------------------------------------------------------------------
# timeline


def load_timing(path: Path | None) -> dict[str, list[int]]:
    timing = {state: list(values) for state, values in ROW_DURATIONS.items()}
    if path is not None:
        override = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
        for state, values in override.items():
            if state.startswith("_"):
                continue
            if state not in timing:
                raise SystemExit(f"timing override has unknown state: {state}")
            if not isinstance(values, list) or not all(isinstance(v, int) and v > 0 for v in values):
                raise SystemExit(f"timing for {state} must be a list of positive integers")
            if len(values) != len(timing[state]):
                raise SystemExit(
                    f"timing for {state} has {len(values)} entries; the row has {len(timing[state])}"
                )
            timing[state] = values
    return timing


def build_plan(
    states: list[str],
    timing: dict[str, list[int]],
    fps: int,
    smooth: bool,
    inbetweens: int,
    gap_ms: int = 0,
) -> list[Frame]:
    plan: list[Frame] = []
    gap = max(0, round(gap_ms * fps / 1000))
    for state in states:
        durations = timing[state]
        count = len(durations)
        for index in range(count):
            hold = max(1, round(durations[index] * fps / 1000))
            extra = inbetweens if (smooth and count > 1) else 0
            if hold - extra < 1:
                extra = max(0, hold - 1)
            hold -= extra
            plan.extend(Frame(state, index) for _ in range(hold))
            if extra:
                nxt = (index + 1) % count
                plan.extend(Frame(state, index, nxt, step, extra) for step in range(1, extra + 1))
            if gap and index == 0:
                plan.extend(Frame(state, 0) for _ in range(gap))
    return plan


# --------------------------------------------------------------------------------------
# encoders


def find_ffmpeg() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    return imageio_ffmpeg.get_ffmpeg_exe()


def ffmpeg_version(binary: str) -> str:
    try:
        out = subprocess.run(
            [binary, "-version"], capture_output=True, text=True, check=False
        ).stdout
    except OSError:
        return "unknown"
    return out.splitlines()[0] if out else "unknown"


class VideoWriter:
    """Streams RGBA frames into ffmpeg; nothing but one frame is ever buffered."""

    def __init__(
        self,
        binary: str,
        path: Path,
        size: tuple[int, int],
        fps: int,
        *,
        alpha: bool = False,
        crf: int = 16,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        width, height = size
        command = [
            binary, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{width}x{height}",
            "-framerate", str(fps), "-i", "-",
        ]
        if path.suffix == ".webm":
            command += [
                "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p" if alpha else "yuv420p",
                "-crf", str(crf + 12), "-b:v", "0", "-row-mt", "1", "-cpu-used", "2",
                "-auto-alt-ref", "0",
            ]
        else:
            command += [
                "-c:v", "libx264", "-preset", "slow", "-tune", "animation",
                "-crf", str(crf), "-pix_fmt", "yuv420p", "-g", str(fps),
                "-movflags", "+faststart",
            ]
        command.append(str(path))
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE)

    def write(self, frame: Image.Image) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(frame.convert("RGBA").tobytes())

    def close(self) -> None:
        assert self.process.stdin is not None
        self.process.stdin.close()
        code = self.process.wait()
        if code != 0:
            raise SystemExit(f"ffmpeg failed for {self.path} (exit {code})")


def file_record(path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "path": str(path.relative_to(REPO_ROOT)) if REPO_ROOT in path.parents else str(path),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def write_gif_from_video(
    binary: str, source: Path, path: Path, fps: int, width: int
) -> None:
    """Derive the GIF from the encoded master so both show identical motion."""
    path.parent.mkdir(parents=True, exist_ok=True)
    filters = (
        f"fps={fps},scale={width}:-1:flags=lanczos,split[pal][img];"
        "[pal]palettegen=max_colors=224:stats_mode=diff[map];"
        "[img][map]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle"
    )
    command = [
        binary, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-vf", filters, "-loop", "0", str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"ffmpeg GIF encode failed: {result.stderr.strip()}")


def write_webp(
    renderer: SceneRenderer, plan: list[Frame], path: Path, duration_ms: int, *, alpha: bool
) -> None:
    frames = []
    for frame in plan:
        rendered = renderer.render(frame)
        frames.append(rendered if alpha else rendered.convert("RGB"))
    path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=0,
        lossless=True,
        quality=100,
        method=4,
        exact=alpha,
    )


def write_video(
    binary: str, renderer: SceneRenderer, plan: list[Frame], path: Path, fps: int, *, alpha: bool
) -> None:
    writer = VideoWriter(binary, path, (renderer.layout.width, renderer.layout.height), fps, alpha=alpha)
    try:
        for frame in plan:
            writer.write(renderer.render(frame))
    finally:
        writer.close()


# --------------------------------------------------------------------------------------
# stills


def write_poster(atlas: Image.Image, path: Path, scale: int = 3) -> None:
    """Designed one-page sheet: nine state cards above the sixteen-pose gaze strip."""
    states = [name for name in ROW_NAMES if not name.startswith("look")]
    look_states = ["look 000-157.5", "look 180-337.5"]
    renderer = SceneRenderer(atlas, "dark", make_layout(2), shadow=False)

    pose_w, pose_h = CELL_WIDTH * scale, CELL_HEIGHT * scale
    gaze_scale = 2
    gaze_w, gaze_h_cell = CELL_WIDTH * gaze_scale, CELL_HEIGHT * gaze_scale
    gap = round(pose_w * 0.0625)
    columns = 3
    rows = (len(states) + columns - 1) // columns

    card_w = (8 * gaze_w + 9 * gap - (columns + 1) * gap) // columns
    card_h = pose_h + round(pose_h * 0.24)
    header_h = round(pose_h * 0.40)
    gaze_label_h = round(gaze_h_cell * 0.16)

    width = 8 * gaze_w + 9 * gap
    cards_h = rows * (card_h + gap)
    gaze_block = 2 * (gaze_h_cell + gaze_label_h) + round(gap * 4.2)
    height = header_h + cards_h + gaze_block + gap
    width -= width % 2
    height -= height % 2

    body = gradient((width, height), (13, 18, 42), (4, 6, 14))
    draw = ImageDraw.Draw(body)

    title_font = load_font(FONT_BOLD, round(pose_h * 0.185))
    subtitle_font = load_font(FONT_MONO, max(12, round(pose_h * 0.052)))
    draw.text((gap, round(gap * 1.2)), "NAZAR", font=title_font, fill=(236, 241, 253, 255))
    title_box = draw.textbbox((gap, round(gap * 1.2)), "NAZAR", font=title_font)
    draw.text(
        (gap, title_box[3] + round(gap * 0.55)),
        "codex pet · v2 atlas · 8x11 grid · 192x208 cells · 73 used frames",
        font=subtitle_font,
        fill=(126, 148, 190, 255),
    )
    draw.text(
        (width - gap, round(gap * 1.2)),
        "rendered from final/spritesheet-extended.png",
        font=load_font(FONT_MONO, max(11, round(pose_h * 0.044))),
        fill=(92, 110, 148, 255),
        anchor="ra",
    )

    for index, state in enumerate(states):
        column = index % columns
        row = index // columns
        x = gap + column * (card_w + gap)
        y = header_h + row * (card_h + gap)
        draw.rounded_rectangle(
            (x, y, x + card_w, y + card_h),
            radius=round(card_w * 0.045),
            fill=(17, 23, 50, 255),
            outline=(40, 52, 96, 255),
            width=max(1, scale // 2),
        )
        glow = radial_glow(
            (pose_w, pose_h),
            (pose_w / 2, pose_h * 0.5),
            pose_w * 0.58,
            (58, 112, 222),
            30,
        )
        body.alpha_composite(glow, (x + (card_w - pose_w) // 2, y))
        body.alpha_composite(upscale(renderer.cells(state)[0], scale), (x + (card_w - pose_w) // 2, y))

        title, subtitle = STATE_COPY[state]
        text_x = x + round(card_w * 0.055)
        draw.text(
            (text_x, y + pose_h + round(card_h * 0.020)),
            title,
            font=load_font(FONT_BOLD, max(13, round(pose_h * 0.072))),
            fill=(228, 236, 252, 255),
        )
        draw.text(
            (text_x, y + pose_h + round(card_h * 0.085)),
            subtitle,
            font=load_font(FONT_REGULAR, max(11, round(pose_h * 0.050))),
            fill=(128, 148, 188, 255),
        )
        draw.text(
            (x + card_w - round(card_w * 0.045), y + round(card_h * 0.035)),
            f"{len(renderer.cells(state))} frames · row {STATE_ROWS[state]}",
            font=load_font(FONT_MONO, max(10, round(pose_h * 0.044))),
            fill=(118, 138, 178, 255),
            anchor="ra",
        )

    gaze_top = header_h + cards_h + round(gap * 3.0)
    draw.text(
        (gap, gaze_top - round(gaze_label_h * 1.35)),
        "GAZE · 16 directions, clockwise from up · 000 up → 337.5 up-left",
        font=load_font(FONT_BOLD, max(12, round(pose_h * 0.052))),
        fill=(210, 222, 245, 255),
    )
    for row_index, state in enumerate(look_states):
        for column in range(8):
            x = gap + column * (gaze_w + gap)
            y = gaze_top + row_index * (gaze_h_cell + gaze_label_h)
            body.alpha_composite(
                radial_glow((gaze_w, gaze_h_cell), (gaze_w / 2, gaze_h_cell / 2), gaze_w * 0.55,
                            (58, 110, 220), 26),
                (x, y),
            )
            body.alpha_composite(upscale(renderer.cells(state)[column], gaze_scale), (x, y))
            draw.text(
                (x + gaze_w // 2, y + gaze_h_cell + round(gaze_label_h * 0.10)),
                LOOK_LABELS[row_index * 8 + column],
                font=load_font(FONT_MONO, max(10, round(gaze_w * 0.10))),
                fill=(142, 164, 202, 255),
                anchor="ma",
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    body.convert("RGB").save(path, optimize=True, compress_level=9)


# --------------------------------------------------------------------------------------
# main


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("atlas", nargs="?", default=str(REPO_ROOT / "final/spritesheet-extended.png"))
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "showcase")
    parser.add_argument("--scale", type=int, default=4, help="Supersampling factor for video.")
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--gif-fps", type=int, default=20)
    parser.add_argument("--gif-width", type=int, default=384)
    parser.add_argument(
        "--smooth", choices=("none", "motion"), default="motion",
        help="Insert eased inbetweens so pose changes read as motion, not flipbook.",
    )
    parser.add_argument("--inbetweens", type=int, default=2)
    parser.add_argument("--gap-ms", type=int, default=260, help="Hold between states in the master cut.")
    parser.add_argument("--theme", choices=("dark", "light"), default="dark")
    parser.add_argument("--timing", type=Path, default=None, help="JSON timing override.")
    parser.add_argument("--no-shadow", action="store_true", help="Presentation shadow off.")
    parser.add_argument("--no-webp", action="store_true")
    parser.add_argument("--no-gif", action="store_true")
    parser.add_argument("--no-authentic", action="store_true")
    parser.add_argument("--only", choices=("all", "master", "states", "poster"), default="all")
    args = parser.parse_args()

    atlas_path = Path(args.atlas).expanduser().resolve()
    atlas = load_atlas(atlas_path)
    timing = load_timing(args.timing)
    output = args.output_dir.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)

    binary = find_ffmpeg()
    if binary is None and args.only != "poster":
        raise SystemExit("ffmpeg not found; install imageio-ffmpeg or ffmpeg, or use --only poster")

    artifacts: list[dict[str, object]] = []
    layout = make_layout(args.scale)
    renderer = SceneRenderer(atlas, args.theme, layout, shadow=not args.no_shadow)

    states = [state for state in ROW_NAMES if not state.startswith("look")]

    if args.only in {"all", "master"}:
        master_plan = build_plan(
            states, timing, args.fps, args.smooth == "motion", args.inbetweens, args.gap_ms
        )
        master = output / f"Nazar-codex-motion-{args.theme}-{args.scale}x.mp4"
        write_video(binary, renderer, master_plan, master, args.fps, alpha=False)
        artifacts.append(file_record(master))

        if args.smooth == "motion" and not args.no_authentic:
            authentic = SceneRenderer(atlas, args.theme, layout, shadow=not args.no_shadow)
            plain_plan = build_plan(states, timing, args.fps, False, 0, args.gap_ms)
            plain = output / f"Nazar-codex-motion-{args.theme}-authentic.mp4"
            write_video(binary, authentic, plain_plan, plain, args.fps, alpha=False)
            artifacts.append(file_record(plain))

        if not args.no_gif:
            gif_path = output / f"Nazar-codex-motion-{args.theme}.gif"
            write_gif_from_video(binary, master, gif_path, args.gif_fps, args.gif_width)
            artifacts.append(file_record(gif_path))

    if args.only in {"all", "states"}:
        state_dir = output / "states"
        for state in states:
            plan = build_plan([state], timing, args.fps, args.smooth == "motion", args.inbetweens)
            path = state_dir / f"{state.replace(' ', '-')}.mp4"
            write_video(binary, renderer, plan, path, args.fps, alpha=False)
            artifacts.append(file_record(path))

        look_poses = [
            Frame(state, index)
            for state, count in zip(ROW_NAMES, USED_COUNTS, strict=True)
            if state.startswith("look")
            for index in range(count)
        ]
        # Round each cumulative boundary so 60 fps quantization does not drift.
        frames_per_pose = LOOK_POSE_HOLD_MS * args.fps / 1000
        look_plan = [
            pose
            for index, pose in enumerate(look_poses)
            for _ in range(max(1, round((index + 1) * frames_per_pose) - round(index * frames_per_pose)))
        ]
        gaze = output / "states" / "gaze-16.mp4"
        write_video(binary, renderer, look_plan, gaze, args.fps, alpha=False)
        artifacts.append(file_record(gaze))

        if not args.no_webp:
            alpha_layout = make_layout(2)
            alpha_renderer = SceneRenderer(atlas, args.theme, alpha_layout, shadow=False)
            webp = output / "states" / "gaze-16-alpha.webp"
            write_webp(alpha_renderer, look_poses, webp, LOOK_POSE_HOLD_MS, alpha=True)
            artifacts.append(file_record(webp))

            # Idle → jump → idle, the transition users actually watch.
            jump_plan = (
                [Frame("idle", 0) for _ in range(round(0.3 * args.fps))]
                + build_plan(["jumping"], timing, args.fps, args.smooth == "motion", args.inbetweens)
                + [Frame("idle", 5) for _ in range(round(0.35 * args.fps))]
            )
            jump = output / "states" / "idle-jump-idle.mp4"
            write_video(binary, renderer, jump_plan, jump, args.fps, alpha=False)
            artifacts.append(file_record(jump))

        # Idle timing A/B: canonical cadence beside the calmer proposal.
        proposal = REPO_ROOT / "qa" / "state-timing-proposal.json"
        if proposal.is_file():
            proposed = load_timing(proposal)
            for label, table in (("canonical", timing), ("proposed", proposed)):
                if table is timing and args.timing is not None:
                    continue
                plan = build_plan(["idle"], table, args.gif_fps, True, 1)
                path = output / "states" / f"idle-timing-{label}.mp4"
                write_video(binary, renderer, plan, path, args.gif_fps, alpha=False)
                artifacts.append(file_record(path))

    if args.only in {"all", "poster"}:
        poster = output / "Nazar-codex-poster.png"
        write_poster(atlas, poster, scale=3)
        artifacts.append(file_record(poster))

    manifest_path = output / "showcase-manifest.json"
    fresh = {record["path"] for record in artifacts}
    previous: dict[str, object] = {}
    if manifest_path.is_file():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}
    kept = [
        record
        for record in previous.get("artifacts", [])
        if isinstance(record, dict)
        and isinstance(record.get("path"), str)
        and record["path"] not in fresh
        and (REPO_ROOT / record["path"]).is_file()
        and previous.get("atlas_sha256") == hashlib.sha256(atlas_path.read_bytes()).hexdigest()
    ]
    artifacts = sorted([*kept, *artifacts], key=lambda record: str(record.get("path")))
    runs = [run for run in previous.get("runs", []) if isinstance(run, dict)]

    manifest = {
        "ok": True,
        "generator": "qa/render_showcase.py",
        "atlas": str(atlas_path.relative_to(REPO_ROOT)) if REPO_ROOT in atlas_path.parents else str(atlas_path),
        "atlas_sha256": hashlib.sha256(atlas_path.read_bytes()).hexdigest(),
        "theme": args.theme,
        "scale": args.scale,
        "fps": args.fps,
        "smooth": args.smooth,
        "inbetweens": args.inbetweens,
        "timing": timing,
        "shadow": not args.no_shadow,
        "fringe_repaired_pixels": renderer.fringe_repaired,
        "environment": {
            "python": platform.python_version(),
            "pillow": Image.__version__,
            "numpy": np.__version__,
            "ffmpeg": ffmpeg_version(binary) if binary else None,
        },
        "artifacts": artifacts,
        "runs": [
            *runs,
            {
                "theme": args.theme,
                "scale": args.scale,
                "fps": args.fps,
                "only": args.only,
                "fringe_repaired_pixels": renderer.fringe_repaired,
            },
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "artifacts": artifacts, "manifest": str(manifest_path)}, indent=2))


if __name__ == "__main__":
    main()
