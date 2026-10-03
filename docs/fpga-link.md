# FPGA to edge box link (proposal, to agree with Abdullah)

How frames get from Abdullah's FPGA to the edge box in his weeks 12 to 16. This is Tarik's first draft so the software side is ready and testable before the hardware is. Nothing here is fixed: change any of it, then record the agreed version in a decision record (both owners).

The edge box side is built: `src/upchirp/sources/fpga.py` listens, puts packets back together into the usual Frame message, and publishes it. Everything that depends on the layout below lives in that one file.

## Why UDP

- The FPGA can send it with a small hardware block (no TCP state in the fabric), or from the Zynq's ARM side with a few lines of C or Python.
- A late frame is useless for live tracking. Dropping a frame is better than waiting for a resend.
- One standard Ethernet frame per packet: no jumbo frames, so any switch and any laptop works.

## Packet layout (draft v0)

One packet carries part of one chirp of one receive channel. All fields are little-endian.

| Bytes | Field | Type | Notes |
| --- | --- | --- | --- |
| 0 to 3 | magic | 4 chars | `UPC0` |
| 4 | version | u8 | 0 |
| 5 | stage | u8 | 0 = raw ADC samples, 1 = after the range FFT |
| 6 | sample format | u8 | 0 = int16 I, int16 Q, interleaved |
| 7 | n_rx | u8 | Receive channels in the frame (1, 2 or 4) |
| 8 to 11 | frame counter | u32 | Counts up by one per frame |
| 12 to 13 | chirp index | u16 | 0 to n_chirps minus 1 |
| 14 | rx index | u8 | 0 to n_rx minus 1 |
| 15 | reserved | u8 | 0 |
| 16 to 17 | n_chirps | u16 | Chirps per frame (64 in the draft chirp config) |
| 18 to 19 | n_samples | u16 | Samples per chirp (256) |
| 20 to 21 | first sample | u16 | Where this packet's samples start in the chirp |
| 22 to 23 | samples in packet | u16 | At most 360, so a packet fits in 1472 bytes |
| 24 to 31 | FPGA clock | u64 | Nanoseconds, any start point; kept in the frame's metadata |
| 32 on | samples | int16 pairs | I then Q, samples in order |

With the draft chirp config (2 channels, 64 chirps, 256 samples) one frame is 128 packets of 1056 bytes, about 135 kB. At 10 frames a second that is about 11 Mbit/s, well within 100 Mbit Ethernet.

## What the edge box does with it

- Packets can arrive in any order and are placed by their indexes.
- A frame is published when every sample has arrived.
- A frame still missing packets when a newer one completes is dropped and counted (`frames dropped`). A frame with holes would make false detections.
- Duplicates are ignored. Packets that do not parse, or whose n_chirps and n_samples do not match the chirp config in use, are counted as bad and ignored.
- Samples are scaled to plus or minus 1 (divided by 32768). The time stamp is when the first packet arrived at the box; the FPGA clock is kept alongside.

## Try it without hardware

A fake FPGA sends a simulated scene in this layout:

```
upchirp source --fpga-port 4991     # edge box: listen, publish frames
upchirp fake-fpga --port 4991       # pretend FPGA, in a second terminal
```

With `make live` running instead of the replay source, the live view shows the scene arriving over UDP.

## Questions to settle

1. **Byte order:** little-endian suits the Zynq's ARM and AXI. Fine, or network order (big-endian)?
2. **Sample format:** int16 I and Q? If the ADC is real (not I/Q), send real samples (format 1) and do the Hilbert step on the box, or form I/Q in the FPGA?
3. **Stage:** raw samples first, range FFT output later (stage 1) once his FFT is verified? With range FFT output, which bins: all 256, or only the ones that hold ranges (half for a real ADC)?
4. **FFT scaling:** for stage 1, what scale do the int16 values have, so the box can undo it (ties to question 5 in `fpga-test-vectors.md`)?
5. **Who sends:** hardware UDP block in the fabric, or software on the ARM side reading DMA buffers (PYNQ, DMA proxy, or u-dma-buf)? This decides the open item on the board and PYNQ.
6. **Chirp config:** should the header carry a chirp config id, so the box can check it is reading the settings the radar runs?
7. **Port and addresses:** UDP port 4991 by default; static IPs on a direct cable?
8. **Counter wrap:** the u32 counter wraps after about 13 years at 10 frames a second; the box does not handle the wrap yet.
