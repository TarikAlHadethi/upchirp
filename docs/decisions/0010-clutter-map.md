# 0010: Clutter map with a power map, instead of per-frame static clutter removal

- Date: 2026-10-03
- Owner: Tarik
- Status: accepted

## Context

The simulator now adds what a courtyard really has: walls, a lamp post, the ground, trees whose leaves move, echoes that fade from frame to frame (Swerling 1 and 3), and a hovering drone that bobs. Without clutter handling, the trees alone made about 2 false tracks at all times.

## Decision

A clutter map (`dsp/clutter.py`) for a radar fixed in one place. While the scene is quiet at start (2 seconds), it learns the complex background echo of every range bin and subtracts it from every chirp; afterwards it keeps learning slowly (60 s time constant). It also learns each range-Doppler cell's usual residual power, and a detection must be 10 dB above that. Range bins and cells near a detection are never learned from.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Subtract each frame's mean over chirps (common on radar chips) | Erases targets moving across the view and the hovering drone, and left ghosts: 8 tracks for 4 targets |
| Ignore detections near zero speed | Same loss: anything moving across the view or hovering disappears |
| Drop tracks that do not move | Would drop the hovering drone too |

## Consequences

On both scenes and four seeds: every target found 97 to 100% of the time, no false tracks, no ID switches. Costs: the radar needs a quiet moment after starting, and anything still for about a minute fades into the background. A small target at nearly the same range and speed as a tree is lost (seen when a tree sat 1.7 m from the hovering drone); two receive channels cannot separate them. The scenes avoid that case; a dedicated eval should cover it.
