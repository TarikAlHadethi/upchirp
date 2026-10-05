# Upchirp: development guide

Offline sensor data platform with an AI agent. A 5.8 GHz FMCW radar with angle of arrival is the sensor. It detects, tracks and classifies people, cars and drone-like targets, and anyone can question the agent about what it saw.

Framing: a sensor data platform, not counter-drone. Never describe it as a defense or counter-UAS product.

## People and ownership

- **Tarik** (software and platform). Owns `src/upchirp/` (sim, sources, dsp, api, agent), `evals/`, `tests/`, `ui/`, `ml/`, `deploy/`, `infra/`.
- **Abdullah** (RF hardware, FPGA second). Owns everything under `hardware/`, `rtl/`, `verification/`, `regmap/`, `characterization/`.

Each person edits only their own folders. Abdullah's interfaces (frame format, register map) are contracts: change them only through a decision record both agree on.

## How the system fits together

```
radar front end -> Xilinx FPGA (window + range FFT) -> Ethernet -> edge box (k3s)
                                                                   |
frame sources (all publish the same Frame message to one topic):   |
  sim | replay | soundcard (coffee-can) | fpga                     v
                                                     Redpanda topic "frames"
                                                                   |
               dsp (Doppler FFT, CFAR) -> tracker (2D Kalman) -> classifier (ONNX)
                                                                   |
                         PostgreSQL + TimescaleDB + pgvector (detections, tracks, audit, RAG)
                                                                   |
                    FastAPI (REST + WebSockets) -> TypeScript UI, webhook, MCP server
                                                                   |
                                 LangGraph agent (hosted model / Bedrock / Ollama)
```

The pipeline must never know which frame source it is reading. Swapping sources is a config change. See `docs/architecture.md` for the Frame message.

## Stack (Tarik's half)

Python 3.12 is the main language; TypeScript only for `ui/`. No C, no Rust on Tarik's side.

| Area | Tool |
| --- | --- |
| Simulator, DSP, tracking | NumPy, SciPy (textbook CFAR and Kalman on purpose) |
| Recordings | Parquet |
| Streaming | Redpanda (Kafka API) |
| Storage | PostgreSQL + TimescaleDB + pgvector (one database) |
| API | FastAPI, WebSockets |
| UI | TypeScript, thin; live range-Doppler heatmap, angle map, tracks, agent chat |
| Agent | MCP server (Python SDK) + LangGraph via langchain-mcp-adapters |
| Models | hosted API in dev, Amazon Bedrock on the demo server, Ollama offline |
| Evals | pytest + custom scorers, in CI |
| Observability | OpenTelemetry, Prometheus, Grafana (system health only) |
| Edge deploy | k3s, Helm, offline bundle |
| Cloud | Terraform + AWS (S3, IAM, Budgets, EC2, Spot) |
| ML | PyTorch, MLflow, ONNX Runtime; RAD-DAR dataset |

Deliberately cut (do not add without a decision record): C, Rust, Go, NATS, ArgoCD, vLLM, DuckDB, EKS, Azure, GCP, Kafka clusters, advanced trackers.

## Build order (Tarik)

Work in this order. A step is finished only when its "done when" holds. Check `docs/progress.md` for the current step.

1. **Simulator and replay.** Done when one command replays a scene (people, a car, a drone-like target, with angle) and its ground truth is saved.
2. **Reference DSP.** Range and Doppler FFTs, CFAR, 2D Kalman tracker. Done when detections and tracks are scored against ground truth.
3. **The agent.** MCP server; LangGraph agent through langchain-mcp-adapters; chirp config tool marked destructive so it needs a human yes through LangGraph's interrupt; two evals. Done when it answers the drone question correctly and a planted wrong tool output fails the eval. Repo goes public here with a 60-second video.
4. **Platform.** Redpanda, Postgres with Timescale and pgvector, FastAPI, the TypeScript UI, OpenTelemetry. Done when the live view and the chat run on a replay.
5. **Full evals in CI.** Ground truth scoring, agent answers checked against SQL, planted faults, prompt injection hidden in RAG docs and in recording metadata, cost and p95 latency per answer for hosted vs local, a one-page threat model. Done when a regression fails the build.
6. **Live demo.** Terraform for S3, least privilege IAM and the budget alarm, then one small EC2 server running the same services in replay mode. Read-only tools, a rate limit, a daily spend cap, model via Bedrock with the instance role (no API key on the box). Done when anyone can open the link.
7. **Offline bundle.** k3s, Helm, Ollama, hosted vs local evals, Prometheus and Grafana, air-gap images, checksums, install guide. Done when it installs on a fresh machine with the network off.
8. **Install test.** Three people install from the guide offline: a CS classmate, someone non-technical, a lecturer. Note where each gets stuck, fix, time before and after. Guide gets an operator section for a non-engineer. Done when the write-up is posted.
9. **Classifier.** Train on RAD-DAR (downloaded by script, never committed), converted to our radar's grid, tested on Abdullah's recordings. PyTorch + MLflow on a CPU Spot instance. ONNX into the bundle. Done when simulated and real accuracy are reported separately, with the conversion cost.
10. **Real hardware.** Sound card adapter for coffee-can recordings, then the FPGA adapter, then every eval rerun on real data. Waits on Abdullah.

## Working together

Tarik and Abdullah work on one repo, `main`, and each owns the folders above. The other side only sees work that is committed and pushed, so when a task is finished and `make test` and `make evals` pass (or the owner's equivalent checks), commit and push it right away, in small commits with one concern each.

Shared files (`docs/`, `README.md`, `Makefile`, `pyproject.toml`, `.github/`, `scripts/`) can be edited by both. Keep those edits small and push them quickly, to avoid conflicts. Never edit the other person's folders: ask them for the change instead.

## Rules for working in this repo

- Ground truth first. Every simulated scene saves its ground truth; every feature that can be scored gets an eval.
- Agent safety is not optional: tools are allowlisted, destructive tools need a human yes, every agent action goes in the audit log.
- Public demo tools are read-only. Never expose a hardware-changing tool on the public server.
- No secrets in the repo. AWS access comes from roles. `.env` files are git-ignored.
- Never commit datasets or model weights. `data/` and `models/` are git-ignored; download by script.
- Every tool choice gets a short decision record in `docs/decisions/` (copy `0000-template.md`).
- Small commits, one concern each. Run `make test` and `make evals` before committing.
- Writing style in docs: plain words, short sentences, no en dashes or em dashes; write ranges with "to".

## Commands

```
make setup      # create venv, install deps
make sim        # generate a scene with ground truth
make replay     # replay a recording through the pipeline (saves detections and tracks)
make score      # score the latest replay against ground truth
make up         # start Redpanda, Postgres and Ollama (compose.yaml), pull models, index docs
make ui         # build the TypeScript live view
make live       # processor, writer, API and a looping replay; UI at http://127.0.0.1:8000
make down       # stop the containers
upchirp ask "..."  # ask the agent from the terminal
upchirp mcp     # run the MCP server for any MCP client
upchirp bench   # agent latency, tokens, cost and correctness -> docs/reports/
python scripts/download_raddar.py && python ml/train.py   # step 9 classifier (needs kaggle.json)
deploy/bundle/build.sh            # offline bundle -> dist/upchirp-bundle-<version>/
deploy/bundle/test/run-airgap-test.sh dist/upchirp-bundle-<version>   # install on a fresh offline Ubuntu
make test       # unit tests
make evals      # eval suite (fails on regression)
make lint       # ruff + mypy
```

`sim` and `replay` are real since step 1; keep the Makefile in sync as targets change. On Windows the Makefile uses `py -3.12` and `.venv/Scripts`.
