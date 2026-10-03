# 0006: Rule-based track labels from estimated RCS until the classifier

- Date: 2026-10-03
- Owner: Tarik
- Status: accepted (replaced by the step 9 classifier when it beats these rules)

## Context

The agent must answer questions about drone-like tracks at step 3, but the trained classifier comes at step 9.

## Decision

Estimate each detection's radar cross section from its SNR and range (radar equation, received power falls as 1/R^4), take the median over a track's last 20 detections, and label: 5 dBsm and up is a car, -10 dBsm and down is drone-like, between is a person. The calibration constant (78.2 dB) was measured on the simulator.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Speed rules | A hovering drone and a standing person look the same |
| Height from elevation angle | Our 2-channel array has no elevation |
| Wait for step 9 | Blocks the agent and the demo for months |

## Consequences

Labels are right in 100% of tracked frames in the simulator. Since decision 0010 the simulator adds Swerling fluctuation, and labels stay right in 99 to 100% of frames because the median over 20 detections smooths it; real data will still be harder. On real data the constant must be measured again with a corner reflector (handoff to Abdullah), and fluctuation will cause errors. The label is always called "drone-like", never "drone".
