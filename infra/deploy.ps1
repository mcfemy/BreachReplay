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

# Package only git-tracked files from backend/ — NOT `scp -r`, which uploads
# whatever happens to be sitting on the local disk verbatim. That's exactly
# what shipped a developer's local, gitignored backend/.env (with a live
# NVIDIA API key) straight to the production box. `git archive` can only
# ever include committed files, so untracked/gitignored content is
# structurally impossible to upload this way.
#
# A plain extraction on top of the destination is additive-only, though —
# it adds/overwrites but never removes. That bit us too: a migration file
# deleted from git 5+ days ago (superseded, on an unmerged branch, by a
# correctly-chained replacement) was still sitting on the server from some
# earlier scp-based deploy, and its stale down_revision produced a second
# Alembic head, breaking `alembic upgrade head` outright. So the archive is
# extracted to a scratch dir, then rsync --delete mirrors it onto the real
# backend/ dir — files git no longer tracks get removed, matching prod to
# HEAD exactly. Two things must never be touched by that mirroring: the
# server's own standing .env (not git-tracked, holds prod secrets) and
# app/uploads/ (not git-tracked, holds real user-uploaded documents from
# the ingestion feature) — both are explicitly excluded.
$BackendArchive = Join-Path $env:TEMP "breachreplay_backend.tar"
git archive --format=tar --output=$BackendArchive HEAD -- backend
if ($LASTEXITCODE -ne 0) { Write-Error "git archive of backend/ failed"; exit 1 }
scp $SSH_OPTS.Split(" ") $BackendArchive "${SSH_TARGET}:/tmp/breachreplay_backend.tar"
if ($LASTEXITCODE -ne 0) { Write-Error "Backend archive upload failed"; exit 1 }
ssh $SSH_OPTS.Split(" ") $SSH_TARGET "rm -rf /tmp/br_backend_new && mkdir -p /tmp/br_backend_new && tar -xf /tmp/breachreplay_backend.tar -C /tmp/br_backend_new && rsync -a --delete --exclude='.env' --exclude='app/uploads/' /tmp/br_backend_new/backend/ /home/ec2-user/breachreplay/backend/ && rm -rf /tmp/br_backend_new /tmp/breachreplay_backend.tar"
if ($LASTEXITCODE -ne 0) { Write-Error "Backend sync failed"; exit 1 }
Remove-Item $BackendArchive -ErrorAction SilentlyContinue

scp $SSH_OPTS.Split(" ") "$ROOT\docker-compose.prod.yml" "${SSH_TARGET}:/home/ec2-user/breachreplay/"
if ($LASTEXITCODE -ne 0) { Write-Error "docker-compose.prod.yml upload failed"; exit 1 }

# nginx config was previously only ever installed once by ec2_setup.sh and
# never touched again by this script — meaning a change committed here
# (like the /health proxy fix) would silently NOT be live until someone
# remembered to apply it by hand. Same drift pattern as the deploy.ps1 fix
# above; sync it on every deploy so the repo is the actual source of truth.
Write-Host "==> Syncing nginx config..."
scp $SSH_OPTS.Split(" ") "$ROOT\nginx\breachreplay.conf" "${SSH_TARGET}:/tmp/breachreplay.conf"
if ($LASTEXITCODE -ne 0) { Write-Error "nginx config upload failed"; exit 1 }
ssh $SSH_OPTS.Split(" ") $SSH_TARGET "sudo cp /tmp/breachreplay.conf /etc/nginx/conf.d/breachreplay.conf && rm -f /tmp/breachreplay.conf && sudo nginx -t && sudo systemctl reload nginx"
if ($LASTEXITCODE -ne 0) { Write-Error "nginx config apply failed, check 'sudo nginx -t' output above"; exit 1 }

Write-Host "==> Uploading frontend build..."
# Stage to a temp dir first (avoids nginx ownership issues on /var/www).
# NOTE: upload the whole "dist" folder, not "dist\*" — PowerShell does not
# glob-expand wildcards for native commands like scp.exe, so a trailing
# "\*" gets passed to scp literally and fails to match anything, leaving
# the remote temp dir empty. rsync --delete against an empty source would
# then wipe the live site. Uploading the folder itself avoids the glob
# entirely; the remote rsync source path is adjusted to match.
# sudo, not plain rm: scp -r has been observed creating the destination
# "dist" directory with a mode that denies write back to its own owner
# (ec2-user) — root can still remove it, ec2-user's own rm cannot, even
# though ec2-user owns it. Confirmed reproducible (hit on consecutive
# deploys) 2026-07-27 deploying the guided-first-run feature: the SAME
# scp -r invocation, unmodified, produced a "dist" dir the owning user
# couldn't delete either before OR after that run's publish. Root cause
# not fully diagnosed (likely an OpenSSH/scp quirk translating the local
# Windows source directory's ACLs), but sudo on both removals sidesteps
# it either way.
ssh $SSH_OPTS.Split(" ") $SSH_TARGET "sudo rm -rf /tmp/br_dist_upload && mkdir -p /tmp/br_dist_upload"
scp $SSH_OPTS.Split(" ") -r "$ROOT\frontend\dist" "${SSH_TARGET}:/tmp/br_dist_upload/"
if ($LASTEXITCODE -ne 0) { Write-Error "Frontend upload failed"; exit 1 }
ssh $SSH_OPTS.Split(" ") $SSH_TARGET "sudo mkdir -p /var/www/breachreplay && sudo rsync -a --delete /tmp/br_dist_upload/dist/ /var/www/breachreplay/ && sudo chown -R nginx:nginx /var/www/breachreplay && sudo rm -rf /tmp/br_dist_upload"
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
