$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\windows-common.ps1"

$root = Get-ProjectRoot
$configPath = Join-Path $root 'data\offsite-monitor\settings.json'
if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) { throw 'MenuBot monitor settings do not exist' }

$name = 'VieworksMenuBot-ExternalMonitor'
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -WorkingDirectory $root -Argument (
    '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f (Join-Path $PSScriptRoot 'run-external-monitor.ps1')
)
$trigger = New-ScheduledTaskTrigger -Daily -At '00:00'
$repeated = New-ScheduledTaskTrigger -Once -At '00:00' -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Days 1)
$trigger.Repetition = $repeated.Repetition
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Get-ScheduledTask -TaskName $name | Select-Object TaskName, State
