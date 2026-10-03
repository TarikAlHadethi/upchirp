# 0011: Patch classifier trained on RAD-DAR, shipped as an option until real data decides

- Date: 2026-10-03
- Owner: Tarik
- Status: accepted

## Context

Step 9 replaces the rule-based labels (decision 0006) with a trained classifier. The training data is RAD-DAR: 17,485 real range-Doppler patches of people, cars and drones from another radar (8.75 GHz, 0.878 m and 0.094 m/s per cell).

## Decision

A small CNN (two 3 by 3 convolutions, one dense layer) on one 11 by 15 range-Doppler patch per detection, cut around the target in our grid. RAD-DAR patches are converted to our grid in metres and metres per second: Doppler power integrated over our 0.41 m/s cells, range interpolated to our 1 m cells, then normalised to the patch peak. Trained with PyTorch on a CPU (6 minutes, no Spot instance needed), logged to MLflow, exported to ONNX (1.4 MB), run with ONNX Runtime. Test sets are whole held-out recordings, over three splits.

Results (`docs/reports/classifier.md`): 90.1% native, 90.2% converted, so no measurable conversion cost; 36.1% on our simulator, about chance.

The rules stay the default. The classifier runs with `UPCHIRP_LABELER=onnx`.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Make the classifier the default now | On simulated data it is at chance, so labels and every eval would get worse; real data has not been measured |
| Random split of samples | Samples within a recording are near-copies; a random split leaks them into the test set and inflates accuracy |
| Three stacked frames, as in the RAD-DAR paper | Needs tracks before the first label; one frame first, stacking is the next experiment |
| Train in AWS on a Spot instance (the plan) | The model trains in minutes on the laptop CPU; the cloud adds cost and nothing else |

## Consequences

The simulator cannot evaluate the classifier until it models micro-Doppler (limbs, wheels, rotors): that is the next simulator work. Real accuracy comes from Abdullah's recordings (step 10); the classifier becomes the default only if it beats the rules there. Re-run `python ml/train.py` after any change to the patch format; it regenerates the report.
