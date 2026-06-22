#!/usr/bin/env sh
set -eu

port="${PORT:-${1:-8000}}"
protocol="${PROTOCOL:-${2:-http2}}"
target_url="${TUNNEL_TARGET_URL:-http://host.docker.internal:${port}}"

case "$protocol" in
  http2|quic) ;;
  *)
    printf '%s\n' "Protocol must be either 'http2' or 'quic'." >&2
    exit 2
    ;;
esac

docker run --rm cloudflare/cloudflared:latest tunnel --no-autoupdate --protocol "$protocol" --url "$target_url"