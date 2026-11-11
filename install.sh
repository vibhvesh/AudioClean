#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/audioclean"
REPO="https://github.com/vibhvesh/AudioClean.git"
SERVICE_USER="audioclean"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Please run with sudo: sudo bash install.sh"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv python3-pip ffmpeg git

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
fi

if [[ -d "$APP_DIR/.git" ]]; then
  git -C "$APP_DIR" pull --ff-only
else
  mkdir -p "$APP_DIR"
  git clone "$REPO" "$APP_DIR"
fi

python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

mkdir -p "$APP_DIR/data/original" "$APP_DIR/data/cleaned"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR"

cat >/etc/systemd/system/audioclean.service <<'UNIT'
[Unit]
Description=Canberra AudioClean API and Web GUI
After=network.target

[Service]
Type=simple
User=audioclean
Group=audioclean
WorkingDirectory=/opt/audioclean
ExecStart=/opt/audioclean/venv/bin/uvicorn app:app --host 0.0.0.0 --port 8095
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now audioclean
echo
echo "Canberra AudioClean installed."
echo "GUI:    http://YOUR_SERVER_IP:8095"
echo "Health: http://YOUR_SERVER_IP:8095/health"
echo "API:    POST http://YOUR_SERVER_IP:8095/api/v1/enhance"
echo "Logs:   sudo journalctl -u audioclean -f"
echo
echo "Note: Restrict port 8095 with your firewall or reverse proxy before exposing it publicly."
