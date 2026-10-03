# 0012: Micro-Doppler in the simulator; the tracker handles echoes from moving parts

- Date: 2026-10-03
- Owner: Tarik
- Status: accepted

## Context

The classifier scored at chance on our simulator (decision 0011) because simulated targets were single points. Real targets have moving parts: swinging limbs, turning wheels, spinning rotors (micro-Doppler).

## Decision

The simulator adds moving parts as extra scatterers (`sim/micro_doppler.py`): two legs and two arms swinging at the gait rate, points on the tyres moving at 0.3 to 1.7 times the car's speed, and two-bladed rotors at about 100 Hz whose echo smears over every speed. Doppler cells within 30 dB of the peak: person 3 to 11, car 4 to 18, drone 3 to 59 of 64.

The detector keeps every echo. The tracker associates the echo that fits each track (its speed gate prefers the body), does not start a new track from an echo within 1.5 m and 15 degrees of an existing track, starts at most one new track per spot per frame (the strongest echo), and drops a track that sits on another and moves the same way. Scoring counts echoes at a target's range and angle but another speed as moving-part echoes, not false alarms.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Keep only the strongest echo per spot | When the drone body fades, a blade echo wins and the speed is wrong: 7% of drone frames |
| Judge "same spot" by x and y distance | Part echoes are weak, so their angles are poor; at 30 m an 8 degree error is 4 m |
| Leave the simulator with point targets | The classifier cannot be judged on simulated data at all |

## Consequences

Eval gates now differ by label, from measured results on four seeds: the drone is detected 93 to 98% of the time (gate 90%, people and cars stay at 97%), its angle error rises to about 1.2 degrees (gate 1.5) and its track position error to at most 1.06 m (gate 1.25, others stay 0.5). In the default scene the drone flies over the car; with no elevation the radar cannot separate them for a moment, and the drone's track breaks into pieces (up to 2 ID switches, gate 2). A target within 1.5 m and 15 degrees of another track cannot start its own track until it moves apart.

Because of those breaks, the agent's tools stitch track pieces into objects (`agent/data.py`): a piece that starts within 3 s after (or 0.5 s before) another of the same label ends, within 6 m of where that one was heading, is the same object. Without it the agent answered "3 drone-like tracks" for one drone. Tools report each object's `track_pieces`.

Real targets also have size. The simulator can spread a car's body over its 4.5 m (`extended`), which took the classifier from 38% to 59% on simulated data (cars 86%, people 75%, drones 7%: real drone recordings are farther and noisier). Tracking a target that wide needs extended-object tracking, which is not built yet, so the tracking scenes keep point-sized bodies and only the classifier's patches use `extended`.

## Update, 3 October 2026: micro-Doppler depends on the viewing angle

Limbs and tyre treads move along the direction of travel, so only their motion along the line of sight shows up as Doppler: all of it for a target coming straight at the radar, almost none for one crossing the view. The simulator first used a fixed share (0.7 for tyres, 1 for limbs). Now the share is the cosine of the aspect angle (`sim/engine.py::aspect`).

What it fixed: in the default scene the car crosses the view, and its tyres were smearing echo over every speed, including the drone's, when the drone flew over it. Run on seeds 0 to 11 of both scenes, ID switches fell from up to 5 per run (seed 9 failed its gates) to at most 1, and every gate held on all 24 runs. Simulated classifier accuracy is unchanged (60.5%).

What it changed in scoring: the car driving away now shows its tyres' contact patch at 0 m/s, beside the hovering drone's range for a moment. The scorer had matched that tyre echo to the drone, 25 degrees away. A detection now has to be within 15 degrees of a target to count as its echo (`scoring.MATCH_AZIMUTH_DEG`); others count as part echoes or false alarms. The eval suite now runs four seeds per scene instead of two.
