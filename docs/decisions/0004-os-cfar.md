# 0004: Ordered-statistic CFAR instead of cell-averaging CFAR

- Date: 2026-10-03
- Owner: Tarik
- Status: accepted

## Context

In the default scene the drone-like target sits 6 range bins from the car, in the same Doppler bin, about 30 dB weaker. Cell-averaging CFAR put the car inside the drone's training window, raised the threshold, and missed the drone in 35% of frames.

## Decision

Use ordered-statistic CFAR: the noise estimate is the 75th percentile of the training cells (`dsp/cfar.py`). Peaks are kept only if they are the largest in a 3 by 3 window, so two targets 3 range bins apart both survive.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Cell-averaging CFAR | Masks weak targets next to strong ones, as above |
| Smallest-of or greatest-of CFAR | Only helps when the interferer is on one side; OS-CFAR handles both and is just as textbook |
| Lower window sidelobes (Blackman-Harris) | Did not fix masking and widened the main lobe, which lost close targets |

## Consequences

Every target in both scenes is detected in every frame. The rank filter costs about 40 ms per frame in NumPy, fine for 10 frames per second. The textbook threshold formula assumes single-channel exponential noise; we sum two channels, so the real false alarm rate is lower than designed (tested in `tests/test_cfar.py`). Revisit on real data from Abdullah's hardware, where clutter will change the noise.
