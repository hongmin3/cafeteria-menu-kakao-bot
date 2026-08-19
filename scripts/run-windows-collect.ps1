# 운영용 주간 수집: 월요일 아침에 한 번 실행되도록 예약합니다.
# 차주 식단표는 주말에 게시되지만 이번 주 수집에는 포함하지 않으므로
# (운영 DB는 항상 "이번 주"만 저장), 월요일 아침 실행이 유일하게 안전한
# 시점입니다.
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\windows-common.ps1"
Set-Location (Get-ProjectRoot)
Remove-OldLogs

$menuBot = Get-MenuBotExe
$manifest = "data\latest_manifest.json"

try {
    Write-Log "주간 수집 시작" "collect"
    & $menuBot scrape --pages 2 --output $manifest 2>&1 | ForEach-Object { Write-Log $_ "collect" }
    if ($LASTEXITCODE -ne 0) { throw "scrape 실패(종료 코드 $LASTEXITCODE)" }

    & $menuBot ingest $manifest 2>&1 | ForEach-Object { Write-Log $_ "collect" }
    if ($LASTEXITCODE -ne 0) { throw "ingest 실패(종료 코드 $LASTEXITCODE)" }

    Write-Log "주간 수집 완료" "collect"
} catch {
    Write-Log "오류: $($_.Exception.Message)" "collect"
    exit 1
}
