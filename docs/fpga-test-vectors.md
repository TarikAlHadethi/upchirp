# FPGA range FFT test vectors (proposal, to agree with Abdullah)

The handoff after Tarik's step 2: reference data for Abdullah's fixed-point range FFT, and one number to judge it by, SQNR. Generate with:

```
upchirp vectors --out dist/fft-vectors
```

Options: `--adc-bits 12`, `--window-bits 16`, `--real-input` (real ADC samples only), `--bit-reversed` (expected output in bit-reversed order), `--frame 40` (which frame of the default scene).

## What is in the folder

| File | Content |
| --- | --- |
| `input_i.mem`, `input_q.mem` | ADC samples, 16-bit two's complement hex, one word per line, chirp after chirp, for `$readmemh` |
| `window.mem` | Hann window, Q1.15 by default, one word per line |
| `input_iq.npy`, `window.npy` | The same as NumPy arrays (for cocotb tests in Python) |
| `expected_fft.npy` | Complex float64 range FFT of exactly the quantized input times the quantized window |
| `vectors.json` | The settings used, so the folder explains itself |

The input is one receive channel of a simulated frame with people, a car and a drone-like target in a courtyard (ground truth known), scaled to 90% of the ADC's full range.

## How it is scored

`upchirp.dsp.vectors.sqnr_db(expected, measured)` fits one complex gain first, so the FFT's output scaling (a power of two, from its scaling schedule) is not counted as error. Everything left over is noise:

SQNR = 10 log10( energy of expected / energy of (expected - gain x measured) )

A good 16-bit pipelined FFT should land roughly in the 60 to 90 dB range; the plan asks for the number, not a fixed target, and for how it changes with the scaling schedule.

## Questions to settle

1. **ADC:** real samples (one ADC per channel) or I/Q? How many bits? The default assumes complex input and 12 bits.
2. **FFT size:** 256 points per chirp, as in the chirp config draft? Does it change for rev A?
3. **Window:** Hann applied in the FPGA? Coefficient width (Q1.15 default)?
4. **Output order:** natural or bit-reversed? (Both supported.)
5. **Output width and scaling:** full bit growth or scaled per stage? Fixed or block floating point? This decides what "gain" the SQNR fit removes.
6. **File format:** is one hex word per line fine, or does the testbench want packed I and Q per word?
7. **How many frames:** one frame (64 chirps) by default; more for coverage?

When these are agreed, record them in a decision record (both owners) and make them the defaults.
