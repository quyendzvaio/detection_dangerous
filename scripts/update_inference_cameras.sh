#!/usr/bin/env bash
# Detect local cameras and update the GitHub INFERENCE_CAMERAS variable.
#
# Format written: [{"id":N,"key":"cam-N","stream":"rtsps://HOST:8322/tenants/TENANT/cameras/N/main"}]
# The stream URL is the MediaMTX ingress the cloud inference worker will pull from.
#
# Env:
#   GH_REPO      - owner/repo (default: current git remote)
#   GH_TOKEN     - GitHub token with Actions read/write
#   MQTT_HOST    - public hostname of the cloud MediaMTX (default: from gh var MQTT_PUBLIC_HOSTNAME)
#   MQTT_PORT    - RTSPS port (default 8322)
#   TENANT_ID    - tenant id for stream paths (default 1)
#   DRY_RUN=1    - print JSON instead of updating
set -eu

GH_REPO="${GH_REPO:-$(git remote get-url origin 2>/dev/null | sed -E 's#.*[:/]([^/]+/[^/]+)(\.git)?$#\1#')}"
: "${GH_TOKEN:?GH_TOKEN required}"
HOST="${MQTT_HOST:-$(gh api "repos/$GH_REPO/actions/variables/MQTT_PUBLIC_HOSTNAME" --jq .value 2>/dev/null || echo '')}"
: "${HOST:?MQTT_HOST or MQTT_PUBLIC_HOSTNAME var required}"
PORT="${MQTT_PORT:-8322}"
TENANT_ID="${TENANT_ID:-1}"

detect() {
  local i=0
  for dev in /dev/video*; do
    [ -e "$dev" ] || continue
    local name
    name=$(v4l2-ctl --device "$dev" --info 2>/dev/null | sed -n 's/^.*Card type.*: *//p' | head -1)
    printf '{"id":%d,"key":"cam-%d","stream":"rtsps://%s:%s/tenants/%s/cameras/%d/main"}\n' \
      "$i" "$i" "$HOST" "$PORT" "$TENANT_ID" "$i"
    i=$((i + 1))
  done
}

CAMERAS_JSON="[$(detect | paste -sd, -)]"

if [ "$DRY_RUN" = "1" ]; then
  echo "$CAMERAS_JSON"
  exit 0
fi

gh api "repos/$GH_REPO/actions/variables/INFERENCE_CAMERAS" \
  -X PATCH -F value="$CAMERAS_JSON" >/dev/null
echo "INFERENCE_CAMERAS updated: $CAMERAS_JSON"
