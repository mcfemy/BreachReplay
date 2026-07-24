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

# ── Branch guard ─────────────────────────────────────────────────────────────
# Refuses to deploy anything but a clean checkout of main. This script
# uploads whatever is sitting in $ROOT\backend and $ROOT\frontend\dist
# verbatim — it has no concept of "which commit" it's deploying, so an
# uncommitted local change or a deploy run from a feature branch would ship
# silently, with nothing in git history to say what actually went to prod.
Push-Location $ROOT
$CurrentBranch = (git rev-parse --abbrev-ref HEAD).Trim()
if ($CurrentBranch -ne "main") {
    Pop-Location
    Write-Error "Refusing to deploy: current branch is '$CurrentBranch', not 'main'. Checkout main first."
    exit 1
}
$DirtyFiles = git status --porcelain
if ($DirtyFiles) {
    Pop-Location
    Write-Error "Refusing to deploy: working tree is not clean. Uncommitted changes:`n$DirtyFiles"
    exit 1
}
Pop-Location

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
if ($LASTEXITCODE -ne 0) { Write-Error "Backend upload failed"; exit 1 }
scp $SSH_OPTS.Split(" ") "$ROOT\docker-compose.prod.yml" "${SSH_TARGET}:/home/ec2-user/breachreplay/"
if ($LASTEXITCODE -ne 0) { Write-Error "docker-compose.prod.yml upload failed"; exit 1 }

Write-Host "==> Uploading frontend build..."
# Stage to a temp dir first (avoids nginx ownership issues on /var/www).
# NOTE: upload the whole "dist" folder, not "dist\*" — PowerShell does not
# glob-expand wildcards for native commands like scp.exe, so a trailing
# "\*" gets passed to scp literally and fails to match anything, leaving
# the remote temp dir empty. rsync --delete against an empty source would
# then wipe the live site. Uploading the folder itself avoids the glob
# entirely; the remote rsync source path is adjusted to match.
ssh $SSH_OPTS.Split(" ") $SSH_TARGET "rm -rf /tmp/br_dist_upload && mkdir -p /tmp/br_dist_upload"
scp $SSH_OPTS.Split(" ") -r "$ROOT\frontend\dist" "${SSH_TARGET}:/tmp/br_dist_upload/"
if ($LASTEXITCODE -ne 0) { Write-Error "Frontend upload failed"; exit 1 }
ssh $SSH_OPTS.Split(" ") $SSH_TARGET "sudo mkdir -p /var/www/breachreplay && sudo rsync -a --delete /tmp/br_dist_upload/dist/ /var/www/breachreplay/ && sudo chown -R nginx:nginx /var/www/breachreplay && rm -rf /tmp/br_dist_upload"
if ($LASTEXITCODE -ne 0) { Write-Error "Frontend publish failed"; exit 1 }

# ── Rebuild and restart containers ───────────────────────────────────────────
Write-Host "==> Restarting services..."
# NOTE: deliberately no `python seed.py` here. seed.py skips-if-exists by
# source_reference, so against an already-populated DB it's a silent no-op —
# worse, its presence in the deploy path creates the false impression that
# scenario data changes shipped when they didn't. Data changes to existing
# rows (e.g. backfilling a new column onto rows that already exist) belong in
# an explicit, reviewable one-off backfill script run deliberately, not in
# the routine deploy path. seed.py's insert-new-scenarios behavior is still
# available to run by hand when a genuinely new scenario is added.
ssh $SSH_OPTS.Split(" ") $SSH_TARGET @"
cd /home/ec2-user/breachreplay
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build --remove-orphans
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T backend alembic upgrade head
"@

if ($LASTEXITCODE -ne 0) { Write-Error "Remote restart failed"; exit 1 }

Write-Host ""
Write-Host "==> Deploy complete! https://breachreplay.com" -ForegroundColor Green
