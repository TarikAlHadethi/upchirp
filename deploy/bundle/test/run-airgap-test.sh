#!/bin/bash
# Air-gap install test (step 7 "done when"): a fresh Ubuntu machine whose only network is
# Docker's --internal network, so nothing can reach the internet. Install the bundle there
# and check the live view, the API and the agent answer.
set -euo pipefail
cd "$(dirname "$0")/../../.."
DOCKER=${DOCKER:-docker}
BUNDLE=${1:?usage: run-airgap-test.sh <bundle folder>}
BUNDLE_ABS=$(cd "$BUNDLE" && pwd -W 2>/dev/null || pwd)
NAME=upchirp-airgap-test

"$DOCKER" rm -f "$NAME" >/dev/null 2>&1 || true
"$DOCKER" volume rm "$NAME-var" >/dev/null 2>&1 || true
"$DOCKER" network inspect upchirp-airgap >/dev/null 2>&1 || "$DOCKER" network create --internal upchirp-airgap
"$DOCKER" build -q -t upchirp-testvm deploy/bundle/test

"$DOCKER" run -d --name "$NAME" --hostname edgebox --network upchirp-airgap \
  --privileged --security-opt seccomp=unconfined --cgroupns=private \
  --tmpfs /tmp --tmpfs /run --tmpfs /run/lock -v "$NAME-var:/var" \
  -v "$BUNDLE_ABS:/bundle:ro" upchirp-testvm >/dev/null
sleep 5

echo "== Is the internet really unreachable?"
if "$DOCKER" exec "$NAME" curl -s -m 8 -o /dev/null https://github.com; then
  echo "FAIL: the test machine can reach the internet"; exit 1
fi
echo "Yes: github.com is unreachable from the test machine."

echo "== Installing"
"$DOCKER" exec "$NAME" bash -c "cp -r /bundle /root/bundle && cd /root/bundle && ./install.sh"

echo "== Checking"
"$DOCKER" exec "$NAME" k3s kubectl get pods -n upchirp
"$DOCKER" exec "$NAME" bash -c '
  for i in $(seq 1 60); do
    curl -sf localhost:30080/api/summary | grep -q total_tracks && break; sleep 5; done
  echo "API summary: $(curl -sf localhost:30080/api/summary)"
  curl -sf localhost:30080/ | grep -q "Upchirp live view" && echo "UI: served"
  curl -sf localhost/api/health && echo " (through ingress on port 80)"
  curl -sf localhost:30300/api/health && echo " (Grafana)"
  echo "Agent: $(curl -sf -m 300 -X POST localhost:30080/api/ask -H "content-type: application/json" \
    -d "{\"question\": \"How many drone-like tracks crossed in the last 10 minutes, and which came closest?\"}")"
'
