[CmdletBinding()]
param([switch]$SendTest)
$ErrorActionPreference = 'Stop'
$settings = @{}
$configFile = Join-Path (Split-Path $PSScriptRoot -Parent) '.env.oracle'
foreach ($line in Get-Content -LiteralPath $configFile -Encoding UTF8) {
    if ($line -match '^([A-Z_]+)=(.*)$') { $settings[$matches[1]]=$matches[2] }
}
$server=$settings['ORACLE_HOST']
$userName=$settings['ORACLE_USER']
$keyPath=$settings['ORACLE_SSH_KEY_PATH']
if ($server -notmatch '^[a-zA-Z0-9.-]+$' -or $userName -notmatch '^[a-zA-Z0-9_-]+$') { throw 'Invalid local SSH settings.' }
if (!(Test-Path -LiteralPath $keyPath -PathType Leaf)) { throw 'SSH private key not found.' }
$destination=$userName+'@'+$server
$sshArgs=@('-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes',
           '-o','ConnectTimeout=20','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=2','-i',$keyPath)
$remote="tr -d '\r' | sudo -n /opt/gongsi/python3 -"
if ($SendTest) { $remote += ' --send-test' }
$previousEncoding=$OutputEncoding
try {
    $OutputEncoding=[Text.UTF8Encoding]::new($false)
    Get-Content -LiteralPath (Join-Path $PSScriptRoot 'healthcheck.py') -Raw -Encoding UTF8 | & ssh @sshArgs -T $destination $remote
    if ($LASTEXITCODE -ne 0) { throw 'Server health test did not pass. Review the safe status output above.' }
} finally {
    $OutputEncoding=$previousEncoding
}
