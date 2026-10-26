#!/usr/bin/env bash
# One-time: enable HA packages, install climate_seasonal.yaml, restart HA.
# Run from Git Bash on the laptop. Safe to re-run. Every input_boolean in the
# package starts OFF, so nothing touches the thermostats until you enable it.
set -euo pipefail

cd "$(dirname "$0")"
[ -f .env ] && . ./.env   # untracked local settings (HA_HOST etc.)

SSH=${SSH:-ssh}   # on Windows, set SSH to OpenSSH's ssh.exe if Git's ssh can't reach the key agent
HOST=${HA_HOST:?set HA_HOST to the ssh target of the Docker host running Home Assistant, e.g. user@nas}
HA=${HA_CONTAINER:-ix-home-assistant-home-assistant-1}
PKG=ha/packages/climate_seasonal.yaml

if grep -q $'\r' "$PKG"; then echo "$PKG has CRLF line endings, aborting" >&2; exit 1; fi

api() {  # api <method> <path> [json-body]
  local body=${3:-'{}'}
  "$SSH" "$HOST" "curl -s -m 120 -X $1 -H \"Authorization: Bearer \$(cat ~/.ha_token)\" \
    -H 'Content-Type: application/json' http://127.0.0.1:8123$2 -d '$body'"
}

echo "== backing up configuration.yaml and adding packages include"
"$SSH" "$HOST" "docker exec -i $HA sh -s" <<'EOF'
set -e
cd /config
[ -f configuration.yaml.bak-20261019-thermo ] || cp -p configuration.yaml configuration.yaml.bak-20261019-thermo
mkdir -p packages
if ! grep -q '^  packages: !include_dir_named packages' configuration.yaml; then
  if grep -q '^homeassistant:' configuration.yaml; then
    echo "configuration.yaml already has a homeassistant: block; add the packages line by hand" >&2
    exit 1
  fi
  # Write in place so owner/mode stay as they are (BusyBox has no --reference).
  { printf 'homeassistant:\n  packages: !include_dir_named packages\n'; cat configuration.yaml; } > configuration.yaml.new
  cat configuration.yaml.new > configuration.yaml
  rm configuration.yaml.new
fi
head -3 configuration.yaml
EOF

echo "== copying $PKG"
"$SSH" "$HOST" "docker exec -i $HA sh -c 'cat > /config/packages/climate_seasonal.yaml'" < "$PKG"

echo "== checking config"
result=$(api POST /api/config/core/check_config)
echo "$result"
if ! grep -qE '"result": ?"valid"' <<<"$result"; then
  echo "== INVALID: restoring configuration.yaml and removing the package" >&2
  "$SSH" "$HOST" "docker exec $HA sh -c 'cp -p /config/configuration.yaml.bak-20261019-thermo /config/configuration.yaml && rm -f /config/packages/climate_seasonal.yaml'"
  exit 1
fi

echo "== restarting Home Assistant"
api POST /api/services/homeassistant/restart >/dev/null || true
sleep 20
for i in $(seq 1 30); do
  # Entities appear before startup finishes; wait for RUNNING so templates have rendered.
  if api GET /api/config 2>/dev/null | grep -qE '"state": ?"RUNNING"' &&
     api GET /api/states/input_boolean.climate_schedule_enabled 2>/dev/null | grep -q '"entity_id"'; then
    echo "== HA is back and the package is loaded"
    api GET /api/states/input_boolean.climate_schedule_enabled; echo
    exit 0
  fi
  sleep 10
done
echo "== HA did not answer with the new entities within ~5 min; check Settings > System > Logs" >&2
exit 1
