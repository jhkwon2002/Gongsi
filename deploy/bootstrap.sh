#!/usr/bin/env bash
# Run once as root from a reviewed checkout on Oracle Ubuntu 24.04.
set -euo pipefail
if [[ $EUID != 0 ]]; then echo "Run with sudo."; exit 1; fi
python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
command -v git >/dev/null
command -v flock >/dev/null
id gongsi >/dev/null 2>&1 || useradd --system --home-dir /var/lib/gongsi --shell /usr/sbin/nologin gongsi
install -d -o root -g root -m 0755 /opt/gongsi /opt/gongsi/releases
install -d -o root -g root -m 0700 /etc/gongsi
install -d -o gongsi -g gongsi -m 0700 /var/lib/gongsi
HERE="$(cd -- "$(dirname -- "$0")" && pwd)"
install -o root -g root -m 0755 "$HERE/deploy.sh" /usr/local/sbin/deploy-gongsi
if [[ ! -f /etc/gongsi/gongsi.env ]]; then
  install -o root -g root -m 0600 "$HERE/../.env.example" /etc/gongsi/gongsi.env
fi
echo "Bootstrap ready. Configure repository, Oracle-only credentials and SSH, then deploy a commit."

