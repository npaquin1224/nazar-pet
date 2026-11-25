# Nazar

![Nazar animation preview](previews/Nazar-motion.gif)

Nazar is an installed custom ChatGPT pet. Its visible behavior comes from an animated PNG sprite sheet. This kit contains the actual art, individual frames, prompts, layout guides, previews, validation reports, and Python and PowerShell tooling used to build and check that sheet.

| Location | Contents |
|---|---|
| final/spritesheet-extended.png | Rebuilt sprite sheet for review and installation |
| decoded/ | Editable ImageGen source strips and canonical artwork |
| frames/ | Registered standard animation frames |
| prompts/ and references/ | Generation prompts, canonical and layout references |
| previews/ | Full motion, individual states, jump transition, and gaze loop |
| qa/ | Visual notes, current validation reports, and preview tooling |
| pipeline/ | Bundled Pets scripts and contracts plus Nazar’s baseline registration helper |

## Quickest way to update it in ChatGPT

Attach this kit or point Codex at its extracted folder, then use the Pets plugin with a prompt like this.

> Use the Pets update-pet skill to update my existing custom pet Nazar. Use my Nazar update kit as the source. I want [describe the changes]. Preserve the existing pet ID. For artwork changes, show me the revised motion and validate the exact sprite sheet before applying the update.

For a name or description change, give the new wording. The Pets update tool can change that metadata directly. To revise the art, the workflow first fetches the current stored sprite sheet, which may contain updates made after this kit was exported.

## Rebuild the image locally

Use Python 3.12 or newer. The PowerShell wrapper requires PowerShell 7. FFmpeg or the optional Python package imageio-ffmpeg produces the MP4 preview. From the repository root, install the pinned Python dependencies and rebuild into a fresh directory.

    python -m pip install -r requirements.txt
    python rebuild_nazar.py --output-dir revision-01

The PowerShell wrapper runs the same builder. Use a fresh output directory for each build.

    pwsh -NoProfile -File .\Rebuild-Nazar.ps1 -OutputDir .\revision-01

The script rebuilds the PNG from the source strips in decoded/, runs structural and animation quality validation, and generates contact sheets plus dark, light, and transparent motion previews. It writes to the requested output directory. For an additional lossless compression pass, install pyoxipng in an environment that supports it and use `--optimize-png` (PowerShell `-OptimizePng`). The builder checks pixel equality after compression, then validates the newly encoded bytes.

For an art change, replace the affected source strip in a working copy of decoded/ and rebuild. The original prompts and layout guides identify the required frame counts. Use the current pet atlas and the canonical artwork as identity references when generating replacement visuals, then review the new sprite at normal pet size. If you change the gaze, rebuild the affected eight-pose look row together so adjacent poses retain the same silhouette and move clockwise consistently. If the neutral pose or gaze pixels change, the build still generates previews and a quality report. Review the new direction sheet, record the sixteen verdicts and the `look_rgba_sha256` from the report, then rebuild into a fresh directory with `--direction-semantics <path>` (PowerShell `-DirectionSemantics <path>`). See pipeline/references/sprite-sheet-contract.md for the full review sequence.

The shipping sheet is a transparent 1536 × 2288 PNG with 192 × 208 cells. It has nine state rows and two gaze rows. The fifteen unused cells are transparent. The bundled blind review is bound to the checked-in neutral and gaze pixels. Rebuild and review new previews for each art revision.

## Apply the revised pet

The Pets plugin validates the exact encoded PNG before its upload-session tool transfers it. Pass that session to update_pet using the existing Nazar pet ID, then verify it and the active selection. See pipeline/skills/update-pet/SKILL.md and pipeline/references/upload-session.md for the full sequence.

The default rebuilt sprite SHA-256 is `3cd3669265bfce1fa6625e38d750f06d6cff9ec3bf0eafd144d497fa5ffeff4b`. The optional PNG optimizer can change the encoded hash while preserving every RGBA pixel.

## Rendering update

- Uses exterior-connected soft chroma recovery and single-pass body registration. The new jump keeps Nazar's body size, lifts 30 px, and lands on the idle baseline.
- Registers both gaze rows at subpixel precision. The 247.5-degree pose reads down-left on both axes in blind review. Two small silhouette differences at the gaze row boundaries are documented in the continuity report.
- Generates dark and light GIFs, transparent animated WebP, per-state loops, and a 2× inspection sheet. The MP4 uses RGB frames directly.
- Keeps visual review tied to the reviewed gaze pixels. Pets preflight reports come from the Pets validator for the exact encoded file.
