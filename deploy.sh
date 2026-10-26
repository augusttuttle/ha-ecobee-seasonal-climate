#!/usr/bin/env bash
# Push ha/packages/*.yaml into Home Assistant, validate, then reload.
# Run from Git Bash on the laptop. On a failed config check the previous
# live copy is put back and nothing is reloaded.
set -euo pipefail

cd "$(dirname "$0")"
[ -f .env ] && . ./.env   # untracked local settings (HA_HOST etc.)

SSH=${SSH:-ssh}   # on Windows, set SSH to OpenSSH's ssh.exe if Git's ssh can't reach the key agent
HOST=${HA_HOST:?set HA_HOST to the ssh target of the Docker host running Home Assistant, e.g. user@nas}
HA=${HA_CONTAINER:-ix-home-assistant-home-assistant-1}


api() {  # api <path> [json-body]
  local body=${2:-'{}'}
  "$SSH" "$HOST" "curl -s -m 120 -X POST -H \"Authorization: Bearer \$(cat ~/.ha_token)\" \
    -H 'Content-Type: application/json' http://127.0.0.1:8123$1 -d '$body'"
}

files=(ha/packages/*.yaml)
for f in "${files[@]}"; do
  name=$(basename "$f")
  if grep -q $'\r' "$f"; then echo "$f has CRLF line endings, aborting" >&2; exit 1; fi
  "$SSH" "$HOST" "docker exec $HA sh -c 'mkdir -p /config/packages && \
    if [ -f /config/packages/$name ]; then cp /config/packages/$name /config/packages/$name.prev; fi'"
  "$SSH" "$HOST" "docker exec -i $HA sh -c 'cat > /config/packages/$name'" < "$f"
  echo "copied $name"
done

result=$(api /api/config/core/check_config)
echo "check_config: $result"
if ! grep -qE '"result": ?"valid"' <<<"$result"; then
  for f in "${files[@]}"; do
    name=$(basename "$f")
    "$SSH" "$HOST" "docker exec $HA sh -c 'if [ -f /config/packages/$name.prev ]; then mv /config/packages/$name.prev /config/packages/$name; else rm -f /config/packages/$name; fi'"
  done
  echo "config invalid: previous files restored, nothing reloaded" >&2
  exit 1
fi

since=$("$SSH" "$HOST" "date '+%Y-%m-%d %H:%M:%S'")
api /api/services/homeassistant/reload_all >/dev/null
echo "reloaded"

# check_config passes things that later fail automation validation (a YAML key
# like `off:` parses as false), and HA then silently disables that automation.
sleep 5
bad=$("$SSH" "$HOST" "docker exec -i $HA sh -s '$since'" <<'EOF'
awk -v s="$1" 'substr($0,1,19) >= s' /config/home-assistant.log \
  | grep -E 'could not be validated|Invalid config for|Error loading' | cut -c1-300
exit 0
EOF
)
if [ -n "$bad" ]; then
  echo "WARNING: errors logged after reload (an automation may now be disabled):" >&2
  echo "$bad" >&2
  exit 2
fi
echo "no validation errors after reload"
