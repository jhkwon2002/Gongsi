#!/usr/bin/env bash
# Root-owned helper: sudo /usr/local/sbin/deploy-gongsi <40-character commit SHA>
set -euo pipefail
[[ $EUID == 0 ]] || { echo "Run as root."; exit 1; }
[[ $# == 1 ]] || { echo "A full commit SHA is required."; exit 1; }
SHA="$1"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "Invalid commit SHA."; exit 1; }
exec 9>/run/lock/gongsi-deploy.lock
flock -n 9 || { echo "Another deployment is active."; exit 1; }
REPO=/opt/gongsi/repository
[[ -d "$REPO/.git" && -f /etc/gongsi/gongsi.env ]] || { echo "Complete bootstrap first."; exit 1; }
if [[ -f /etc/gongsi/github_deploy_key ]]; then
  export GIT_SSH_COMMAND="ssh -i /etc/gongsi/github_deploy_key -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/etc/gongsi/github_known_hosts"
fi
git -C "$REPO" fetch --prune origin main
git -C "$REPO" merge-base --is-ancestor "$SHA" origin/main || { echo "Commit is not on origin/main."; exit 1; }
RELEASE="/opt/gongsi/releases/$SHA"
if [[ ! -d "$RELEASE" ]]; then
  STAGE="$(mktemp -d /opt/gongsi/releases/stage.XXXXXXXX)"
  chmod 0755 "$STAGE"
  git -C "$REPO" archive "$SHA" | tar -x -C "$STAGE"
  printf '%s\n' "$SHA" > "$STAGE/RELEASE"
  chmod -R a+rX "$STAGE"
  mv "$STAGE" "$RELEASE"
fi
runuser -u gongsi -- env PYTHONDONTWRITEBYTECODE=1 bash -c 'cd "$1"; python3 -m unittest discover -s tests -v' bash "$RELEASE"
PREVIOUS="$(readlink -f /opt/gongsi/current || true)"
UNIT_BACKUP="$(mktemp /run/gongsi-unit.XXXXXXXX)"
if [[ -f /etc/systemd/system/gongsi.service ]]; then
  cp /etc/systemd/system/gongsi.service "$UNIT_BACKUP"
fi
# SQLite's backup API provides a consistent snapshot even while the old service runs.
if [[ -f /var/lib/gongsi/store.db ]]; then
  install -d -o root -g root -m 0700 /var/backups/gongsi
  BACKUP="/var/backups/gongsi/store.$(date -u +%Y%m%dT%H%M%SZ).db"
  python3 - "$BACKUP" <<'PY'
import sqlite3, sys
with sqlite3.connect("/var/lib/gongsi/store.db") as source:
    with sqlite3.connect(sys.argv[1]) as destination:
        source.backup(destination)
PY
  chmod 0600 "$BACKUP"
fi
activate() {
  local target="$1"
  ln -s "$target" "/opt/gongsi/current.new.$$"
  mv -Tf "/opt/gongsi/current.new.$$" /opt/gongsi/current
}
CUTOVER=0
SUCCESS=0
cleanup() {
  local result=$?
  trap - EXIT
  if [[ $CUTOVER == 1 && $SUCCESS == 0 ]]; then
    systemctl stop gongsi.service || true
    if [[ -n "$PREVIOUS" && "$PREVIOUS" != /opt/gongsi/current && -d "$PREVIOUS" ]]; then
      activate "$PREVIOUS" || true
      if [[ -s "$UNIT_BACKUP" ]]; then cp "$UNIT_BACKUP" /etc/systemd/system/gongsi.service; fi
      systemctl daemon-reload || true
      systemctl start gongsi.service || true
      echo "Deployment failed; previous code restored. Database kept; backup available."
    else
      echo "Initial deployment failed. Inspect: sudo journalctl -u gongsi -n 50"
    fi
  fi
  rm -f "$UNIT_BACKUP"
  exit "$result"
}
trap cleanup EXIT
if systemctl cat gongsi.service >/dev/null 2>&1; then
  systemctl stop gongsi.service
fi
CUTOVER=1
activate "$RELEASE"
install -o root -g root -m 0644 "$RELEASE/deploy/gongsi.service" /etc/systemd/system/gongsi.service
systemctl daemon-reload
systemctl enable gongsi.service >/dev/null
systemctl start gongsi.service
for ((attempt=0; attempt<30; attempt++)); do
  if systemctl is-active --quiet gongsi.service && [[ -s /run/gongsi/ready ]]; then
    MAINPID="$(systemctl show -p MainPID --value gongsi.service)"
    if [[ "$(cat /run/gongsi/ready)" == "$MAINPID" ]]; then
      SUCCESS=1
      echo "DEPLOYED $SHA; menu ready. Check /status for DART scan health."
      exit 0
    fi
  fi
  sleep 1
done
echo "New service did not become ready."
exit 1

