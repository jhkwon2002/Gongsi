[CmdletBinding()]
param([switch]$SendTest)
$ErrorActionPreference='Stop'
$settings=@{}
foreach($line in Get-Content -LiteralPath (Join-Path (Split-Path $PSScriptRoot -Parent) '.env.oracle') -Encoding UTF8) {
    if($line -match '^([A-Z_]+)=(.*)$') { $settings[$matches[1]]=$matches[2] }
}
$server=$settings['ORACLE_HOST']
$userName=$settings['ORACLE_USER']
$keyPath=$settings['ORACLE_SSH_KEY_PATH']
if($server -notmatch '^[a-zA-Z0-9.-]+$' -or $userName -notmatch '^[a-zA-Z0-9_-]+$') { throw 'Invalid local SSH settings.' }
if(!(Test-Path -LiteralPath $keyPath -PathType Leaf)) { throw 'SSH private key not found.' }
$destination=$userName+'@'+$server
$sshArgs=@('-o','BatchMode=yes','-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes',
           '-o','ConnectTimeout=20','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=2','-i',$keyPath)
$assets=@{
    '/usr/local/libexec/gongsi-autodeploy.py'=([IO.File]::ReadAllText((Join-Path $PSScriptRoot 'autodeploy.py'), [Text.Encoding]::UTF8))
    '/etc/systemd/system/gongsi-update.service'=([IO.File]::ReadAllText((Join-Path $PSScriptRoot 'gongsi-update.service'), [Text.Encoding]::UTF8))
    '/etc/systemd/system/gongsi-update.timer'=([IO.File]::ReadAllText((Join-Path $PSScriptRoot 'gongsi-update.timer'), [Text.Encoding]::UTF8))
}
$encoded=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($assets|ConvertTo-Json -Compress)))
$installer="import base64,json`nASSETS=json.loads(base64.b64decode('$encoded').decode('utf-8'))`n"+(Get-Content -LiteralPath (Join-Path $PSScriptRoot 'install-autodeploy.py') -Raw -Encoding UTF8)
$previousEncoding=$OutputEncoding
try {
    $OutputEncoding=[Text.UTF8Encoding]::new($false)
    Write-Host 'Configuring Oracle automatic deployment. Existing API credentials are preserved.'
    $installer | & ssh @sshArgs -T $destination "tr -d '\r' | sudo -n /opt/gongsi/python3 -"
    if($LASTEXITCODE -ne 0) { throw 'Automatic deployment setup did not complete. Review the status above.' }
} finally {
    $OutputEncoding=$previousEncoding
}
if($SendTest) {
    & (Join-Path $PSScriptRoot 'test-oracle.ps1') -SendTest
}
