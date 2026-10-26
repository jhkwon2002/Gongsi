#!/usr/bin/env bash
# Run before package installation on small Oracle Linux / Ubuntu instances.
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run with sudo.'; exit 1; }
exec 9>/run/lock/gongsi-memory.lock
flock -n 9 || { echo 'Another memory preparation is running.'; exit 1; }
for manager in dnf yum rpm apt apt-get; do
  if pgrep -x "$manager" >/dev/null; then
    echo "Package manager $manager is still running. Wait for it to exit before retrying."
    exit 1
  fi
done
RAM_KB=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
SWAP_KB=$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo)
[[ $RAM_KB =~ ^[0-9]+$ && $SWAP_KB =~ ^[0-9]+$ ]] || { echo 'Cannot read memory totals.'; exit 1; }
echo "[memory] RAM: $((RAM_KB / 1024)) MiB; swap: $((SWAP_KB / 1024)) MiB"
SWAP_DIR=/var/lib/gongsi-swap
SWAP_FILE=$SWAP_DIR/swapfile
if (( RAM_KB >= 2097152 || SWAP_KB >= 3145728 )) && [[ ! -e $SWAP_FILE && ! -L $SWAP_FILE ]]; then
  echo 'MEMORY READY: no additional swap needed.'
  exit 0
fi
[[ ! -L $SWAP_DIR && ! -L $SWAP_FILE ]] || { echo 'Refusing a symbolic link at swap location.'; exit 1; }
if [[ -e $SWAP_DIR ]]; then
  [[ -d $SWAP_DIR && $(stat -c '%u:%a' "$SWAP_DIR") == 0:700 ]] || { echo 'Swap directory must be root-owned with mode 700.'; exit 1; }
else
  install -d -o root -g root -m 0700 "$SWAP_DIR"
fi
FS=$(findmnt -n -o FSTYPE -T "$SWAP_DIR")
[[ $FS == xfs || $FS == ext4 ]] || { echo "Swap preparation supports xfs/ext4, detected $FS. No swap file was changed."; exit 1; }
if awk -v p="$SWAP_FILE" '$1 == p && ($2 != "none" || $3 != "swap" || $4 != "defaults,nofail") {bad=1} END {exit !bad}' /etc/fstab; then
  echo 'An incompatible fstab entry exists; review it before continuing.'
  exit 1
fi
if [[ -e $SWAP_FILE ]]; then
  [[ -f $SWAP_FILE && $(stat -c '%u:%a:%h:%s' "$SWAP_FILE") == 0:600:1:3221225472 ]] || { echo 'Existing swap path has unexpected ownership, mode, links or size; refusing to overwrite.'; exit 1; }
  [[ $(blkid -p -s TYPE -o value "$SWAP_FILE") == swap ]] || { echo 'Existing file is not initialized swap; refusing to overwrite.'; exit 1; }
else
  AVAILABLE_KB=$(df -Pk "$SWAP_DIR" | awk 'END {print $4}')
  [[ $AVAILABLE_KB =~ ^[0-9]+$ ]] && (( AVAILABLE_KB >= 4194304 )) || { echo 'At least 4 GiB free disk is needed (3 GiB swap plus 1 GiB reserve).'; exit 1; }
  echo '[memory] Creating an additional 3 GiB swap file. This may take a few minutes.'
  # noclobber creates only a new file, with private permissions from the start.
  (umask 077; set -o noclobber; : > "$SWAP_FILE")
  dd if=/dev/zero of="$SWAP_FILE" bs=1M count=3072 conv=notrunc status=progress
  mkswap "$SWAP_FILE"
fi
if ! swapon --show=NAME --noheadings --raw | awk -v p="$SWAP_FILE" '$0 == p {found=1} END {exit !found}'; then
  swapon "$SWAP_FILE"
fi
SWAP_KB=$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo)
(( SWAP_KB >= 3145728 )) || { echo 'Swap activation did not provide enough capacity. Package installation is blocked.'; exit 1; }
if ! awk -v p="$SWAP_FILE" '$1 == p {found=1} END {exit !found}' /etc/fstab; then
  FSTAB_BACKUP=$(mktemp /etc/fstab.gongsi-backup.XXXXXX)
  cp --preserve=all /etc/fstab "$FSTAB_BACKUP"
  printf '\n%s none swap defaults,nofail 0 0\n' "$SWAP_FILE" >> /etc/fstab
  echo "[memory] Existing fstab backed up to $FSTAB_BACKUP"
fi
systemctl daemon-reload
free -m
echo 'MEMORY READY: additional swap is active and persists after reboot. No packages were installed by this step.'
