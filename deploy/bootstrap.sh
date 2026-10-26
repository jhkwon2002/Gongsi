#!/usr/bin/env bash
# Run once as root on Oracle Linux 9 or Ubuntu 24.04 with existing Python 3.9+; --archive does not require git.
set -euo pipefail
[[ $EUID == 0 ]] || { echo "Run with sudo."; exit 1; }
SOURCE_MODE=git
if [[ $# == 1 && "$1" == --archive ]]; then
  SOURCE_MODE=archive
elif [[ $# != 0 ]]; then
  echo "Usage: bootstrap.sh [--archive]"; exit 1
fi
PYTHON=""
for candidate in python3 python3.9 python3.11 python3.12 python3.13; do
  if command -v "$candidate" >/dev/null && "$candidate" -c 'import sys, sqlite3, ssl, fcntl; assert sys.version_info >= (3,9)' 2>/dev/null; then
    PYTHON="$(command -v "$candidate")"
    break
  fi
done
[[ -n "$PYTHON" ]] || { echo "Python 3.9+ with sqlite3 is required."; exit 1; }
if [[ "$SOURCE_MODE" == git ]]; then command -v git >/dev/null; fi
command -v flock >/dev/null
id gongsi >/dev/null 2>&1 || useradd --system --home-dir /var/lib/gongsi --shell /usr/sbin/nologin gongsi
install -d -o root -g root -m 0755 /opt/gongsi /opt/gongsi/releases
install -d -o root -g root -m 0700 /etc/gongsi
install -d -o gongsi -g gongsi -m 0700 /var/lib/gongsi
# A service-specific path leaves the operating system's Python version unchanged.
ln -sfn "$PYTHON" /opt/gongsi/python3
HERE="$(cd -- "$(dirname -- "$0")" && pwd)"
install -o root -g root -m 0755 "$HERE/deploy.sh" /usr/local/sbin/deploy-gongsi
install -d -o root -g root -m 0755 /usr/local/libexec
install -o root -g root -m 0644 "$HERE/fetch-release.py" /usr/local/libexec/gongsi-fetch-release.py
printf '%s\n' "$SOURCE_MODE" > /etc/gongsi/source-mode
chmod 0600 /etc/gongsi/source-mode
if [[ ! -f /etc/gongsi/gongsi.env ]]; then
  install -o root -g root -m 0600 "$HERE/../.env.example" /etc/gongsi/gongsi.env
fi
echo "Bootstrap ready. Service runtime: $PYTHON"

