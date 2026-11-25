# Showcase

Presentation renders of Nazar. Every motion artifact here is generated from
`final/spritesheet-extended.png` — the same validated bytes that ship to ChatGPT — and
the renderer never writes to the atlas. SHA-256 of the source sheet is recorded in
[`showcase-manifest.json`](showcase-manifest.json).

    python qa/render_showcase.py --output-dir showcase --theme dark

Supersampling defaults to 4×, 60 fps, motion-aware inbetweens, and a 384 px GIF derived
from the encoded master. ffmpeg comes from `PATH` or from the optional
`imageio-ffmpeg` package; `--only poster` needs neither.

## What is here

| Artifact | Contents |
| --- | --- |
| `Nazar-hero.png` | Promotional key art. Generated, not sprite art; provenance in `hero.json` |
| `Nazar-codex-poster.png` | One-page sheet: nine state cards plus all sixteen gaze directions |
| `Nazar-codex-motion-dark-4x.mp4` | 11 s, 60 fps, 802×944, all states with coded captions |
| `Nazar-codex-motion-light-4x.mp4` | The same cut on the light theme |
| `Nazar-codex-motion-dark-authentic.mp4` | 1:1 playback with no inbetweens, as the client plays it |
| `Nazar-codex-motion-dark.gif` | 384 px inline version for the README |
| `states/*.mp4` | Per-state loops at 60 fps |
| `states/gaze-16.mp4`, `states/gaze-16-alpha.webp` | The sixteen-direction gaze loop, with and without alpha |
| `states/idle-jump-idle.mp4` | The transition users actually watch |
| `states/idle-timing-*.mp4` | Canonical cadence beside the calmer proposal |

## What the renderer adds

- **Hard-cut detection.** Blinks, lid settles, and gaze shifts keep an identical silhouette,
  so cross-fading them double-exposes the eyelid. Any transition with silhouette IoU above
  0.993 and centroid travel under 1.5 px stays discrete; only genuine body travel is
  interpolated. That is why the authentic cut and the smoothed cut look equally clean.
- **Motion-compensated inbetweens.** When the body does travel, both poses are parked on the
  same eased centroid before the fade, so a jump translates instead of ghosting.
- **Fringe repair.** The shipped sheet still contains 2,571 fully opaque, near-magenta pixels
  at silhouette edges. Invisible at 192×208, they read as pink confetti at 4×. The renderer
  replaces them with the mean of their clean neighbourhood and reports the count; alpha is
  never touched. The atlas itself is untouched, so every existing QA hash stays valid.
- **Theme-correct contact.** A black drop shadow is invisible on a near-black background, so
  the dark theme gets a cool floor pool instead and the light theme keeps a real shadow.

## Codex state map

The sheet has nine standard rows. Naming them by product moment makes the pet legible in a
Codex session:

| Row | Pet state | Codex moment |
| --- | --- | --- |
| 0 | `idle` | Ready. Frame 0 is also the reduced-motion still |
| 1 | `running-right` | Working, moving out — a call is in flight |
| 2 | `running-left` | Moving back — undo, retry, return |
| 3 | `waving` | Session start, greeting |
| 4 | `jumping` | Build or task started; 30 px lift, lands on the idle baseline |
| 5 | `failed` | Tests red; fast recoil, slow recovery |
| 6 | `waiting` | Blocked on your approval or input |
| 7 | `running` | Thinking through the task — scoped gaze, not literal foot-running |
| 8 | `review` | Reading the diff |
| 9-10 | `look 000-337.5` | Sixteen clockwise gaze directions, `000` up |

## Timing proposal

`qa/state-timing-proposal.json` holds a calmer cadence derived from frame study: hold the
readable extreme longer, keep the transition short, never stretch a three-frame blink past
about 200 ms. The shipped sheet carries no timing metadata, so these durations affect
previews and the reference table, not client playback. The proposed idle holds the open eye
for 1.15 s and blinks in 160 ms, where the current table blinks every 1.1 s.

Renders with and without it:

    python qa/render_showcase.py --output-dir showcase --timing qa/state-timing-proposal.json

## Known art limits

Two things this layer cannot fix:

- `waving` reads as "eye up, paws out" rather than a clear greeting. That is an artwork and
  semantics problem, not a timing one; the contract asks for a greeting carried by an
  attached limb, and the row does not quite deliver it.
- The magenta remnants above are a despill gap in the atlas, so they should eventually be
  fixed in the pipeline (`despill_chroma_edges.py`) rather than repaired at render time.
