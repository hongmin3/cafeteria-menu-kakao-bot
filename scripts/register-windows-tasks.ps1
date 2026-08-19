# 재부팅/로그온 후 자동 시작과 주간 스케줄을 Windows 작업 스케줄러에 등록합니다.
#
# 작업 스케줄러를 선택한 이유: 이 프로젝트는 Windows 서비스로 만들기보다
# 사용자 세션에서 Chrome(Playwright)과 ngrok을 그대로 띄우는 편이 훨씬
# 단순합니다. 서비스로 만들려면 별도 서비스 래퍼(NSSM 등)와 세션 0 격리
# 문제를 다뤄야 하지만, 작업 스케줄러는 관리자 권한 없이 현재 사용자
# 계정만으로 등록할 수 있고 재시작/로그 확인도 GUI에서 바로 됩니다.
# 대신 "재시작"은 스케줄러의 제한된 RestartCount 대신 각 run-windows-*.ps1
# 안의 무한 재시작 루프가 담당합니다(스케줄러 설정에도 방어적으로 재시작을
# 걸어 두지만, 실제 복구 로직은 스크립트 쪽이 1차 책임입니다).
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\windows-common.ps1"
$root = Get-ProjectRoot

function Register-LongRunningTask {
    param([string]$Name, [string]$ScriptPath)
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -DontStopOnIdleEnd `
        -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
        -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Host "등록: $Name (로그온 시 시작, 죽으면 스크립트 내부 루프가 재시작)"
}

function Register-OneShotWeeklyTask {
    param([string]$Name, [string]$ScriptPath, [string]$DayOfWeek, [string]$At)
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $DayOfWeek -At $At
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) `
        -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Host "등록: $Name ($DayOfWeek $At, 1회 실행)"
}

function Register-RepeatingWeekendTask {
    param([string]$Name, [string]$ScriptPath)
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""
    # 토요일 00:05부터 2일(토+일) 동안 2시간 간격으로 반복 실행.
    # 스크립트 자체가 이미 확인된 주차면 그룹웨어 접속 없이 즉시 종료하므로
    # 확인 후에는 이 반복 실행이 사실상 아무 일도 하지 않게 된다.
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At "00:05"
    $trigger.Repetition = (New-ScheduledTaskTrigger -Once -At "00:05" `
        -RepetitionInterval (New-TimeSpan -Hours 2) `
        -RepetitionDuration (New-TimeSpan -Days 2)).Repetition
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) `
        -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Host "등록: $Name (토요일 00:05부터 2일간 2시간 간격 반복)"
}

Write-Host "=== Windows 작업 스케줄러 등록 (현재 사용자: $env:USERNAME) ===`n"

Register-LongRunningTask -Name "VieworksMenuBot-Server" -ScriptPath (Join-Path $root "scripts\run-windows-server.ps1")
Register-LongRunningTask -Name "VieworksMenuBot-Tunnel" -ScriptPath (Join-Path $root "scripts\run-windows-tunnel.ps1")
Register-OneShotWeeklyTask -Name "VieworksMenuBot-Collect" -ScriptPath (Join-Path $root "scripts\run-windows-collect.ps1") -DayOfWeek Monday -At "08:00"
Register-OneShotWeeklyTask -Name "VieworksMenuBot-NextWeekWatch-Friday" -ScriptPath (Join-Path $root "scripts\run-windows-next-week-watch.ps1") -DayOfWeek Friday -At "22:00"
Register-RepeatingWeekendTask -Name "VieworksMenuBot-NextWeekWatch-Weekend" -ScriptPath (Join-Path $root "scripts\run-windows-next-week-watch.ps1")

Write-Host "`n등록 완료. 'taskschd.msc'에서 확인하거나 Get-ScheduledTask -TaskName 'VieworksMenuBot-*' 으로 조회하세요."
Write-Host "제거하려면: Get-ScheduledTask -TaskName 'VieworksMenuBot-*' | Unregister-ScheduledTask -Confirm:`$false"
