$ErrorActionPreference = 'Stop'
$postgresRoot = if ($env:XM_POSTGRES_ROOT) { $env:XM_POSTGRES_ROOT } else { 'E:\PostgreSQL-18' }
$postgresStart = Join-Path $postgresRoot 'scripts\start.ps1'
if (-not (Test-Path -LiteralPath $postgresStart)) { throw "PostgreSQL start script was not found at $postgresStart." }
& $postgresStart
try {
    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 2
    if ($health.company -eq '星幕设备') {
        Write-Host '星幕设备网页已在运行：http://127.0.0.1:8765'
        exit 0
    }
} catch {
    # The web server is not running yet.
}
Set-Location -LiteralPath $PSScriptRoot
Write-Host '星幕设备项目已准备好。请在浏览器打开 http://127.0.0.1:8765'
& (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') -m xingmu.server
