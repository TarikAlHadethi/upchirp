# 0014: A 15-minute courtyard for the demo and a long-run eval

- Date: 2026-10-03
- Owner: Tarik
- Status: accepted

## Context

The demo looped 10 to 12 second recordings, and every loop is a new run. So "how many drone-like tracks crossed in the last 10 minutes?" was answered from the last few seconds. The short scenes also never showed what happens over many minutes: the first 15-minute run counted 24 drone-like objects where there were 4.

## Decision

1. **A `courtyard` scene** (`sim/scene.py`): 15 minutes, people walking through about every 45 s, cars on the road behind about every 75 s, two drone-like targets crossing and two hovering for a minute. The schedule comes from a fixed seed, one random stream per kind of target. It is simulated live (`upchirp source --scene courtyard --loop`), so nothing is stored. The public demo and the edge box (until real hardware) play it.
2. **Scene realism rules**: people do not walk through tree trunks (they keep 2 m away), and hovering drones keep 10 m from trees and walls. A drone hovering beside clutter is a known limit with its own scene (decision 0010); placed there by chance, it turned one drone into 20 track pieces.
3. **Stitching** (`agent/data.py`): a piece may start near where the last one stopped, not only where it was heading (short pieces have wild velocity estimates), and an object that stood still is joined over a gap of up to 10 s if the new piece starts within 3 m.
4. **A long-run eval** (`evals/test_long_run.py`): the drone-like object count after stitching must equal the truth; the other gates sit just below the worst of three layouts.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Record 15 minutes and replay it | About 2.4 GB of raw frames per scene |
| Keep the short loops and change the question | The question is the point of the demo |
| Wider stitching gaps for everything | Joins two different people who pass the same spot |

## Consequences

Measured on three layouts (seeds 7, 8, 9), noise seed 0: drone-like objects 4 of 4 every time; cars detected 98.5 to 99.4%, drones 89 to 97%, people 82.5 to 95.7%; at most 12 ID switches and 0.021 false tracks per frame in 15 minutes.

**Known limit found:** a person crossing the view at the same range as a tree (about 32 m here) is hidden while their radial speed is near zero. They sit in the same range and Doppler cell as the tree, and two receive channels cannot separate two sources in one cell by angle. Coverage of such a walk drops to 35 to 50%, and the person may be counted twice. More receive channels (rev B) or spatial nulling of the tree's direction would help.

## Update: what a 12-minute live run showed

Asked the headline question through the live view after 12 minutes, the local agent got two things wrong, and both are fixed:

- **A person briefly labelled drone-like.** A track got its label after 3 detections. A person's echo fluctuates, and the median of 3 estimates falls 10 dB under its mean about 2.5% of the time. A drone-like label now needs 10 detections (1 s; about once in 10,000 by chance); until then the track says "unknown". People and cars still get their label after 3. The eval's label check now counts only frames with a label (at least 95% right) and separately needs at least 80% of tracked frames labelled, so holding back is not scored as a wrong label.
- **The wrong closest track.** The model picked the wrong entry from the list of tracks. `get_tracks` now returns a `closest` field with the answer worked out, and the prompt says to use it.

Over noise seeds 1 to 8 of the demo layout, the drone-like object count is now 4 of 4 every time (before the label change, seeds 1 and 3 counted 5).

Still open: in the live run, one crossing drone was counted twice, as two tracks running at the same time. It did not happen on any of the 8 noise seeds run afterwards. Merging two same-label tracks that run side by side would also merge two people walking together, so it is left as it is.
