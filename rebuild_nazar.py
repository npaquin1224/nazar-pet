#!/usr/bin/env python3
"""Build and review a Nazar sprite sheet in a fresh output directory."""

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image


def optimize_png(path):
    try:
        import oxipng
    except ImportError as exc:
        raise SystemExit("Install pyoxipng to use --optimize-png.") from exc
    with Image.open(path) as original:
        pixels = original.convert("RGBA").tobytes()
    oxipng.optimize(str(path), level=2, fix_errors=False, optimize_alpha=False,
                    strip=oxipng.StripChunks.safe())
    with Image.open(path) as optimized:
        if optimized.convert("RGBA").tobytes() != pixels:
            raise SystemExit("PNG optimization changed the sprite pixels.")


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--direction-semantics", type=Path, default=root / "qa/direction-semantics.json")
    parser.add_argument("--optimize-png", action="store_true", help="Use optional pyoxipng lossless encoding.")
    args = parser.parse_args()

    out = args.output_dir.resolve()
    try:
        out.mkdir(parents=True)
    except FileExistsError as exc:
        raise SystemExit(f"Choose a fresh output directory: {out}") from exc

    pipeline = root / "pipeline"
    tools = pipeline / "skills/create-pet/scripts"
    decoded = root / "decoded"
    frames = out / "frames"
    standard = out / "standard-atlas.png"
    raw = out / "atlas-before-despill.png"
    atlas = out / "spritesheet-extended.png"
    row9 = out / "look-row-9-registered.png"
    registration = out / "look-row-9-registration.json"

    def run(script, *options, report=None):
        path = script if isinstance(script, Path) else tools / script
        command = [sys.executable, path, *options]
        print(f"Running {path.name}", flush=True)
        if report is None:
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
        else:
            with report.open("w", encoding="utf-8") as stream:
                subprocess.run(command, check=True, stdout=stream)

    run("extract_strip_frames.py", "--decoded-dir", decoded, "--output-dir", frames,
        "--method", "auto", report=out / "extraction.json")
    run(pipeline / "register_standard_frames.py", frames, "--decoded-dir", decoded,
        "--report-out", out / "baseline-registration.txt")
    run("inspect_frames.py", "--frames-root", frames, "--json-out", out / "frame-review.json",
        "--require-components")
    run("compose_atlas.py", "--frames-root", frames, "--output", standard)
    run("assemble_extended_atlas.py", "--base-atlas", standard, "--look-row-9", decoded / "look-row-9.png",
        "--registered-row-output", row9, "--registration-manifest-output", registration, "--chroma-key", "#FF00FF")
    run("assemble_extended_atlas.py", "--base-atlas", standard, "--registered-row-9", row9,
        "--row-9-registration", registration, "--look-row-10", decoded / "look-row-10.png",
        "--output", raw, "--manifest-output", out / "atlas-registration.json", "--chroma-key", "#FF00FF")
    run("despill_chroma_edges.py", raw, "--output", atlas, "--json-out", out / "despill.json",
        "--chroma-key", "#FF00FF", "--edge-radius", "3", "--spill-tolerance", "0.20")
    if args.optimize_png:
        optimize_png(atlas)
    run("validate_atlas.py", atlas, "--require-v2", "--chroma-key", "#FF00FF",
        "--json-out", out / "atlas-validation.json")
    run("make_contact_sheet.py", atlas, "--output", out / "Nazar-contact-sheet.png", "--scale", "0.65")
    run("make_direction_qa_sheet.py", atlas, "--output", out / "Nazar-direction-sheet.png")
    run("measure_direction_continuity.py", atlas, "--json-out", out / "look-continuity.json")
    run(root / "qa/render-final-preview.py", tools, out)
    run("render_animation_previews.py", "--frames-root", out / "qa/encoded-frames",
        "--output-dir", out / "previews/states")
    run("validate_pet_quality.py", atlas, "--atlas-validation", out / "atlas-validation.json",
        "--chroma-report", out / "despill.json", "--frame-review", out / "frame-review.json",
        "--direction-semantics", args.direction_semantics, "--require-reviewed-look",
        "--continuity", out / "look-continuity.json", "--json-out", out / "validation-extended.json")
    print(f"{hashlib.sha256(atlas.read_bytes()).hexdigest()}  {os.fspath(atlas)}")


if __name__ == "__main__":
    main()
