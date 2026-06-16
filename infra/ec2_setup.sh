#!/bin/bash
# Run this ONCE via SSH after copying the project to the EC2 instance.
# Usage: ssh into EC2 then: bash ~/breachreplay/infra/ec2_setup.sh
set -euxo pipefail

APP_DIR="/home/ec2-user/breachreplay"
STATIC_DIR="/var/www/breachreplay"

cd "$APP_DIR"

# ── Validate .env.prod exists ─────────────────────────────────────────────────
if [ ! -f ".env.prod" ]; then
  echo "ERROR: .env.prod not found. Copy .env.prod.example, fill in values, then re-run."
  exit 1
fi

# ── Build React frontend ───────────────────────────────────────────────────────
echo "==> Building frontend..."
cd frontend
npm ci --prefer-offline
VITE_API_URL=https://breachreplay.com/api/v1 \
VITE_WS_URL=wss://breachreplay.com \
  npm run build
cd "$APP_DIR"

# ── Copy static files to nginx root ──────────────────────────────────────────
echo "==> Copying frontend build to $STATIC_DIR..."
sudo mkdir -p "$STATIC_DIR"
sudo cp -r frontend/dist/* "$STATIC_DIR/"
sudo chown -R nginx:nginx "$STATIC_DIR"

# ── Configure nginx ───────────────────────────────────────────────────────────
echo "==> Installing nginx config..."
sudo cp nginx/breachreplay.conf /etc/nginx/conf.d/breachreplay.conf
# Remove the default config that conflicts on port 80
sudo rm -f /etc/nginx/conf.d/default.conf
sudo nginx -t
sudo systemctl restart nginx

# ── Start docker-compose (backend services) ───────────────────────────────────
echo "==> Starting backend services..."
docker compose -f docker-compose.prod.yml pull --ignore-buildable
docker compose -f docker-compose.prod.yml up -d --build

# Wait for DB to be healthy, then run migrations
echo "==> Waiting for database..."
sleep 15
docker compose -f docker-compose.prod.yml exec backend \
  alembic upgrade head

# ── Enable breachreplay systemd service ───────────────────────────────────────
sudo systemctl enable breachreplay

echo ""
echo "==> Setup complete!"
echo ""
echo "NEXT STEP — Enable HTTPS:"
echo "  1. Point breachreplay.com A record → $(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)"
echo "  2. Wait for DNS to propagate (use: https://dnschecker.org)"
echo "  3. Run: sudo certbot --nginx -d breachreplay.com -d www.breachreplay.com --email mcfemy@gmail.com --agree-tos --non-interactive"
echo "  4. Certbot auto-renews via cron — nothing else needed."
