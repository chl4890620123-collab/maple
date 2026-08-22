param(
    [string]$Repo = "chl4890620123-collab/maple",
    [string]$DeployPath = "C:\home\maple\app",
    [int[]]$PortCandidates = @(8000, 18080, 18081, 18082),
    [string]$DefaultFeeRate = "0.05",
    [switch]$SkipGitHubSetup
)

$ErrorActionPreference = "Stop"

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Ensure-OpenSshServer {
    $cap = Get-WindowsCapability -Online | Where-Object Name -like 'OpenSSH.Server*' | Select-Object -First 1
    if (-not $cap -or $cap.State -ne 'Installed') {
        Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 | Out-Null
    }

    Set-Service -Name sshd -StartupType Automatic
    if ((Get-Service sshd).Status -ne 'Running') {
        Start-Service sshd
    }

    $sshRule = Get-NetFirewallRule -DisplayName 'Maple SSH 22' -ErrorAction SilentlyContinue
    if (-not $sshRule) {
        New-NetFirewallRule -DisplayName 'Maple SSH 22' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 22 | Out-Null
    }
}

function Test-DockerReady {
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $docker) { return $false }
    & docker info *> $null
    return ($LASTEXITCODE -eq 0)
}

function Ensure-Docker {
    if (Test-DockerReady) { return }

    $dockerDesktop = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
    if (Test-Path $dockerDesktop) {
        Start-Process $dockerDesktop
        for ($i = 0; $i -lt 60; $i++) {
            Start-Sleep -Seconds 2
            if (Test-DockerReady) { return }
        }
    }
    throw 'Docker Engine is not ready. Start Docker Desktop and run this script again.'
}

function Select-AppPort {
    foreach ($port in $PortCandidates) {
        $listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
        if (-not $listener) { return $port }
    }
    throw "No free port found in candidates: $($PortCandidates -join ', ')"
}

function Ensure-AppFirewall([int]$Port) {
    $name = "Maple Craft $Port"
    $rule = Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue
    if (-not $rule) {
        New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port | Out-Null
    }
}

function Sync-Repository {
    $gitDir = Join-Path $DeployPath '.git'
    if (Test-Path $gitDir) {
        Set-Location $DeployPath
        git fetch origin main
        if ($LASTEXITCODE -ne 0) { throw 'git fetch failed' }
        git reset --hard origin/main
        if ($LASTEXITCODE -ne 0) { throw 'git reset failed' }
        return
    }

    if (Test-Path $DeployPath) {
        $existing = Get-ChildItem $DeployPath -Force -ErrorAction SilentlyContinue
        if ($existing) {
            throw "$DeployPath exists and is not an empty Git repository. Refusing to overwrite it."
        }
    } else {
        New-Item -ItemType Directory -Force -Path $DeployPath | Out-Null
    }

    git clone "https://github.com/$Repo.git" $DeployPath
    if ($LASTEXITCODE -ne 0) { throw 'git clone failed' }
    Set-Location $DeployPath
}

function Ensure-RuntimeEnv([int]$Port) {
    $runtime = Join-Path $DeployPath '.env.runtime'
    if (-not (Test-Path $runtime)) {
        $token = ([guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N'))
        @"
APP_PORT=$Port
BIND_HOST=0.0.0.0
ADMIN_TOKEN=$token
DB_PATH=/app/data/maple_craft.db
DEFAULT_FEE_RATE=$DefaultFeeRate
CORS_ORIGINS=
"@ | Set-Content -Path $runtime -Encoding ascii
    }
    return $runtime
}

function Deploy-App([int]$Port) {
    Set-Location $DeployPath
    & '.\deploy\scripts\deploy.ps1' -AppPort "$Port" -DefaultFeeRate $DefaultFeeRate

    $healthy = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 2
        try {
            $result = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 3
            if ($result.status -eq 'ok') {
                $healthy = $true
                break
            }
        } catch {}
    }
    if (-not $healthy) {
        docker compose --env-file '.env.runtime' ps
        docker compose --env-file '.env.runtime' logs --tail 100 maple-craft
        throw 'Container started but /api/health did not become healthy.'
    }
}

function Ensure-GhCli {
    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if ($gh) { return $gh.Source }

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id GitHub.cli -e --silent --accept-source-agreements --accept-package-agreements | Out-Null
        $candidate = 'C:\Program Files\GitHub CLI\gh.exe'
        if (Test-Path $candidate) { return $candidate }
    }
    throw 'GitHub CLI (gh) is required for automatic Actions secret setup.'
}

function Configure-GitHub([int]$Port) {
    $gh = Ensure-GhCli

    & $gh auth status --hostname github.com *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'GitHub login is required once. Follow the device/browser login shown by gh.'
        & $gh auth login --hostname github.com --git-protocol https --web
        if ($LASTEXITCODE -ne 0) { throw 'GitHub CLI login failed.' }
    }

    $publicIp = (Invoke-RestMethod 'https://api.ipify.org?format=text' -TimeoutSec 10).Trim()
    $serverUser = $env:USERNAME

    $securePassword = Read-Host 'Windows/SSH password (stored only as an encrypted GitHub Actions secret)' -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
    try {
        $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
        $publicIp | & $gh secret set SERVER_HOST --repo $Repo
        $serverUser | & $gh secret set SERVER_USER --repo $Repo
        '22' | & $gh secret set SERVER_PORT --repo $Repo
        $plainPassword | & $gh secret set SERVER_PASSWORD --repo $Repo
    } finally {
        if ($ptr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
        $plainPassword = $null
    }

    & $gh variable set DEPLOY_PATH --repo $Repo --body $DeployPath
    & $gh variable set APP_PORT --repo $Repo --body "$Port"
    & $gh variable set DEFAULT_FEE_RATE --repo $Repo --body $DefaultFeeRate
    & $gh variable set ENABLE_DEPLOY --repo $Repo --body 'true'

    Write-Host 'GitHub Actions secrets/variables configured.'
}

if (-not (Test-Admin)) {
    throw 'Run PowerShell as Administrator and execute this script again.'
}

Write-Host '1/7 Enable SSH 22'
Ensure-OpenSshServer

Write-Host '2/7 Check Docker'
Ensure-Docker

Write-Host '3/7 Select free app port'
$appPort = Select-AppPort
Write-Host "Selected app port: $appPort"
Ensure-AppFirewall $appPort

Write-Host '4/7 Clone/update repository'
Sync-Repository

Write-Host '5/7 Create runtime environment'
$runtime = Ensure-RuntimeEnv $appPort

Write-Host '6/7 Build and deploy Docker container'
Deploy-App $appPort

if (-not $SkipGitHubSetup) {
    Write-Host '7/7 Configure GitHub Actions'
    Configure-GitHub $appPort
} else {
    Write-Host '7/7 GitHub setup skipped by parameter.'
}

$localIp = (Get-NetIPAddress -AddressFamily IPv4 -PrefixOrigin Dhcp -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike '169.254*' -and $_.IPAddress -notlike '127.*' } |
    Select-Object -First 1 -ExpandProperty IPAddress)
if (-not $localIp) {
    $localIp = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '169.254*' -and $_.IPAddress -notlike '127.*' } |
        Select-Object -First 1 -ExpandProperty IPAddress)
}

Write-Host ''
Write-Host 'Maple Craft bootstrap completed.'
Write-Host "Local health: http://127.0.0.1:$appPort/api/health"
if ($localIp) { Write-Host "LAN address : http://${localIp}:$appPort" }
Write-Host 'For Internet access, the router must forward the selected port to this PC.'
Write-Host "Runtime env : $runtime"
