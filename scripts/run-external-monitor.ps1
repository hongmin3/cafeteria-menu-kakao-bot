$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\windows-common.ps1"
Set-Location (Get-ProjectRoot)

$monitorDir = Join-Path (Get-ProjectRoot) 'data\offsite-monitor'
$configPath = Join-Path $monitorDir 'settings.json'
$config = Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json
$token = ConvertTo-SecureString -String $config.protected_token
$env:MENUBOT_MONITOR_BEARER = [System.Net.NetworkCredential]::new('', $token).Password
try {
    $resultJson = & (Get-VenvPython) -B -m menu_bot.ops monitor --monitor-dir $monitorDir --domain $config.domain --backup-host $config.backup_host
    if ($LASTEXITCODE -ne 0) { throw 'MenuBot monitor failed to run' }
    $result = $resultJson | ConvertFrom-Json
} finally {
    Remove-Item Env:MENUBOT_MONITOR_BEARER -ErrorAction SilentlyContinue
}

if ($result.backup_day -match '^\d{4}-\d{2}-\d{2}$') {
    $backup = Join-Path $monitorDir "backups\menubot-$($result.backup_day).db"
    $file = Get-Item -LiteralPath $backup
    if ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Unexpected backup file type' }
    $ids = @([Security.Principal.WindowsIdentity]::GetCurrent().User.Value, 'S-1-5-18')
    $rules = (Get-Acl -LiteralPath $backup).GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])
    if (@($rules | Where-Object { $_.IdentityReference.Value -notin $ids }).Count) {
        throw 'Backup permissions are not private'
    }
}

if ($result.event) {
    $message = "MenuBot: $($result.event)"
    $shell = New-Object -ComObject WScript.Shell
    [void]$shell.Popup($message, 12, 'MenuBot monitor', 48)
}
Write-Output $resultJson
