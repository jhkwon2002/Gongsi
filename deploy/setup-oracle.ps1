[CmdletBinding()]
param(
    [string]$Server,[string]$User,[string]$KeyPath,[switch]$DiagnoseOnly,[switch]$PrepareMemoryOnly,[switch]$NoInstall,
    [ValidateRange(5,120)][int]$ConnectTimeoutSeconds = 60,
    [string]$DiagnosticLogPath
)
$ErrorActionPreference = 'Stop'
if ($NoInstall -and $PrepareMemoryOnly) { throw 'Choose -NoInstall or -PrepareMemoryOnly, not both.' }
Write-Host '[1/5] Installer started. Reading local connection settings.'
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
             '-o',('ConnectTimeout=' + $ConnectTimeoutSeconds),'-o','ConnectionAttempts=1',
             '-o','ServerAliveInterval=15','-o','ServerAliveCountMax=2','-i',$KeyPath)
$destination = $User + '@' + $Server
if (!$DiagnosticLogPath) {
    $DiagnosticLogPath = Join-Path (Split-Path $PSScriptRoot -Parent) 'logs\ssh-preflight.log'
}
$logDirectory = Split-Path -Parent $DiagnosticLogPath
if ($logDirectory) { [void][IO.Directory]::CreateDirectory($logDirectory) }
Add-Content -LiteralPath $DiagnosticLogPath -Encoding UTF8 -Value ('=== SSH preflight ' + (Get-Date -Format o) + ' ===')
Write-Host ("[2/5] Checking SSH and sudo. Connection timeout: " + $ConnectTimeoutSeconds + " seconds.")
Write-Host ("SSH diagnostic log (local only): " + $DiagnosticLogPath)
$probe = 'set -e; echo SSH_CONNECTION_OK; id -un; cat /etc/os-release; echo SERVER_LOAD; uptime; if command -v free >/dev/null; then free -m; fi; sudo -n true; echo SUDO_OK'
& ssh @sshArgs -v -E $DiagnosticLogPath -n -T $destination $probe
if ($LASTEXITCODE -ne 0) {
    Write-Host ("SSH failed. Diagnostic log is available at: " + $DiagnosticLogPath)
    throw 'SSH/sudo preflight failed. No package installation or credential changes were attempted.'
}
if ($DiagnoseOnly) {
    Write-Host 'DIAGNOSTIC SUCCESS: SSH and passwordless sudo are working. No installation was performed.'
    return
}
if ($NoInstall) { Write-Host '[3/5] Using existing packages. No package installation or swap changes.' }
else { Write-Host '[3/5] Preparing memory before any package installation.' }
$memoryScript = Join-Path $PSScriptRoot 'prepare-memory.sh'
if (!$NoInstall -and !(Test-Path -LiteralPath $memoryScript -PathType Leaf)) { throw 'Missing deploy/prepare-memory.sh. No packages were installed.' }

$bootstrap = @'
set -euo pipefail
echo "[server] Bootstrap shell started"
. /etc/os-release
echo "[server] Detected OS: $PRETTY_NAME"
PYTHON_READY=0
for candidate in python3 python3.9 python3.11 python3.12 python3.13; do
  if command -v "$candidate" >/dev/null && "$candidate" -c 'import sys, sqlite3, ssl, fcntl; assert sys.version_info >= (3,9)' 2>/dev/null; then
    PYTHON_READY=1
    echo "[server] Existing runtime: $($candidate --version)"
    break
  fi
done
if command -v git >/dev/null && [[ "$PYTHON_READY" == 1 ]]; then
  echo "[server] Existing packages are sufficient; skipping package manager"
elif [[ "${GONGSI_NO_INSTALL:-0}" == 1 ]]; then
  echo "NO-INSTALL STOP: git and Python 3.9+ (sqlite3, ssl, fcntl) must already exist. No packages were installed."
  exit 1
else
  case "$ID" in
    ol)
      [[ "$VERSION_ID" == 9* ]] || { echo "This installer supports Oracle Linux 9."; exit 1; }
      echo "[server] Starting dnf package installation with reduced optional downloads"
      sudo -n dnf --setopt=timeout=30 --setopt=retries=2 --setopt=install_weak_deps=False --setopt=max_parallel_downloads=1 install -y git python3
      ;;
    ubuntu)
      sudo -n apt-get update
      sudo -n apt-get install -y git python3
      ;;
    *) echo "Unsupported OS. Stop and adapt the installation."; exit 1 ;;
  esac
fi
echo "[server] Packages ready. Preparing project checkout"
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
    if (!$NoInstall) {
        $memorySource = Get-Content -LiteralPath $memoryScript -Raw -Encoding UTF8
        $memorySource | & ssh @sshArgs -T $destination "tr -d '\r' | sudo -n bash -s"
        if ($LASTEXITCODE -ne 0) { throw 'Memory preparation failed. Package installation was not started.' }
        if ($PrepareMemoryOnly) {
            Write-Host 'MEMORY PREPARATION SUCCESS: no packages were installed. Run this installer again without -PrepareMemoryOnly to continue.'
            return
        }
        Write-Host '[3/5] Memory prepared. Checking server packages.'
    }
    $remoteBootstrap = "tr -d '\r' | bash -s"
    if ($NoInstall) { $remoteBootstrap = "tr -d '\r' | GONGSI_NO_INSTALL=1 bash -s" }
    $bootstrap | & ssh @sshArgs -T $destination $remoteBootstrap
    if ($LASTEXITCODE -ne 0) { throw 'Server bootstrap failed. Credentials were not requested.' }
    Write-Host '[4/5] Enter the two API credentials in the SSH terminal. Input will be hidden.'
    $configure = 'sudo -n /opt/gongsi/python3 /opt/gongsi/repository/deploy/configure.py && TARGET=$(sudo -n git -C /opt/gongsi/repository rev-parse HEAD) && sudo -n /usr/local/sbin/deploy-gongsi "$TARGET"'
    & ssh @sshArgs -t $destination $configure
    if ($LASTEXITCODE -ne 0) { throw 'Configuration or deployment failed. Review the safe error above.' }
    Write-Host '[5/5] Verifying deployed service.'
    & ssh @sshArgs -n -T $destination 'sudo -n systemctl is-active gongsi.service; sudo -n readlink -f /opt/gongsi/current'
    if ($LASTEXITCODE -ne 0) { throw 'Post-deployment inspection failed.' }
    Write-Host 'SETUP SUCCESS: Open the Telegram bot and send /start, then select reports.'
    Write-Host 'Use /status to confirm the first DART scan. GitHub automatic deployment is a separate next step.'
} finally {
    $OutputEncoding = $previousEncoding
}
