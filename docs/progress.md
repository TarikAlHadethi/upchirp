# Progress

Update this file at the end of every working session.

## Tarik

| Step | Status | Notes |
| --- | --- | --- |
| 1. Simulator and replay | done | `upchirp sim` saves frames, ground truth and a manifest; `upchirp replay` streams them back. Eval: all targets found at truth in range, Doppler and angle (400 of 400 target-frames). |
| 2. Reference DSP | done | OS-CFAR (decision 0004), 2D Kalman tracker, scoring in `scoring.py`, `upchirp score`. Evals on two scenes and two seeds: every target detected, 0 ID switches, position error at most 0.31 m. A planted angle fault fails 9 gates. |
| 3. The agent (repo goes public) | done (repo still private) | MCP server (`upchirp mcp`), LangGraph agent (`upchirp ask`), local model via Ollama (decision 0005), rule-based labels (decision 0006). Evals: drone question right on both scenes; planted wrong tool output caught. Settings changes wait for a human yes; audit log in `data/audit.jsonl`. Going public and the 60-second video are Tarik's call. |
| 4. Platform | done | `make up` / `make live`: source, processor and writer services over Redpanda (topic prefixes isolate environments), TimescaleDB hypertables per run, pgvector doc search with local embeddings, FastAPI with WebSocket live feed, TypeScript UI (map, range-Doppler, tracks, chat with approve or deny), OpenTelemetry spans. Checked in the browser: live view and chat on a looping replay. |
| 5. Full evals in CI | done (CI run on GitHub not yet seen) | Injection evals (notes and docs) with three defenses: untrusted marking, grounding guard, settings changes only on the user's request. Agent answers checked against SQL. `upchirp bench`: local model 10 of 10 correct, p95 16.8 s, $0 (`docs/reports/`); hosted not measured (no key). Threat model in `docs/threat-model.md`. CI has three jobs: Python, UI, platform (Redpanda + Postgres). |
| 6. Live demo | blocked on AWS | Terraform, app image, public-mode limits and deploy script done and tested locally. The account is on AWS's free plan: its organization policy denies EC2 lookups and Bedrock waits on account verification. Next: retry after verification, else Tarik upgrades the plan. |
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

- [ ] Exact Xilinx board model, and whether it runs PYNQ
- [ ] University lab access for noise figure and phase noise
- [ ] AWS account and budget alarm
- [ ] Repo home: Tarik's GitHub or a shared org
