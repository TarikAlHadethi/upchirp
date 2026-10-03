# 0013: Cars at their real size, grouped where the echoes are found

- Date: 2026-10-03
- Owner: Tarik
- Status: accepted

## Context

A real car is not a point. Driving towards or away from the radar it is 4.5 m deep in range, and its echo often comes back as two strong spots, one at each end, about 3 m apart at the same speed. Decision 0012 kept the simulated car a point in the tracking scenes because the old grouping (echoes at most 1.2 m apart) left the two ends separate: with the car at real size, the crossing scene made 1.3 false tracks per frame against a limit of 0.05.

## Decision

Group the echoes where they are found, before tracking, with three rules. Echoes must always have the same speed (within 0.6 m/s) and fit in one car length plus a range cell (5.5 m):

1. **Close together:** within 1.2 m and 10 degrees, as before (a body and its neighbouring range cell).
2. **Side on:** up to 2.5 m deep at nearly the same angle (2.5 degrees). A car crossing the view is about 2 m deep, at close to zero radial speed.
3. **Along the line of sight:** up to 5.5 m at nearly the same angle, only with a clear radial speed (1 m/s or more). A body only looks long in range when it moves along the line of sight.

Rule 3's speed condition matters: in the crossing scene two people walk past each other 3 m apart, both at nearly zero radial speed, and line up for a moment at the same angle. Without it they merge and a person is missed (people detection fell to 95.4%, under the 97% gate).

Scoring now knows the body's depth: the simulator's ground truth carries `extent_m`, a detection anywhere on the body counts as on target, and the track gate grows by half the body.

The car driving away in the crossing scene is now real size in every eval. The default scene's car stays a point (see below).

## Alternatives considered

| Option | Why not |
| --- | --- |
| A wider simple gap (3.5 m) | Merges the two crossing people |
| Group inside the tracker, after association | A track at the car's centre is 1.5 to 2 m from either end, outside its gate, so it loses both ends; grouping first gives the tracker one measurement near the centre |
| A full extended-object tracker (random matrices, shape estimation) | On the cut list ("advanced trackers"); the simple rule passes every gate |

## Consequences

- Measured on both crossing seeds with the car at real size: no false tracks, no ID switches, car position error 0.29 m. With point cars nothing got worse.
- **Known limit:** in the default scene the drone flies low over the car. At real size the car's body (1000 times the drone's echo) covers 2 m more range for longer, and the drone is lost for a while: detection 86% instead of 97%, 9 ID switches. A strict expected-failure eval (`test_drone_over_a_real_size_car_is_found`) records it. Elevation (rev B's extra channels) would separate them.
- Two objects at the same angle, the same speed and less than a car length apart look like one object. Two people walking side by side towards the radar are an example.
- Revisit if real recordings show car echoes spread more widely than the simulator's five spots, or people merging.
