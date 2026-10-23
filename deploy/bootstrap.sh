#!/usr/bin/env bash
# Run once as root on Oracle Linux 9 or Ubuntu 24.04 after installing git and Python 3.11+.
set -euo pipefail
[[ $EUID == 0 ]] || { echo "Run with sudo."; exit 1; }
PYTHON=""
for candidate in python3.11 python3.12 python3.13 python3; do
  if command -v "$candidate" >/dev/null && "$candidate" -c 'import sys, sqlite3; assert sys.version_info >= (3,11)' 2>/dev/null; then
    PYTHON="$(command -v "$candidate")"
    break
  fi
done
[[ -n "$PYTHON" ]] || { echo "Python 3.11+ with sqlite3 is required."; exit 1; }
command -v git >/dev/null
command -v flock >/dev/null
id gongsi >/dev/null 2>&1 || useradd --system --home-dir /var/lib/gongsi --shell /usr/sbin/nologin gongsi
install -d -o root -g root -m 0755 /opt/gongsi /opt/gongsi/releases
install -d -o root -g root -m 0700 /etc/gongsi
install -d -o gongsi -g gongsi -m 0700 /var/lib/gongsi
# A service-specific path leaves the operating system's Python version unchanged.
ln -sfn "$PYTHON" /opt/gongsi/python3
HERE="$(cd -- "$(dirname -- "$0")" && pwd)"
install -o root -g root -m 0755 "$HERE/deploy.sh" /usr/local/sbin/deploy-gongsi
if [[ ! -f /etc/gongsi/gongsi.env ]]; then
  install -o root -g root -m 0600 "$HERE/../.env.example" /etc/gongsi/gongsi.env
fi
echo "Bootstrap ready. Service runtime: $PYTHON"

