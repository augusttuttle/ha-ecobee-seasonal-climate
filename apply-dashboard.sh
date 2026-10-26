#!/usr/bin/env bash
# Add the climate cards/view to the home-hub dashboard (idempotent).
# Save the dashboard first so --restore can put it back (see README).
#   ./apply-dashboard.sh                       apply
#   ./apply-dashboard.sh --restore <file.json> put a saved dashboard back verbatim
set -euo pipefail

cd "$(dirname "$0")"
[ -f .env ] && . ./.env   # untracked local settings (HA_HOST etc.)

SSH=${SSH:-ssh}   # on Windows, set SSH to OpenSSH's ssh.exe if Git's ssh can't reach the key agent
HOST=${HA_HOST:?set HA_HOST to the ssh target of the Docker host running Home Assistant, e.g. user@nas}
HA=${HA_CONTAINER:-ix-home-assistant-home-assistant-1}
PY=ha/dashboard/apply_climate_dashboard.py


push() {  # push <local> <container-path>
  "$SSH" "$HOST" "docker exec -i $HA sh -c 'cat > $2'" < "$1"
}

push "$PY" /tmp/apply_climate_dashboard.py
if [ "${1:-}" = "--restore" ]; then
  push "$2" /tmp/dashboard_restore.json
  "$SSH" "$HOST" "docker exec -e HA_TOKEN=\"\$(cat ~/.ha_token)\" $HA python /tmp/apply_climate_dashboard.py --restore /tmp/dashboard_restore.json"
else
  "$SSH" "$HOST" "docker exec -e HA_TOKEN=\"\$(cat ~/.ha_token)\" $HA python /tmp/apply_climate_dashboard.py"
fi
