# deploy.ps1 — Push local changes to the EC2 instance and restart services
# Usage from project root: .\infra\deploy.ps1
# Requires: OpenSSH (built into Windows 10+), Node.js

param(
    [string]$KeyFile = "breachreplay-key.pem",
    [string]$EC2User = "ec2-user",
    [string]$EC2Host = "" # filled in automatically from infra/ec2_ip.txt
)

$ErrorActionPreference = "Stop"
$ROOT = Split-Path $PSScriptRoot -Parent

# ── Load EC2 IP ───────────────────────────────────────────────────────────────
$IpFile = Join-Path $PSScriptRoot "ec2_ip.txt"
if (-not $EC2Host) {
    if (Test-Path $IpFile) {
        $EC2Host = (Get-Content $IpFile).Trim()
    } else {
        Write-Error "No EC2 IP found. Create infra/ec2_ip.txt with the Elastic IP, or pass -EC2Host."
    }
}

$SSH_TARGET = "${EC2User}@${EC2Host}"
$KEY = Join-Path $ROOT $KeyFile
$SSH_OPTS = "-i `"$KEY`" -o StrictHostKeyChecking=no"

Write-Host "==> Deploying to $SSH_TARGET" -ForegroundColor Cyan

# ── Build frontend ────────────────────────────────────────────────────────────
Write-Host "==> Building React frontend..."
Push-Location (Join-Path $ROOT "frontend")
$env:VITE_API_URL = "https://breachreplay.com/api/v1"
$env:VITE_WS_URL  = "wss://breachreplay.com"
npm run build
if ($LASTEXITCODE -ne 0) { Write-Error "Frontend build failed"; exit 1 }
Pop-Location

# ── Copy files to EC2 ────────────────────────────────────────────────────────
Write-Host "==> Uploading backend..."
# Fix permissions first — Docker containers run as root and leave directories non-writable
ssh $SSH_OPTS.Split(" ") $SSH_TARGET "sudo chmod -R u+w /home/ec2-user/breachreplay/ 2>/dev/null || true"

$REMOTE = "${SSH_TARGET}:/home/ec2-user/breachreplay"

scp $SSH_OPTS.Split(" ") -r "$ROOT\backend" "${SSH_TARGET}:/home/ec2-user/breachreplay/"
scp $SSH_OPTS.Split(" ") "$ROOT\docker-compose.prod.yml" "${SSH_TARGET}:/home/ec2-user/breachreplay/"

Write-Host "==> Uploading frontend build..."
# Stage to a temp dir first (avoids nginx ownership issues on /var/www)
ssh $SSH_OPTS.Split(" ") $SSH_TARGET "rm -rf /tmp/br_dist && mkdir -p /tmp/br_dist"
scp $SSH_OPTS.Split(" ") -r "$ROOT\frontend\dist\*" "${SSH_TARGET}:/tmp/br_dist/"
ssh $SSH_OPTS.Split(" ") $SSH_TARGET "sudo mkdir -p /var/www/breachreplay && sudo rsync -a --delete /tmp/br_dist/ /var/www/breachreplay/ && sudo chown -R nginx:nginx /var/www/breachreplay && rm -rf /tmp/br_dist"

# ── Rebuild and restart containers ───────────────────────────────────────────
Write-Host "==> Restarting services..."
ssh $SSH_OPTS.Split(" ") $SSH_TARGET @"
cd /home/ec2-user/breachreplay
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build --remove-orphans
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T backend alembic upgrade head
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T backend python seed.py
"@

if ($LASTEXITCODE -ne 0) { Write-Error "Remote restart failed"; exit 1 }

Write-Host ""
Write-Host "==> Deploy complete! https://breachreplay.com" -ForegroundColor Green
