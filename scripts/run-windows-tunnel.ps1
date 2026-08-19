# ngrok 터널을 실행합니다. 프로세스가 죽으면 자동으로 재시작합니다.
# 같은 고정 도메인으로 macOS 쪽 터널을 아직 쓰고 있다면 먼저 종료한 뒤
# 이 스크립트를 실행하세요(README 참고).
$ErrorActionPreference = "Continue"
. "$PSScriptRoot\windows-common.ps1"
Set-Location (Get-ProjectRoot)
Remove-OldLogs

$ngrokDomain = Get-EnvValue -Name "NGROK_DOMAIN"
if (-not $ngrokDomain) {
    Write-Log "오류: .env의 NGROK_DOMAIN이 비어 있습니다." "tunnel"
    exit 1
}
if (-not (Get-Command ngrok -ErrorAction SilentlyContinue)) {
    Write-Log "오류: ngrok CLI를 찾을 수 없습니다. scripts\install-windows.ps1 안내를 참고해 설치하세요." "tunnel"
    exit 1
}

Write-Log "터널 감시 루프 시작 (도메인: $ngrokDomain)" "tunnel"

while ($true) {
    Write-Log "ngrok http 시작" "tunnel"
    & ngrok http 8000 --url "https://$ngrokDomain" 2>&1 |
        ForEach-Object { Write-Log $_ "tunnel" }
    Write-Log "ngrok 종료됨(종료 코드 $LASTEXITCODE). 5초 후 재시작합니다." "tunnel"
    Start-Sleep -Seconds 5
}
