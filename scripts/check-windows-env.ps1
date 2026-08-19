# 그룹웨어 로그인이나 실제 수집을 실행하지 않는, 읽기 전용 환경 점검 스크립트.
$ErrorActionPreference = "Continue"
. "$PSScriptRoot\windows-common.ps1"
$root = Get-ProjectRoot
Set-Location $root

function Show-Check($label, $ok, $detail = "") {
    $mark = if ($ok) { "[OK]" } else { "[!!]" }
    Write-Host ("{0,-6} {1}  {2}" -f $mark, $label, $detail)
}

Write-Host "=== 뷰밥 메뉴 알리미 Windows 환경 점검 ===`n"

$os = Get-CimInstance Win32_OperatingSystem
Show-Check "운영체제" $true "$($os.Caption), 여유 메모리 $([math]::Round($os.FreePhysicalMemory/1MB,1))GB / $([math]::Round($os.TotalVisibleMemorySize/1MB,1))GB"

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $ver = & $venvPython --version
    Show-Check "가상환경 Python" $true $ver
} else {
    Show-Check "가상환경 Python" $false "scripts\install-windows.ps1 을 먼저 실행하세요"
}

$chromePaths = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"
)
$chrome = $chromePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
Show-Check "Google Chrome" ([bool]$chrome) $chrome

$ngrok = Get-Command ngrok -ErrorAction SilentlyContinue
Show-Check "ngrok CLI" ([bool]$ngrok) $(if ($ngrok) { & ngrok version } else { "설치되지 않음" })

if ($ngrok) {
    $checkOutput = & ngrok config check 2>&1
    Show-Check "ngrok 설정 파일" ($LASTEXITCODE -eq 0) ($checkOutput | Select-Object -First 1)
}

try {
    $tnc = Test-NetConnection -ComputerName "connect.ngrok-agent.com" -Port 443 -WarningAction SilentlyContinue
    Show-Check "ngrok 아웃바운드 443" $tnc.TcpTestSucceeded
} catch {
    Show-Check "ngrok 아웃바운드 443" $false $_.Exception.Message
}

$envPath = Join-Path $root ".env"
if (Test-Path $envPath) {
    $required = @("GROUPWARE_USER","GROUPWARE_PASSWORD","GROUPWARE_URL","KAKAO_WEBHOOK_TOKEN","NGROK_DOMAIN")
    foreach ($name in $required) {
        $value = Get-EnvValue -Name $name -EnvPath $envPath
        Show-Check ".env $name" ([bool]$value) $(if ($value) { "[SET]" } else { "[EMPTY]" })
    }
} else {
    Show-Check ".env 파일" $false "없음 - .env.example을 복사해 채워 주세요"
}

try {
    $groupwareUrl = Get-EnvValue -Name "GROUPWARE_URL" -EnvPath $envPath
    if ($groupwareUrl) {
        $uri = [Uri]$groupwareUrl
        $tnc2 = Test-NetConnection -ComputerName $uri.Host -Port 443 -WarningAction SilentlyContinue
        Show-Check "그룹웨어 호스트 접속" $tnc2.TcpTestSucceeded $uri.Host
    }
} catch {
    Show-Check "그룹웨어 호스트 접속" $false $_.Exception.Message
}

Write-Host "`n=== 점검 완료 ==="
