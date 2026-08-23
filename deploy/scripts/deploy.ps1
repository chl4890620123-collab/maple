param(
    [string]$RuntimeEnv = "D:\server-data\maple\runtime\.env"
)

$ErrorActionPreference = "Stop"
$AppRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $AppRoot

if (-not (Test-Path $RuntimeEnv)) {
    throw "Maple runtime env file not found: $RuntimeEnv"
}

$requiredKeys = @(
    "APP_PORT",
    "BIND_HOST",
    "ADMIN_TOKEN",
    "DB_PATH",
    "DEFAULT_FEE_RATE"
)

$envMap = @{}
Get-Content $RuntimeEnv | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) { return }
    $parts = $line -split "=", 2
    if ($parts.Count -eq 2) {
        $envMap[$parts[0].Trim()] = $parts[1]
    }
}

foreach ($key in $requiredKeys) {
    if (-not $envMap.ContainsKey($key) -or [string]::IsNullOrWhiteSpace($envMap[$key])) {
        throw "Required runtime setting '$key' is missing in $RuntimeEnv"
    }
}

$AppPort = $envMap["APP_PORT"]
$DataRoot = "D:\server-data\maple\data"
$BackupDir = "D:\server-data\maple\backups"
New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

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

$env:MAPLE_DATA_DIR = $DataRoot

docker compose --env-file $RuntimeEnv up -d --build --remove-orphans
if ($LASTEXITCODE -ne 0) { throw "docker compose deployment failed" }

docker compose --env-file $RuntimeEnv ps

$healthUrl = "http://127.0.0.1:$AppPort/api/health"
$healthy = $false
for ($attempt = 1; $attempt -le 12; $attempt++) {
    try {
        $response = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -eq 200) {
            $healthy = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 5
    }
}

if (-not $healthy) {
    throw "Maple health check failed: $healthUrl"
}

Write-Host "Maple runtime env: $RuntimeEnv"
Write-Host "Maple data root: $DataRoot"
Write-Host "Maple health check OK: $healthUrl"
Write-Host "Maple deployment completed."
