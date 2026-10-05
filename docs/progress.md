# Progress

Update this file at the end of every working session.

## Tarik

| Step | Status | Notes |
| --- | --- | --- |
| 1. Simulator and replay | done | `upchirp sim` saves frames, ground truth and a manifest; `upchirp replay` streams them back. Eval: all targets found at truth in range, Doppler and angle (400 of 400 target-frames). |
| 2. Reference DSP | done | OS-CFAR (decision 0004), 2D Kalman tracker, scoring in `scoring.py`, `upchirp score`. Evals on two scenes and two seeds: every target detected; ID switches only when the drone crosses the car (at most 2); position error at most 0.3 m for people and cars, about 1 m for the drone. A planted angle fault fails 9 gates. |
| 3. The agent (repo goes public) | done (public; 60-second video to do) | MCP server (`upchirp mcp`), LangGraph agent (`upchirp ask`), local model via Ollama (decision 0005), rule-based labels (decision 0006). Evals: drone question right on both scenes; planted wrong tool output caught. Settings changes wait for a human yes; audit log in `data/audit.jsonl`. The repo went public on 3 October 2026. |
| 4. Platform | done | `make up` / `make live`: source, processor and writer services over Redpanda (topic prefixes isolate environments), TimescaleDB hypertables per run, pgvector doc search with local embeddings, FastAPI with WebSocket live feed, TypeScript UI (map, range-Doppler, tracks, chat with approve or deny), OpenTelemetry spans. Checked in the browser: live view and chat on a looping replay. |
| 5. Full evals in CI | done | Green on GitHub since 3 October 2026 (all four jobs). Injection evals (notes and docs) with three defenses: untrusted marking, grounding guard, settings changes only on the user's request. Agent answers checked against SQL. `upchirp bench`: local model 10 of 10 correct, p95 16.2 s (rerun 4 October), $0 (`docs/reports/`); hosted not measured (no key). Threat model in `docs/threat-model.md`. CI has four jobs: Python, UI, platform (Redpanda + Postgres), Helm. |
| 6. Live demo | done | Live since 4 October 2026 at http://ec2-51-21-241-160.eu-north-1.compute.amazonaws.com: one t4g.small in Stockholm (eu-north-1), the 15-minute courtyard live, read-only tools, rate limits and a $1 daily cap, on a fixed address (Elastic IP) since 5 October. The model is the Anthropic API with a key in Parameter Store until AWS grants Bedrock quota (declined once, decision 0015). |
| 7. Offline bundle | done (container test) | `deploy/bundle/build.sh` makes a 6.1 GB folder (10 GB before slim images): k3s v1.36.5 air-gap, Helm chart (22 resources), all images, Ollama models, Prometheus and Grafana with a health dashboard, SHA256SUMS, `install.sh`. Installed on a fresh Ubuntu 24.04 machine with no internet (container stand-in): all pods running, agent answered correctly through the local model. Found and fixed: k3s needs a default route when the cable is unplugged. Hosted vs local evals wait on an API key. |
| 8. Install test | next | Needs three people and a real machine. Kit ready: `docs/install-test/` (how to run it, tester sheet, write-up template). |
| 9. Classifier | in progress (waits on real recordings) | CNN on RAD-DAR (17,485 real patches, 80 recordings, held out by recording): 90.1% native, 90.2% on our grid (no measurable conversion cost), 36.1% on our simulator (chance: no micro-Doppler in the sim). ONNX model ships as an option; rules stay default (decision 0011). Micro-Doppler and car size in the simulator lifted simulated accuracy to 59% (decision 0012). Real accuracy waits on step 10. Cars are now tracked at their real size (decision 0013): the crossing scene's car is 4.5 m long in every eval; a drone low over a real-size car is a known limit. |
| 10. Real hardware | waiting on Abdullah | Sound card reader for coffee-can recordings (`upchirp import-wav`). FPGA reader over UDP (`upchirp source --fpga-port`), tested with a fake FPGA (`upchirp fake-fpga`); packet layout is a proposal (`docs/fpga-link.md`). Next: agree the layout, then rerun every eval on real data. |

## Alongside

- [ ] Post after step 3: an eval catching a planted wrong answer
- [ ] Post after step 7: hosted vs local numbers
- [ ] Post after step 8: the install test
- [ ] Stretch: fine-tune the local model on the agent's own tool calls

## Abdullah

| Weeks (ends) | Work | Status |
| --- | --- | --- |
| 1 to 5 (8 Nov 2026) | Cascaded budget, PLL and antenna simulation, Vivado basics, parts, coffee-can build | not started |
| 6 to 11 (20 Dec) | Coffee-can echoes, RTL for ADC interface, window, FFT, fixed-point analysis | not started |
| 12 to 16 (24 Jan 2027) | FPGA in the loop, UVM, rev A ordered | not started |
| 17 to 22 (7 Mar) | Rev A bring-up, characterization, 2-channel angle | not started |
| 23 to 28 (18 Apr) | Rev B, final report | not started |

## Open items

- [ ] Exact Xilinx board model, and whether it runs PYNQ. Known (4 October): Abdullah can use a board at his university lab, but cannot take it home; decide by week 11 whether integration and the final demo happen at the lab or on a board of the same family bought for it
- [ ] University lab access for noise figure and phase noise
- [ ] AWS account and budget alarm
- [x] Repo home: github.com/TarikAlHadethi/upchirp (public)
