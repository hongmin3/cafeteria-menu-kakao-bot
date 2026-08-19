# FastAPI 카카오 스킬 서버를 실행합니다. 프로세스가 죽으면 자동으로 재시작합니다.
# Task Scheduler의 "AtLogOn" 트리거 하나가 이 스크립트를 한 번 실행하고,
# 이후 재시작은 이 안의 루프가 직접 처리합니다(스케줄러 재시작 횟수 제한에
# 의존하지 않기 위함).
$ErrorActionPreference = "Continue"
. "$PSScriptRoot\windows-common.ps1"
Set-Location (Get-ProjectRoot)
Remove-OldLogs

$python = Get-VenvPython
Write-Log "서버 감시 루프 시작" "server"

while ($true) {
    Write-Log "uvicorn 시작" "server"
    & $python -m uvicorn menu_bot.web:app --host 127.0.0.1 --port 8000 2>&1 |
        ForEach-Object { Write-Log $_ "server" }
    Write-Log "uvicorn 종료됨(종료 코드 $LASTEXITCODE). 5초 후 재시작합니다." "server"
    Start-Sleep -Seconds 5
}
