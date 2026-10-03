#!/bin/bash
# Remove Upchirp and k3s from this machine (recordings and the database are deleted too).
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Run as root: sudo ./uninstall.sh"; exit 1; }
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
helm uninstall upchirp -n upchirp 2>/dev/null || true
[ -x /usr/local/bin/k3s-uninstall.sh ] && /usr/local/bin/k3s-uninstall.sh
rm -rf /var/lib/upchirp
echo "Upchirp and k3s removed."
