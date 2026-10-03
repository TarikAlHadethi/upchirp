# Installing Upchirp offline

This guide installs Upchirp on one computer with no internet connection. It takes about 20 minutes, most of it waiting.

## What you need

- A computer with an x86_64 (Intel or AMD) processor, 8 GB of memory or more (16 GB or more is better for the AI model), and 60 GB of free disk space.
- Linux with systemd. Tested on a fresh Ubuntu 24.04 system with no internet access (3 October 2026, in a container standing in for the machine); a real machine test comes in step 8.
- The bundle folder `upchirp-bundle-<version>` on a USB drive or disk.
- An account that can use `sudo`.

You do not need the internet, Docker, or any other software.

## Install

1. Copy the bundle folder to the computer, for example to your home folder.
2. Open a terminal in that folder.
3. Run:

   ```
   sudo ./install.sh
   ```

The installer goes through six steps and prints each one. It checks every file in the bundle against `SHA256SUMS` first, and stops if anything is damaged or was changed. Do not skip that check. To be sure the list itself is genuine, compare `sha256sum SHA256SUMS` with the value published in the release notes.

When it finishes it prints two addresses:

- **Live view and chat:** `http://<computer address>/`. A top-down map of what the radar sees, the range and speed picture, a track list, and a chat box for questions.
- **System health:** `http://<computer address>:30300`. Graphs showing whether the system is keeping up.

Open them in a browser on the same computer or on any computer on the same network.

## For operators (no engineering background needed)

**Is it working?** Open the live view. The badge at the top right should say **live** in green, and dots should move on the map. Until real radar hardware is connected, the system plays back simulated recordings in a loop: two people, a car and a drone-like target.

**Asking questions.** Type into the chat box, for example "How many drone-like tracks crossed in the last 10 minutes, and which came closest?" Answers come only from what the radar recorded and take about 15 to 30 seconds. The system never changes radar settings unless you ask it to, and even then it asks you to approve first.

**Something looks wrong.**

| What you see | What to do |
| --- | --- |
| Badge says **offline** | Wait one minute; the system may still be starting. Then reload the page. |
| Map stays empty for several minutes | Restart the computer. Upchirp starts by itself. |
| Chat says something went wrong | Ask again in a minute; the AI model may still be loading after a restart. |
| Pages do not open at all | Check the computer is on and on the same network. Then ask an engineer to run `sudo k3s kubectl get pods -n upchirp`. |

**Turning it off.** Shut the computer down normally. Upchirp starts again on its own when the computer starts.

## For engineers

- Status: `sudo k3s kubectl get pods -n upchirp`. Every pod should be `Running`, and `upchirp-seed` should be `Completed`.
- Logs: `sudo k3s kubectl logs -n upchirp deploy/upchirp-api` (or `upchirp-process`, `upchirp-write`, `upchirp-source`, `upchirp-alerts`, `ollama`), and `statefulset/db` or `statefulset/redpanda`.
- Remove everything: `sudo ./uninstall.sh`. This deletes the recordings and the database too.
- Building a new bundle (needs the internet): `deploy/bundle/build.sh` in the repository.

What runs: k3s (a small Kubernetes) with Redpanda, PostgreSQL (TimescaleDB and pgvector), Ollama with the local models, the five Upchirp services (source, processor, writer, alerts, API with the UI), Prometheus and Grafana. All images ship in the bundle; nothing is downloaded at install time or later.
