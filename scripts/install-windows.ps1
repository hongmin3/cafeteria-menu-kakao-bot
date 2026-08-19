# 회사 Windows PC에 뷰밥 메뉴 알리미를 처음 설치할 때 한 번 실행합니다.
# PaddleOCR/paddlepaddle은 Python 3.13에서만 검증했습니다(3.14는 wheel 호환성 미확인).
$ErrorActionPreference = "Stop"
. "$PSScriptRoot\windows-common.ps1"
$root = Get-ProjectRoot
Set-Location $root

$pythonCandidates = @(
    "$env:USERPROFILE\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
)
$python = $pythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $python) {
    $pyLauncher = Get-Command "py" -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        $found = & py -3.13 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $found) { $python = $found.Trim() }
    }
}
if (-not $python) {
    throw "Python 3.13을 찾을 수 없습니다. PaddleOCR wheel은 3.13에서만 검증했으니 3.13을 설치한 뒤 다시 실행하세요."
}
Write-Host "Python 3.13 사용: $python"

if (-not (Test-Path ".venv")) {
    & $python -m venv .venv
}
$venvPython = Join-Path $root ".venv\Scripts\python.exe"

& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -e ".[dev]"
& $venvPython -m pip install paddleocr paddlepaddle
& $venvPython -m playwright install chromium

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host ".env을 새로 만들었습니다. 실제 그룹웨어 계정과 카카오 토큰 값으로 채워 주세요."
}

New-Item -ItemType Directory -Force -Path "logs" | Out-Null
New-Item -ItemType Directory -Force -Path "data\images" | Out-Null

Write-Host ""
Write-Host "설치 완료. 다음 순서로 진행하세요:"
Write-Host "  1) scripts\check-windows-env.ps1  - 환경 점검"
Write-Host "  2) scripts\register-windows-tasks.ps1 - 자동 시작 등록(선택)"
