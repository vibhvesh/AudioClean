#!/usr/bin/env bash
set -euo pipefail
if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo bash install-speaker-detection.sh"
  exit 1
fi
APP_DIR="/opt/audioclean"
VENV="$APP_DIR/venv"
if [[ ! -x "$VENV/bin/python" ]]; then
  echo "AudioClean must be installed first."
  exit 1
fi
echo "This adds PyTorch CPU + pyannote.audio. It may download several GB and use substantial RAM."
echo "For a 4 GB VPS, processing will be slow and memory may be insufficient."
read -r -p "Continue installation? [y/N] " answer
[[ "$answer" =~ ^[Yy]$ ]] || exit 0
read -r -s -p "Paste your Hugging Face access token (input hidden): " HF_TOKEN
echo
if [[ -z "$HF_TOKEN" ]]; then echo "No token supplied."; exit 1; fi
mkdir -p /etc/audioclean
umask 077
printf 'HF_TOKEN=%s\n' "$HF_TOKEN" >/etc/audioclean/speaker.env
unset HF_TOKEN
"$VENV/bin/pip" install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
"$VENV/bin/pip" install "pyannote.audio>=4,<5"
mkdir -p /etc/systemd/system/audioclean.service.d
cat >/etc/systemd/system/audioclean.service.d/speaker.conf <<'UNIT'
[Service]
EnvironmentFile=-/etc/audioclean/speaker.env
UNIT
systemctl daemon-reload
systemctl restart audioclean
echo "Speaker detection installed. Open http://YOUR_SERVER_IP:8095 and use Detect speakers."
