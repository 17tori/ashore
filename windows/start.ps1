# Builds and starts the personal Ashore stack, then opens it in the browser.
. (Join-Path $PSScriptRoot 'common.ps1')

function New-UrlSafeKey {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $rng.Dispose()
    return [Convert]::ToBase64String($bytes).Replace('+', '-').Replace('/', '_')
}

function New-HexSecret {
    $bytes = New-Object byte[] 24
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $rng.Dispose()
    return -join ($bytes | ForEach-Object { $_.ToString('x2') })
}

function New-EnvFile {
    $port = 8080
    $content = @(
        '# Created by windows/start.ps1. Contains secrets: do not share, keep a copy with your backups.',
        'ENVIRONMENT=production',
        "ASHORE_PORT=$port",
        "PUBLIC_BASE_URL=http://localhost:$port",
        'COOKIE_SECURE=false',
        'LOG_LEVEL=INFO',
        "POSTGRES_PASSWORD=$(New-HexSecret)",
        "ENCRYPTION_KEYS=$(New-UrlSafeKey)",
        'HH_CLIENT_ID=',
        'HH_CLIENT_SECRET=',
        'HH_APP_ACCESS_TOKEN=',
        'HH_USER_AGENT=',
        'AI_PROVIDER=local',
        'AI_BASE_URL=',
        'AI_API_KEY=',
        'AI_MODEL=',
        'TELEGRAM_BOT_TOKEN=',
        'TELEGRAM_BOT_USERNAME=',
        'TELEGRAM_WEBHOOK_SECRET=',
        'DEMO_MODE=true'
    ) -join "`n"
    [IO.File]::WriteAllText($EnvFile, $content + "`n", (New-Object Text.UTF8Encoding $false))
    Write-Host 'Создан файл настроек .env.local с новыми ключами шифрования.'
}

Assert-Docker
if (-not (Test-Path $EnvFile)) { New-EnvFile }
$port = Get-Port
$url = "http://localhost:$port"

Write-Host 'Собираю и запускаю Ashore. Первый запуск занимает 5-15 минут, следующие около минуты.'
Invoke-Docker ($ComposeArgs + @('up', '-d', '--build', '--remove-orphans'))

Write-Host 'Жду, пока сервис ответит...'
$deadline = (Get-Date).AddMinutes(5)
$ready = $false
while ((Get-Date) -lt $deadline) {
    try {
        $response = Invoke-WebRequest -Uri "$url/api/health" -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    Start-Sleep -Seconds 3
}
if (-not $ready) {
    Fail ("Сервис не ответил за 5 минут. Журнал можно посмотреть командой:`n" +
          "docker compose -f docker-compose.local.yml --env-file .env.local logs --tail 100")
}

Write-Host ''
Write-Host "Ashore работает: $url" -ForegroundColor Green
Write-Host 'Данные хранятся только на этом компьютере. Остановить: stop-ashore.bat'
Start-Process $url
