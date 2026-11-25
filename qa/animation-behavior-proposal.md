# Motion ideas for Nazar

The most promising idea from Parker is the timing of a reaction. A poke reads immediately because the body flinches first and the expression settles more slowly. Nazar can use that timing to make the existing failure animation easier to read at pet size.

## Shipped failure recoil

The existing eight-frame `failed` row uses a quick recoil and a slower return. The builder sequences the registered poses as `0, 2, 4, 3, 5, 6, 1, 7`, with the same first and last poses and the same frame holds.

| Frames (zero-indexed) | Motion |
| --- | --- |
| 0 | Start from a stance close to idle. |
| 1–2 | Tuck back slightly and narrow the lid. Reach the strongest expression early. |
| 3–5 | Ease the shell back toward center while the lid stays partly lowered. |
| 6–7 | Reopen the eye and settle into a stance that joins idle cleanly. |

Keep the feet on the same ground line and retain the existing body scale, rim, and eye construction. The lid and posture should carry the reaction. Check both the loop seam and the return to idle.

## Second experiment

Parker can signal reluctance with a small motion even when he declines to play. Try that economy in Nazar's six-frame `waiting` row. Let the eye lift briefly toward the viewer, tip the shell forward slightly, and hold the expectant pose before easing back. The held look should read as asking for input and stay distinct from idle breathing and review's inspection motion.

## Scope and acceptance

- Start with the failure row. Keep the waiting idea available as a separate A/B. The jump and gaze already have their own revision history.
- Parker's food reactions, repeated-poke memory, fling dizziness, and sleep depend on actions or state in its desktop runtime. Those have no dedicated trigger or row in Nazar's current sprite-sheet contract.
- Use the current Nazar art as the reference. Generate a candidate strip, then use the existing rebuild pipeline and compare the current and proposed rows on dark and light backgrounds at 64 px. Keep a candidate only if people can tell failure, waiting, and review apart in motion and the loop returns cleanly to idle. Run the existing quality checks and validate the exact encoded atlas before any installation.

The waiting motion remains an optional idea.
