# Shared helpers for the Windows launch scripts. Dot-sourced by start/stop/backup.
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$EnvFile = Join-Path $Root '.env.local'
$ComposeArgs = @('compose', '-f', 'docker-compose.local.yml', '--env-file', '.env.local')

function Fail([string]$Message) {
    Write-Host ''
    Write-Host $Message -ForegroundColor Red
    exit 1
}

function Get-Port {
    $port = 8080
    if (Test-Path $EnvFile) {
        $line = Get-Content $EnvFile | Where-Object { $_ -match '^ASHORE_PORT=(\d+)$' } | Select-Object -First 1
        if ($line) { $port = [int]($line -replace '^ASHORE_PORT=', '') }
    }
    return $port
}

function Invoke-Docker([string[]]$Arguments) {
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) { Fail "Команда docker завершилась с ошибкой (код $LASTEXITCODE)." }
}

function Test-DockerRunning {
    # Windows PowerShell 5.1 turns redirected native stderr into errors; keep them non-fatal here.
    $ErrorActionPreference = 'Continue'
    & docker info *> $null
    return $LASTEXITCODE -eq 0
}

function Assert-Docker {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Fail ("Docker Desktop не установлен.`n" +
              "Скачайте его с https://www.docker.com/products/docker-desktop/ , установите, " +
              "перезагрузите компьютер и запустите этот файл снова.")
    }
    if (Test-DockerRunning) { return }
    $desktop = Join-Path $Env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
    if (Test-Path $desktop) {
        Write-Host 'Запускаю Docker Desktop...'
        Start-Process $desktop | Out-Null
    }
    $deadline = (Get-Date).AddMinutes(3)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 3
        if (Test-DockerRunning) { return }
    }
    Fail 'Docker Desktop не запустился. Откройте его вручную, дождитесь зелёного статуса и запустите этот файл снова.'
}
