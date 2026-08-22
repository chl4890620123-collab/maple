param(
    [string]$AppPort = "18080",
    [string]$DefaultFeeRate = "0.05"
)

$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot "..\.."))

$RuntimeEnv = Join-Path (Get-Location) ".env.runtime"
$BackupDir = Join-Path (Get-Location) "data\backups"
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

if (-not (Test-Path $RuntimeEnv)) {
    @"
APP_PORT=$AppPort
BIND_HOST=0.0.0.0
ADMIN_TOKEN=CHANGE_ME_ON_SERVER
DB_PATH=/app/data/maple_craft.db
DEFAULT_FEE_RATE=$DefaultFeeRate
CORS_ORIGINS=
"@ | Set-Content -Path $RuntimeEnv -Encoding ascii
    Write-Warning ".env.runtime was created. Change ADMIN_TOKEN before exposing this service publicly."
}

# Update only non-secret operational values while preserving server-local secrets.
$lines = Get-Content $RuntimeEnv
$lines = $lines | Where-Object { $_ -notmatch '^(APP_PORT|DEFAULT_FEE_RATE)=' }
$lines += "APP_PORT=$AppPort"
$lines += "DEFAULT_FEE_RATE=$DefaultFeeRate"
$lines | Set-Content -Path $RuntimeEnv -Encoding ascii

# Back up the SQLite database from the running container when it exists.
$containerId = docker compose --env-file $RuntimeEnv ps -q maple-craft
if ($containerId) {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $tmpPath = "/tmp/maple_craft_backup_$stamp.db"
    docker exec $containerId python -c "import os,sqlite3; src=os.getenv('DB_PATH','/app/data/maple_craft.db'); s=sqlite3.connect(src); d=sqlite3.connect('$tmpPath'); s.backup(d); d.close(); s.close()"
    if ($LASTEXITCODE -eq 0) {
        docker cp "${containerId}:${tmpPath}" (Join-Path $BackupDir "maple_craft_$stamp.db")
        docker exec $containerId rm -f $tmpPath | Out-Null
    }
}

Get-ChildItem $BackupDir -Filter "maple_craft_*.db" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-28) } |
    Remove-Item -Force

docker compose --env-file $RuntimeEnv up -d --build --remove-orphans
if ($LASTEXITCODE -ne 0) { throw "docker compose deployment failed" }

docker compose --env-file $RuntimeEnv ps

# Project-local cleanup only; do not run docker system/volume/network prune on the shared server.

Write-Host "Maple Craft deployment completed on host port $AppPort"
