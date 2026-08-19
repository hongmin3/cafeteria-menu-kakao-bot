# 다음 주 식단표 게시글이 올라왔는지 확인합니다.
# 이미 확인된 주차라면 그룹웨어에 접속하지 않고 바로 종료합니다(menu_bot.next_week_watch 참고).
# Task Scheduler 트리거: 금요일 22:00 1회 + 토요일 00:05부터 2일간 2시간 간격 반복.
$ErrorActionPreference = "Continue"
. "$PSScriptRoot\windows-common.ps1"
Set-Location (Get-ProjectRoot)
Remove-OldLogs

$menuBot = Get-MenuBotExe
$output = & $menuBot check-next-week 2>&1
$output | ForEach-Object { Write-Log $_ "next-week-watch" }
