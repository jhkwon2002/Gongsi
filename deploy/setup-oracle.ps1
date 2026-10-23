[CmdletBinding()]
param([string]$Server,[string]$User,[string]$KeyPath)
$ErrorActionPreference = 'Stop'
$configFile = Join-Path (Split-Path $PSScriptRoot -Parent) '.env.oracle'
$settings = @{}
if (Test-Path -LiteralPath $configFile) {
    foreach ($line in Get-Content -LiteralPath $configFile -Encoding UTF8) {
        if ($line -match '^([A-Z_]+)=(.*)$') { $settings[$matches[1]] = $matches[2] }
    }
}
if (!$Server) { $Server = $settings['ORACLE_HOST'] }
if (!$User) { $User = $settings['ORACLE_USER'] }
if (!$KeyPath) { $KeyPath = $settings['ORACLE_SSH_KEY_PATH'] }
if ($Server -notmatch '^[a-zA-Z0-9.-]+$' -or $User -notmatch '^[a-zA-Z0-9_-]+$') {
    throw 'Set Server and User, or configure .env.oracle.'
}
if (!(Test-Path -LiteralPath $KeyPath -PathType Leaf)) { throw 'SSH private key file not found.' }
$sshArgs = @('-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
             '-o','ConnectTimeout=15','-i',$KeyPath)
$destination = $User + '@' + $Server
$bootstrap = @'
set -euo pipefail
. /etc/os-release
case "$ID" in
  ol)
    [[ "$VERSION_ID" == 9* ]] || { echo "This installer supports Oracle Linux 9."; exit 1; }
    sudo -n dnf install -y git python3.11
    ;;
  ubuntu)
    sudo -n apt-get update
    sudo -n apt-get install -y git python3
    ;;
  *) echo "Unsupported OS. Stop and adapt the installation."; exit 1 ;;
esac
sudo -n install -d -o root -g root -m 0755 /opt/gongsi
if sudo -n test -d /opt/gongsi/repository/.git; then
  ORIGIN="$(sudo -n git -C /opt/gongsi/repository remote get-url origin)"
  [[ "$ORIGIN" == https://github.com/jhkwon2002/Gongsi.git ]] || { echo "Existing repository has another origin."; exit 1; }
  [[ -z "$(sudo -n git -C /opt/gongsi/repository status --porcelain)" ]] || { echo "Existing repository has changes; preserve them before updating."; exit 1; }
  sudo -n git -C /opt/gongsi/repository fetch origin main
else
  if sudo -n test -e /opt/gongsi/repository; then
    echo "Existing non-repository path; refusing to overwrite it."; exit 1
  fi
  sudo -n git clone https://github.com/jhkwon2002/Gongsi.git /opt/gongsi/repository
fi
TARGET="$(sudo -n git -C /opt/gongsi/repository rev-parse origin/main)"
sudo -n git -C /opt/gongsi/repository checkout --detach "$TARGET"
sudo -n bash /opt/gongsi/repository/deploy/bootstrap.sh
echo "SERVER BOOTSTRAP OK"
'@
$previousEncoding = $OutputEncoding
try {
    $OutputEncoding = [Text.UTF8Encoding]::new($false)
    $bootstrap | & ssh @sshArgs -T $destination "tr -d '\r' | bash -s"
    if ($LASTEXITCODE -ne 0) { throw 'Server bootstrap failed. Credentials were not requested.' }
    Write-Host 'Next: enter the two API credentials in the SSH terminal. Input will be hidden.'
    $configure = 'sudo -n /opt/gongsi/python3 /opt/gongsi/repository/deploy/configure.py && TARGET=$(sudo -n git -C /opt/gongsi/repository rev-parse HEAD) && sudo -n /usr/local/sbin/deploy-gongsi "$TARGET"'
    & ssh @sshArgs -t $destination $configure
    if ($LASTEXITCODE -ne 0) { throw 'Configuration or deployment failed. Review the safe error above.' }
    & ssh @sshArgs -T $destination 'sudo -n systemctl is-active gongsi.service; sudo -n readlink -f /opt/gongsi/current'
    if ($LASTEXITCODE -ne 0) { throw 'Post-deployment inspection failed.' }
    Write-Host 'SETUP SUCCESS: Open the Telegram bot and send /start, then select reports.'
    Write-Host 'Use /status to confirm the first DART scan. GitHub automatic deployment is a separate next step.'
} finally {
    $OutputEncoding = $previousEncoding
}
