#!/bin/bash
# Runs once as root when the EC2 instance first boots (Amazon Linux 2023)
set -euxo pipefail

# ── System update ─────────────────────────────────────────────────────────────
dnf update -y

# ── Docker ────────────────────────────────────────────────────────────────────
dnf install -y docker
systemctl start docker
systemctl enable docker
usermod -aG docker ec2-user

# Docker Compose v2 plugin
mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL "https://github.com/docker/compose/releases/download/v2.27.0/docker-compose-linux-x86_64" \
     -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
ln -sf /usr/local/lib/docker/cli-plugins/docker-compose /usr/local/bin/docker-compose

# ── Nginx ─────────────────────────────────────────────────────────────────────
dnf install -y nginx
systemctl enable nginx

# ── Node.js 20 (to build React frontend) ─────────────────────────────────────
curl -fsSL https://rpm.nodesource.com/setup_20.x | bash -
dnf install -y nodejs

# ── Git ───────────────────────────────────────────────────────────────────────
dnf install -y git

# ── Certbot (for Let's Encrypt SSL — run manually after domain is pointed) ───
dnf install -y python3-pip
pip3 install certbot certbot-nginx

# ── App directory ─────────────────────────────────────────────────────────────
mkdir -p /home/ec2-user/breachreplay
mkdir -p /var/www/breachreplay
chown ec2-user:ec2-user /home/ec2-user/breachreplay

# ── Systemd service (starts docker-compose on every boot) ────────────────────
cat > /etc/systemd/system/breachreplay.service << 'UNIT'
[Unit]
Description=BreachReplay Application
After=docker.service network-online.target
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/home/ec2-user/breachreplay
ExecStart=/usr/local/bin/docker-compose -f docker-compose.prod.yml up -d --build
ExecStop=/usr/local/bin/docker-compose -f docker-compose.prod.yml down
TimeoutStartSec=300
User=ec2-user
Group=ec2-user

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable breachreplay

echo "==> First-boot setup complete. SSH in and run: bash /home/ec2-user/breachreplay/infra/ec2_setup.sh"
