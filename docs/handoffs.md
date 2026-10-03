# Handoffs between Tarik and Abdullah

Abdullah's schedule runs in weeks from Monday 5 October 2026. Tarik's half has no dates.

| From | What | Feeds | When |
| --- | --- | --- | --- |
| Tarik | Reference DSP output: `upchirp vectors` writes quantized input, window and expected FFT; `sqnr_db` scores it. Format is a proposal: see `docs/fpga-test-vectors.md` | Abdullah's SQNR comparison of his fixed-point FFT | Ready; format to agree |
| Abdullah | Coffee-can recordings (stereo WAV: beat left, sync right) and the measured VCO sweep (start, bandwidth, sweep time) | Tarik's sound card adapter, ready: `upchirp import-wav` | Abdullah's weeks 6 to 11 |
| Abdullah | FPGA frames into Linux, as UDP packets. Layout is a proposal: see `docs/fpga-link.md` | Tarik's FPGA adapter (step 10), built and tested with a fake FPGA | Abdullah's weeks 12 to 16; layout to agree |
| Abdullah | Rev A data, ideally with someone noting what walked, drove or flew past and when (labels) | Tarik's real data evals and the classifier's real accuracy (decision 0011) | Abdullah's weeks 17 to 22 |
| Abdullah | SystemRDL register map | Tarik's generated Python register definitions | When the map is first defined |
| Abdullah | RCS calibration: a measurement of a target of known RCS (corner reflector) | `RCS_CAL_DB` in `src/upchirp/classify/rules.py`, which the drone-like labels depend on | With rev A characterization |

## Contracts

- Frame message: `docs/architecture.md`
- Register map: `regmap/` (Abdullah owns the source; Tarik consumes generated Python)
- Recordings: Parquet with the Frame fields as columns
