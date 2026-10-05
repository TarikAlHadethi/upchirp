# Upchirp: project plan

Started Saturday 3 October 2026. Abdullah's schedule runs in weeks from Monday 5 October, because fabrication and shipping set it. Tarik's half is an ordered list with no dates (see docs/development.md and docs/progress.md).

## What it is

An offline sensor data platform with an AI agent. A 5.8 GHz FMCW radar with angle of arrival is the sensor. It detects, tracks and classifies people, cars and drone-like targets. Framed as a sensor data platform, not counter-drone.

**The finished demo:** the radar faces a courtyard; people, a car and a drone-like target appear on a live range-Doppler and angle map, each tracked and labelled. Someone asks the agent "how many drone-like tracks crossed in the last 10 minutes, and which came closest?" and it answers from the data, with the network cable unplugged. The same view and chat run on a public link in replay mode.

## Decisions locked

- Abdullah's focus is RF, with FPGA as the second track. ASIC tapeout work is cut to fund angle of arrival and a second board revision.
- Tarik's half leads with an agent, evals, safety, an offline bundle, Kubernetes and AWS. Radar DSP stays textbook.
- Every frame source is an adapter publishing one message format to one topic (decision 0003).
- No custom drivers: PYNQ if the board supports it, otherwise Xilinx's DMA proxy driver or u-dma-buf with UIO, owned by Abdullah.

## Tarik: software and platform

Built for outside users, through the install test and a public demo link. The ten steps and their "done when" lines are in docs/development.md.

Alongside: three posts (after steps 3, 7, 8), allowlisted tools and an audit log, a Slack or Telegram webhook, a decision record per tool choice. Stretch: fine-tune the local model on the agent's own tool calls.

## Abdullah: RF hardware, FPGA second

Every block is an original design backed by simulated vs measured numbers.

**RF design:** cascaded budget (Friis); PLL chirp generator (ADF4158/4159 class) with loop filter and phase noise analysis; matching networks in Qucs-S or ADS tuned on the VNA; patch antennas and transitions in openEMS; rev A with 1 TX and 2 RX; rev B with 4 RX plus fixes and a lessons writeup.

**Measurements:** S-parameters vs simulation, receive noise figure (Y-factor), PLL phase noise and chirp linearity, TX P1dB and harmonics, antenna return loss and pattern, channel phase calibration, system range resolution, angle accuracy, noise floor and maximum range vs the radar equation. Python + PyVISA automation for the reports.

**FPGA:** chirp timing, SPI to the PLL, multi-channel ADC interface, CDC with an async FIFO, window and a hand-written pipelined FFT (Xilinx IP only as a baseline), fixed-point analysis with SQNR against Tarik's NumPy reference, AXI streaming, timing closure and resource reports. Stretch: Doppler FFT and CFAR on the FPGA.

**Verification and interfaces:** cocotb, Verilator, assertions, coverage, UVM on at least one block, the SystemRDL register map (generating his Verilog and Tarik's Python register definitions), the DMA path and device tree.

## Abdullah's schedule

| Weeks (ends) | Work | Milestone |
| --- | --- | --- |
| 1 to 5 (8 Nov 2026) | Cascaded budget, PLL and antenna simulation, Vivado basics, parts ordered, coffee-can build starts | Design doc and README published |
| 6 to 11 (20 Dec) | Coffee-can echoes (around week 7); RTL for ADC interface, window and FFT with cocotb; fixed-point analysis starts | First real range plot; verified FFT with SQNR report |
| 12 to 16 (24 Jan 2027) | FPGA in the loop (CDC, timing closure, multi-channel capture), UVM on the FFT, rev A designed and ordered | Real-time FPGA data into Linux |
| 17 to 22 (7 Mar) | Rev A bring-up and characterization, 2-channel angle, PyVISA automation, rev B design starts | Rev A characterization report |
| 23 to 28 (18 Apr) | Rev B fabricated, calibrated and measured; final report | Rev A to rev B writeup and final characterization report |

Handoffs: docs/handoffs.md.

## Cut, and why

| Cut | Why |
| --- | --- |
| C, embedded Linux, drivers on Tarik's side | Not needed: PYNQ or existing DMA paths cover it |
| cocotb and SystemRDL on Tarik's side | Moved to Abdullah |
| Rust | Python covers Tarik's side |
| Go | Python covers it |
| Azure, GCP or a second cloud | One cloud is enough |
| Salesforce-style enterprise hooks | A CRM in a radar project is forced |
| Counter-drone framing | Upchirp is a sensor data platform |
| ArgoCD | No Git remote on an air-gapped box; Helm plus the bundle covers deploys |
| NATS | Redpanda gives the Kafka API |
| vLLM | Needs a GPU; Ollama fits a CPU box |
| Grafana as the radar display | The TypeScript UI replaces it |
| DuckDB | Nothing requires it |
| EKS or cloud Kubernetes | k3s on the edge and one small EC2 server cover it |
| Advanced tracking | Textbook Kalman is enough |
| OpenLane and Tiny Tapeout | Time goes to angle of arrival and rev B |

## Budget (approximate, USD)

| Item | Cost |
| --- | --- |
| Coffee-can reference parts | a few hundred |
| Rev A and rev B PCBs plus RF parts | 300 to 600 |
| NanoVNA and tinySA | 150 to 250 |
| Multi-channel ADC module | 50 to 100 |
| AWS (S3, CPU Spot training, MLflow) | under the budget alarm |
| Public demo server (small EC2) | under the budget alarm and daily spend cap |
| FPGA board and edge box | owned, or a mini PC with 32 GB RAM |

## Risks

- Rev A fails: coffee-can and simulator keep both halves moving; rev B carries the fixes.
- Copied app-note designs: every block gets Abdullah's own calculations and trade-offs.
- No lab access: noise figure and phase noise cannot be measured; secure it in week 1.
- Channel calibration fails: the range and velocity radar still stands.
- Rev B slips: start its design in week 20.
- Local model too slow: 32 GB RAM edge box; evals pick the model.
- GPU quota: not needed; only the fine-tuning stretch would.
- Sim-to-real gap: simulated and real accuracy reported separately, with RAD-DAR conversion cost.
- Public demo abuse and cost: read-only tools, rate limit, daily spend cap, budget alarm.
- Regulations: ISM band at low power under TDRA rules; no drone flight needed thanks to RAD-DAR and the simulator.
