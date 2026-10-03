#!/bin/bash
# Runs on the demo server as root: first boot (from Terraform user data) and every deploy
# (through SSM). Installs Docker, fetches the release from S3, and (re)starts the stack.
set -euo pipefail
BUCKET="$1"
REGION="${2:-eu-north-1}"
APP=/opt/upchirp
COMPOSE_VERSION=v5.6.0
COMPOSE_SHA256=733ec76717ceb59052a9609b9dadfb523b2df8eab57a54212872d10a58078ea2

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
printf 'DB_PASSWORD=%s\nAWS_REGION=%s\n' "$(cat /etc/upchirp-db-password)" "$REGION" > "$ENV_FILE"
chmod 600 "$ENV_FILE"

cd "$APP/deploy/demo"
docker compose up -d --build --remove-orphans
docker image prune -f
