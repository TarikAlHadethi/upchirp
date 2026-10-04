#!/bin/bash
# Runs on the demo server as root: first boot (from Terraform user data) and every deploy
# (through SSM). Installs Docker, fetches the release from S3, and (re)starts the stack.
set -euo pipefail
BUCKET="$1"
REGION="${2:-eu-north-1}"
PROVIDER="${3:-anthropic}"          # or bedrock (decision 0015)
KEY_PARAM="${4:-/upchirp/anthropic-api-key}"
APP=/opt/upchirp
COMPOSE_VERSION=v5.6.0
COMPOSE_SHA256=733ec76717ceb59052a9609b9dadfb523b2df8eab57a54212872d10a58078ea2
BUILDX_VERSION=v0.37.2
BUILDX_SHA256=efa38cb7aa7db2dbb9ad049b00b0a9737f66f033626177b5a4e845184ad7ab29

if ! command -v docker >/dev/null; then
  dnf install -y docker
  systemctl enable --now docker
  mkdir -p /usr/libexec/docker/cli-plugins
  curl -fsSL -o /usr/libexec/docker/cli-plugins/docker-compose \
    "https://github.com/docker/compose/releases/download/$COMPOSE_VERSION/docker-compose-linux-aarch64"
  echo "$COMPOSE_SHA256  /usr/libexec/docker/cli-plugins/docker-compose" | sha256sum -c -
  chmod +x /usr/libexec/docker/cli-plugins/docker-compose
  # 2 GB of RAM: add 2 GB of swap for image builds and the database
  if [ ! -f /swapfile ]; then
    dd if=/dev/zero of=/swapfile bs=1M count=2048 && chmod 600 /swapfile
    mkswap /swapfile && swapon /swapfile && echo "/swapfile none swap sw 0 0" >> /etc/fstab
  fi
fi

# Compose builds need buildx 0.17 or later, newer than Amazon Linux's docker package has
if ! docker buildx version 2>/dev/null | grep -q "$BUILDX_VERSION"; then
  mkdir -p /usr/libexec/docker/cli-plugins
  curl -fsSL -o /usr/libexec/docker/cli-plugins/docker-buildx \
    "https://github.com/docker/buildx/releases/download/$BUILDX_VERSION/buildx-$BUILDX_VERSION.linux-arm64"
  echo "$BUILDX_SHA256  /usr/libexec/docker/cli-plugins/docker-buildx" | sha256sum -c -
  chmod +x /usr/libexec/docker/cli-plugins/docker-buildx
fi

# unpack into a fresh folder, then swap it in, so files deleted in the repo are gone here too
aws s3 cp --region "$REGION" "s3://$BUCKET/releases/upchirp.tar.gz" /tmp/upchirp.tar.gz
rm -rf "$APP.new" && mkdir -p "$APP.new"
tar -xzf /tmp/upchirp.tar.gz -C "$APP.new"
rm -rf "$APP.old"
if [ -d "$APP" ]; then mv "$APP" "$APP.old"; fi
mv "$APP.new" "$APP"

ENV_FILE="$APP/deploy/demo/.env"
if [ ! -f /etc/upchirp-db-password ]; then
  head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' > /etc/upchirp-db-password
  chmod 600 /etc/upchirp-db-password
fi
umask 077  # the env file holds the database password and maybe the API key: root only
printf 'DB_PASSWORD=%s\nAWS_REGION=%s\nMODEL_PROVIDER=%s\n' \
  "$(cat /etc/upchirp-db-password)" "$REGION" "$PROVIDER" > "$ENV_FILE"
if [ "$PROVIDER" = anthropic ]; then
  # read with the server's role at deploy time; never stored in the repo or the release
  printf 'ANTHROPIC_API_KEY=%s\n' "$(aws ssm get-parameter --region "$REGION" \
    --name "$KEY_PARAM" --with-decryption --query Parameter.Value --output text)" >> "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"

cd "$APP/deploy/demo"
docker compose up -d --build --remove-orphans
docker image prune -f
