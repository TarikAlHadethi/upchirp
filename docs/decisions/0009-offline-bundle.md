# 0009: Offline bundle as a folder: k3s air-gap images, a Helm chart and a checked install script

- Date: 2026-10-03
- Owner: Tarik
- Status: accepted

## Context

The edge box must install from a USB drive with the network off (step 7), and the install test (step 8) includes a non-technical person.

## Decision

One folder: the k3s binary and its official air-gap images, Helm, every Upchirp image as one zstd archive in the folder k3s imports at start, the Ollama model files (copied to a host folder the Ollama pod mounts), the Helm chart, `install.sh`, `uninstall.sh`, the guide, and `SHA256SUMS`. The installer checks every checksum before touching the machine, then runs six numbered steps. Prometheus and Grafana come with one system-health dashboard.

## Alternatives considered

| Option | Why not |
| --- | --- |
| A private registry on the box | One more service to install and secure, for one machine |
| Docker Compose instead of k3s | Simpler, but the plan targets Kubernetes skills and Helm |
| Upstream Prometheus and Grafana charts | Many more images and settings than one dashboard needs |
| Pulling models on first start | Breaks the offline requirement |

## Consequences

The first bundle was 10 GB, mostly the official Ollama image (9.4 GB, GPU libraries) and the TimescaleDB HA image (4.4 GB). Slim images built in `deploy/images/` (CPU-only Ollama, 0.2 GB; Postgres 16 with TimescaleDB and pgvector, 1.7 GB) bring it to 6.1 GB, of which the models are 4.7 GB. Retested offline with the slim images: all services up, agent correct. x86_64 only for now. Upgrades are a new bundle and `helm upgrade`.
