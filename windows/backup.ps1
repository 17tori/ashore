# Writes a database dump and a copy of .env.local (the encryption keys) to backups\<timestamp>.
. (Join-Path $PSScriptRoot 'common.ps1')

if (-not (Test-Path $EnvFile)) { Fail 'Ashore ещё ни разу не запускался на этом компьютере.' }
Assert-Docker
$stamp = Get-Date -Format 'yyyy-MM-dd_HH-mm'
$target = Join-Path $Root "backups\$stamp"
New-Item -ItemType Directory -Force -Path $target | Out-Null

Invoke-Docker ($ComposeArgs + @('up', '-d', 'postgres'))
Invoke-Docker ($ComposeArgs + @('exec', '-T', 'postgres', 'pg_dump', '-U', 'ashore', '-d', 'ashore', '-Fc', '-f', '/tmp/ashore.dump'))
Invoke-Docker ($ComposeArgs + @('cp', 'postgres:/tmp/ashore.dump', (Join-Path $target 'ashore.dump')))
Invoke-Docker ($ComposeArgs + @('exec', '-T', 'postgres', 'rm', '-f', '/tmp/ashore.dump'))
Copy-Item $EnvFile (Join-Path $target 'env.local.txt')

Write-Host ''
Write-Host "Резервная копия сохранена в $target" -ForegroundColor Green
Write-Host 'В папке лежат ключи шифрования (env.local.txt). Храните её так же бережно, как пароли.'
