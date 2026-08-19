# 모든 scripts\run-windows-*.ps1, check-windows-env.ps1가 공통으로 불러쓰는 helper.
# 비밀번호나 토큰 값은 어떤 함수도 Write-Host/로그에 출력하지 않는다.

function Get-ProjectRoot {
    Split-Path -Parent $PSScriptRoot
}

function Get-EnvValue {
    param(
        [Parameter(Mandatory)] [string] $Name,
        [string] $EnvPath = (Join-Path (Get-ProjectRoot) ".env")
    )
    if (-not (Test-Path $EnvPath)) { return $null }
    $line = Get-Content $EnvPath | Where-Object { $_ -match "^\s*$Name\s*=" } | Select-Object -First 1
    if (-not $line) { return $null }
    return ($line -replace "^\s*$Name\s*=", "").Trim()
}

function Write-Log {
    param(
        [Parameter(Mandatory)] [string] $Message,
        [Parameter(Mandatory)] [string] $LogName
    )
    $logDir = Join-Path (Get-ProjectRoot) "logs"
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $logFile = Join-Path $logDir "$LogName-$(Get-Date -Format 'yyyy-MM-dd').log"
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message"
    Add-Content -Path $logFile -Value $line -Encoding utf8
    Write-Host $line
}

function Remove-OldLogs {
    param(
        [int] $KeepDays = 30
    )
    $logDir = Join-Path (Get-ProjectRoot) "logs"
    if (-not (Test-Path $logDir)) { return }
    $cutoff = (Get-Date).AddDays(-$KeepDays)
    Get-ChildItem -Path $logDir -Filter "*.log" | Where-Object { $_.LastWriteTime -lt $cutoff } | Remove-Item -Force
}

function Get-VenvPython {
    $root = Get-ProjectRoot
    $venvPython = Join-Path $root ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        throw "가상환경이 없습니다. scripts\install-windows.ps1 을 먼저 실행하세요."
    }
    return $venvPython
}

function Get-MenuBotExe {
    $root = Get-ProjectRoot
    $exe = Join-Path $root ".venv\Scripts\menu-bot.exe"
    if (-not (Test-Path $exe)) {
        throw "가상환경이 없습니다. scripts\install-windows.ps1 을 먼저 실행하세요."
    }
    return $exe
}
