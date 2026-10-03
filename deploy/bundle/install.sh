#!/bin/bash
# Install Upchirp on this machine with no network. Run as root from the bundle folder:
#   sudo ./install.sh
set -euo pipefail
cd "$(dirname "$0")"
step() { printf '\n== %s\n' "$*"; }
[ "$(id -u)" -eq 0 ] || { echo "Run as root: sudo ./install.sh"; exit 1; }
[ "$(uname -m)" = x86_64 ] || { echo "This bundle is for x86_64 machines."; exit 1; }

step "1/6 Checking the bundle is complete and unchanged"
sha256sum --quiet -c SHA256SUMS || { echo "Checksum mismatch: the bundle is damaged or was changed."; exit 1; }
echo "All files match SHA256SUMS."

step "2/6 Installing k3s (Kubernetes) offline"
# k3s will not start without a default route, which a box with its cable unplugged has
# not got. Give it a placeholder route on a dummy interface that leads nowhere, kept
# across reboots by a small service.
if ! ip route show default | grep -q . && ! ip -6 route show default | grep -q .; then
  echo "No network route found: adding a placeholder route so k3s can start offline."
  cat > /etc/systemd/system/upchirp-offline-route.service <<'UNIT'
[Unit]
Description=Placeholder default route so k3s starts with no network
Before=k3s.service
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'ip route show default | grep -q . || { ip link add upchirp0 type dummy 2>/dev/null; ip addr add 10.254.254.1/24 dev upchirp0 2>/dev/null; ip link set upchirp0 up; ip route add default via 10.254.254.254 dev upchirp0 metric 9999; }'
[Install]
WantedBy=multi-user.target
UNIT
  systemctl daemon-reload
  systemctl enable --now upchirp-offline-route.service
fi
install -m 755 k3s/k3s /usr/local/bin/k3s
mkdir -p /var/lib/rancher/k3s/agent/images
cp k3s/k3s-airgap-images-amd64.tar.zst images/upchirp-images.tar.zst /var/lib/rancher/k3s/agent/images/
# the cluster admin file stays readable by root only (k3s default 600): use sudo k3s kubectl
INSTALL_K3S_SKIP_DOWNLOAD=true sh k3s/install-k3s.sh
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
install -m 755 bin/helm /usr/local/bin/helm

step "3/6 Waiting for Kubernetes to be ready (first start unpacks the images: a few minutes)"
for i in $(seq 1 120); do
  k3s kubectl get nodes 2>/dev/null | grep -q " Ready" && break
  sleep 5
done
k3s kubectl get nodes | grep -q " Ready" || {
  echo "Kubernetes did not become ready in 10 minutes. See: sudo journalctl -u k3s"; exit 1; }
k3s kubectl get nodes

step "4/6 Copying the AI models"
mkdir -p /var/lib/upchirp/ollama
tar -xf models/ollama-models.tar -C /var/lib/upchirp/ollama

step "5/6 Installing Upchirp (up to 20 minutes on a slow disk)"
helm upgrade --install upchirp chart/upchirp-*.tgz --namespace upchirp --create-namespace \
  --wait --timeout 20m

step "6/6 Done"
# the first address that is not the placeholder route's (an offline box may have none)
IP=$(hostname -I | tr ' ' '\n' | grep -v '^10\.254\.254\.' | grep . | head -n 1 || true)
IP=${IP:-127.0.0.1}
cat <<MSG
Upchirp is running.
  Live view and chat:  http://$IP/        (or http://$IP:30080)
  System health:       http://$IP:30300
Check status:  sudo k3s kubectl get pods -n upchirp
MSG
