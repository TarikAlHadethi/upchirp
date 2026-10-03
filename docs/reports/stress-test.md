# Stress test: 3 October 2026

What happens to the platform under load and over time, measured on one Windows machine (20 CPU threads) running the full stack: Redpanda and PostgreSQL in Docker, then processor, writer, alerts, API and a live simulated source (`upchirp live`). Every finding below led to a change in the same night; the commit is named.

## Pipeline speed

| | Per frame | Frames per second |
| --- | --- | --- |
| Before | 44 ms (90% in the OS-CFAR rank filter) | 23 |
| After | 3.7 ms | about 270 |

The radar sends 10 frames a second, so the old pipeline used 44% of a fast core; on the demo's small ARM server it would likely not keep up. The threshold is now computed only at local maxima, which are the only cells that can be detections. Detections are identical frame by frame on both scenes (commit "OS-CFAR threshold only at local maxima").

## 50 live viewers plus 400 REST calls

50 browsers on the live view for 60 s, while 400 REST calls arrive 20 at a time.

| | Before | After |
| --- | --- | --- |
| REST p95 | 700 to 975 ms | 170 ms |
| `/api/health` median | 610 ms | 43 ms |
| Live view lag behind the radar, median | 0.13 s | 0.04 s |
| Errors, dropped viewers | 0 | 0 |

Cause: per-message WebSocket compression. The API compressed every range-Doppler picture (22 kB, 10 a second) once per viewer. Now the processor compresses it once (zlib, half the size), the browser decompresses it, and the API sends only what the page draws (detections were a third of all messages and unused). With one viewer, REST calls took 42 to 77 ms, so the remaining cost under load is sharing one CPU.

## Viewers coming and going for an hour

10 viewers at a time, each staying 5 to 60 s, 30% leaving without a clean close (tab killed). Samples every 5 minutes for an hour:

- Live lag p95 0.04 to 0.06 s throughout.
- The server always counted 10 or 11 viewers: no connection left behind, even after aborted ones.
- No visit failed.
- Memory: no growth beyond allocator steps. A separate check of 6,000 short visits in rounds of 1,500 went 134, 146, 145, 157, 157 MB: it steps up and levels off.

## Writer crash

The database fails while the writer holds a batch of 30 messages. Before: offsets were committed when messages were read, so a restarted writer skipped them (0 of 30 rows). Also, the writer did not leave its consumer group when the last write failed, so a restarted writer waited out the session timeout. After: offsets are stored only after a successful write, and the consumer always closes; 30 of 30 rows. `tests/test_platform_live.py::test_writer_crash_loses_nothing` fails on the old code and passes on the new.

## Robustness over seeds

The tracking eval used two noise seeds per scene. Run on seeds 0 to 11 of both scenes, 23 of 24 passed; seed 9 of the default scene had 5 ID switches when the drone flew over the car. The cause was the simulator: tyre micro-Doppler ignored the viewing angle, so a car crossing the view smeared echo over the drone's speed. With the angle in (decision 0012, update), all 24 pass with at most 1 ID switch. The eval suite now runs four seeds per scene.

## 15 minutes of a busy courtyard

The first 15-minute run counted 24 drone-like objects where there were 4: one drone hovering beside a tree broke into 20 pieces (a known limit), and stitching could not join short pieces. After the changes in decision 0014, three layouts give 4 of 4 every time. It also showed a new limit: a person crossing the view at a tree's range is hidden while their radial speed is near zero.

Then the real thing: the live system on the courtyard for 12 minutes, the headline question asked through the live view. The agent said 4 drone-like tracks for 3, and named the wrong one as closest. Causes: a person briefly labelled drone-like after 3 fluctuating echoes, and the small model misreading a list. A drone-like label now needs 1 s of echoes, and the track tool states the closest track itself; over 8 more noise seeds the count is right every time (decision 0014, update).

## Offline install

The bundle rebuilt with all of the above (k3s and Helm now checked against their release checksums) installed on a fresh Ubuntu 24.04 machine with no network in 4.5 minutes. Every pod ran (application pods now as a non-root user, every workload with a memory limit, Grafana view only), and the agent answered the drone question correctly.

## Not tested

Hardware other than this machine (the edge box and the t4g.small demo server); more than 50 viewers; a broker or database outage longer than a restart.
