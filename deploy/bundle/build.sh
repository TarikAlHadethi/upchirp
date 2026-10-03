#!/bin/bash
# Build the offline bundle (step 7) for one x86_64 edge box. Run where Docker and the
# internet are available; the result installs with the network off.
#
#   deploy/bundle/build.sh            -> dist/upchirp-bundle-<version>/
#
# Contents: k3s and its air-gap images, Helm, every Upchirp image, the Ollama models,
# the Helm chart, install and uninstall scripts, the guide, and SHA256SUMS.
set -euo pipefail
cd "$(dirname "$0")/../.."
export MSYS_NO_PATHCONV=1   # Git Bash on Windows: keep /paths inside docker commands as they are
# REUSE_IMAGES=1 keeps an image archive from an earlier run (it takes the longest to build)

VERSION=$(grep -m1 '^version' deploy/helm/upchirp/Chart.yaml | awk '{print $2}')
K3S_VERSION=${K3S_VERSION:-v1.36.5+k3s1}
HELM_VERSION=${HELM_VERSION:-v4.3.0}
OUT=dist/upchirp-bundle-$VERSION
DOCKER=${DOCKER:-docker}
MODELS=("qwen2.5:7b-instruct" "nomic-embed-text")
IMAGES=$(sed -n '/^images:/,/^[a-z]/p' deploy/helm/upchirp/values.yaml | awk '/^  [a-z]+: /{print $2}')

if [ "${REUSE_IMAGES:-0}" = 1 ] && [ -s "$OUT/images/upchirp-images.tar.zst" ]; then
  find "$OUT" -mindepth 1 -maxdepth 1 ! -name images -exec rm -rf {} +
else
  rm -rf "$OUT"
fi
mkdir -p "$OUT"/{k3s,bin,images,models,chart}

echo "== k3s $K3S_VERSION"
K3S_URL="https://github.com/k3s-io/k3s/releases/download/${K3S_VERSION/+/%2B}"
curl -fsSL -o "$OUT/k3s/k3s" "$K3S_URL/k3s"
curl -fsSL -o "$OUT/k3s/k3s-airgap-images-amd64.tar.zst" "$K3S_URL/k3s-airgap-images-amd64.tar.zst"
# check both against the release's own checksums
SUMS=$(curl -fsSL "$K3S_URL/sha256sum-amd64.txt")
for f in k3s k3s-airgap-images-amd64.tar.zst; do
  want=$(echo "$SUMS" | awk -v f="$f" '$2 == f {print $1}')
  [ -n "$want" ] || { echo "no checksum for $f in the k3s release"; exit 1; }
  echo "$want  $OUT/k3s/$f" | sha256sum -c --quiet - || { echo "checksum mismatch: $f"; exit 1; }
done
# the installer script from the same release tag, not whatever get.k3s.io serves today
curl -fsSL -o "$OUT/k3s/install-k3s.sh" \
  "https://raw.githubusercontent.com/k3s-io/k3s/$K3S_VERSION/install.sh"

echo "== helm $HELM_VERSION"
HELM_TGZ="helm-$HELM_VERSION-linux-amd64.tar.gz"
curl -fsSL -o "$OUT/$HELM_TGZ" "https://get.helm.sh/$HELM_TGZ"
echo "$(curl -fsSL "https://get.helm.sh/$HELM_TGZ.sha256sum" | awk '{print $1}')  $OUT/$HELM_TGZ" \
  | sha256sum -c --quiet - || { echo "checksum mismatch: $HELM_TGZ"; exit 1; }
tar -xzf "$OUT/$HELM_TGZ" -C "$OUT/bin" --strip-components=1 linux-amd64/helm
rm "$OUT/$HELM_TGZ"

echo "== images"
if [ "${REUSE_IMAGES:-0}" = 1 ] && [ -s "$OUT/images/upchirp-images.tar.zst" ]; then
  echo "reusing $OUT/images/upchirp-images.tar.zst"
else
"$DOCKER" build --platform linux/amd64 -t "upchirp-app:$VERSION" .
# slim images built from deploy/images (CPU-only Ollama, Postgres with Timescale and pgvector)
for img in $IMAGES; do
  name=${img##*/}
  case "$name" in
    upchirp-ollama-cpu:*) "$DOCKER" build --platform linux/amd64 -t "$name" deploy/images/ollama-cpu ;;
    upchirp-postgres:*) "$DOCKER" build --platform linux/amd64 -t "$name" deploy/images/postgres ;;
  esac
done
for img in $IMAGES; do
  case "$img" in *upchirp-*) continue ;; esac
  "$DOCKER" pull --platform linux/amd64 -q "$img"
done
# k3s imports every archive in its images folder at start; zstd keeps the bundle smaller
"$DOCKER" save $IMAGES \
  | "$DOCKER" run --rm -i alpine:3.20 sh -c "apk add -q zstd >/dev/null && zstd -T0 -6 -q" \
  > "$OUT/images/upchirp-images.tar.zst"
fi

echo "== models ${MODELS[*]}"
"$DOCKER" exec upchirp-ollama sh -c "$(printf 'ollama pull %s && ' "${MODELS[@]}") true" >/dev/null
"$DOCKER" run --rm -v upchirp-ollama:/src:ro alpine:3.20 tar -C /src -cf - models \
  > "$OUT/models/ollama-models.tar"

echo "== chart, scripts, guide"
"${HELM:-helm}" package deploy/helm/upchirp -d "$OUT/chart" >/dev/null
cp deploy/bundle/install.sh deploy/bundle/uninstall.sh "$OUT/"
cp docs/install.md "$OUT/INSTALL.md"
chmod +x "$OUT"/*.sh "$OUT/k3s/k3s" "$OUT/k3s/install-k3s.sh" "$OUT/bin/helm"

(cd "$OUT" && find . -type f ! -name SHA256SUMS | sort | xargs sha256sum > SHA256SUMS)
du -sh "$OUT"
echo "Bundle ready: $OUT"
# SHA256SUMS inside the bundle catches damage, not a deliberate change to the whole folder.
# Publish this line somewhere else (the release notes) so an installer can check the list too.
echo "Publish with the release: $(sha256sum "$OUT/SHA256SUMS" | awk '{print $1}')  SHA256SUMS"
