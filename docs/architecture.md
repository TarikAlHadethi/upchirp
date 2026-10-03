# Architecture

## Topology

Radar front end → Xilinx FPGA board (window and range FFT) → Ethernet → edge box (mini PC running k3s) → syncs to AWS when online. A small public demo server on EC2 runs the same services in replay mode.

## Frame sources

Every source is an adapter that publishes the same `Frame` message to the `frames` topic. The pipeline never knows which source it reads.

| Adapter | Source | When |
| --- | --- | --- |
| `sim` | Simulator, with ground truth | From step 1 |
| `replay` | Parquet recording | From step 1 |
| `soundcard` | Coffee-can radar via sound card | Step 10 (Abdullah's weeks 6 to 11) |
| `fpga` | FPGA board over UDP or PYNQ DMA | Step 10 (Abdullah's weeks 12 to 16) |

## Frame message (draft v0)

Agree any change with Abdullah through a decision record.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | int | Starts at 0 |
| `source` | str | `sim`, `replay`, `soundcard`, `fpga` |
| `session_id` | str | Recording or run id |
| `frame_index` | int | Increments per frame |
| `timestamp_ns` | int | Capture time, Unix nanoseconds |
| `chirp_config_id` | str | Points to the chirp config in effect |
| `n_rx` | int | Receive channels (1, 2 or 4) |
| `n_chirps` | int | Chirps per frame |
| `n_samples` | int | Samples or range bins per chirp |
| `stage` | str | `raw` (time samples) or `range` (after range FFT) |
| `data` | bytes | complex64, shape `[n_rx, n_chirps, n_samples]`, C order |
| `meta` | map | Free-form; treated as untrusted input (prompt injection tests use it) |

Ground truth for simulated sessions is stored separately (`ground_truth` table and Parquet file), never inside `meta`.

## Chirp config (draft)

| Field | Example |
| --- | --- |
| `f_start_hz` | 5.725e9 |
| `bandwidth_hz` | 150e6 |
| `chirp_duration_s` | 1e-3 |
| `n_chirps` | 64 |
| `sample_rate_hz` | set by the ADC |

Range resolution = c / 2B ≈ 1 m at 150 MHz.

## Topics and runs

| Topic | Message |
| --- | --- |
| `frames` | Frame, binary (`frame.to_wire`: magic, header length, JSON header, raw samples) |
| `detections` | JSON per frame: run id, session id, frame index, detections |
| `tracks` | JSON per frame: run id, ..., track states with label and RCS |
| `rdmaps` | JSON per frame: 8-bit range-Doppler image for the live view |

A run is one pass of the processor over a session; a looping replay makes a new run each loop. `UPCHIRP_TOPIC_PREFIX` prefixes topics and consumer groups so tests and the public demo never share a stream with the edge box.

## Services on the edge box

| Service | Reads | Writes |
| --- | --- | --- |
| source adapter | sim, file, hardware | `frames` |
| dsp | `frames` | `detections` |
| tracker | `detections` | `tracks` |
| classifier | `tracks`, frames | track labels |
| writer | all topics | Postgres, Parquet |
| api | Postgres, topics | REST, WebSockets |
| mcp server | api | agent tools |
| agent | mcp server | answers, audit log |

## Agent tools

| Tool | Kind | Public demo |
| --- | --- | --- |
| `query_detections(window, filters)` | read | yes |
| `get_tracks(window, label)` | read | yes |
| `summarize_session(session_id)` | read | yes |
| `search_docs(query)` | read (RAG) | yes |
| `replay_recording(session_id)` | control | no |
| `set_chirp_config(settings)` | destructive, needs human yes | no |
