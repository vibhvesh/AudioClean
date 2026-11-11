# Canberra AudioClean

A small, CPU-only audio cleanup service for radio/PTT recordings. Includes a web review page and a FastAPI endpoint.

## Install on Ubuntu

```bash
curl -fsSL https://raw.githubusercontent.com/vibhvesh/AudioClean/main/install.sh | sudo bash
```

Open `http://YOUR_SERVER_IP:8095`.

## What this first release does

- Accepts WAV, MP3, M4A and OGG input (FFmpeg decodes to mono 16 kHz).
- Applies a speech-focused band-pass filter and a conservative spectral gate.
- Keeps the original recording and writes a separate enhanced WAV.
- Provides a small web page for upload and before/after playback.
- Exposes a health endpoint and an enhancement API.

**Important:** v0.1 is a DSP baseline, not an AI speech-enhancement model. GTCRN/RNNoise integration, automatic noise classification, region-level editing and persistent annotation review are future work. The noise tag is currently saved in the API response only; it does not select a different processing model. Overlapping speech and clipped/missing speech are not reconstructed.

## API

`GET /health`

`POST /api/v1/enhance` as multipart form data:
- `file`: audio file
- `tag`: optional label

Example:

```bash
curl -X POST http://localhost:8095/api/v1/enhance \
  -F "file=@radio-recording.mp3" \
  -F "tag=Static / hiss"
```

The response includes `job_id`, `original_url`, and `enhanced_url`.

## Service management

```bash
sudo systemctl status audioclean
sudo journalctl -u audioclean -f
sudo systemctl restart audioclean
```

## Security

The service listens on port 8095 on all interfaces and has no built-in authentication in this first release. Do not expose it directly to the public internet. Restrict access with a firewall, VPN, or authenticated reverse proxy.

## Requirements

Ubuntu 22.04/24.04/26.04, Python 3, FFmpeg. Designed as a lightweight CPU baseline; benchmark on your actual VPS before production use.
