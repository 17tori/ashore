# Stops the stack. Data stays in Docker volumes and comes back on the next start.
. (Join-Path $PSScriptRoot 'common.ps1')

if (-not (Test-Path $EnvFile)) { Fail 'Ashore ещё ни разу не запускался на этом компьютере.' }
Assert-Docker
Invoke-Docker ($ComposeArgs + @('stop'))
Write-Host ''
Write-Host 'Ashore остановлен. Данные сохранены, запустить снова: start-ashore.bat' -ForegroundColor Green
