# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |
| < 0.1   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability in xiaozhi-bridge, please report it
privately by emailing the maintainers (see `.github/CODEOWNERS` or repo
description). **Do not** open a public issue.

We will respond within 7 days and provide a fix timeline.

## Security Considerations for Self-Hosting

### WebSocket Authentication

V1 only supports optional Bearer token auth (`device.auth_token` in config).
For production deployments:

- **Always** set a strong `auth_token` in `config/config.yaml`
- **Always** put the bridge behind Caddy (HTTPS) — never expose `ws://` directly
- Rotate the token periodically

### API Keys

- Store API keys in `.env` (loaded by Docker Compose), **not** in `config/config.yaml`
- `.env` is in `.gitignore` — never commit it
- For production, consider a secrets manager (Doppler, Vault, etc.)

### Network Exposure

- Bridge WebSocket (port 8000) should be **internal-only** (bound to 127.0.0.1 in compose)
- Only Caddy (port 80/443) should be exposed to the internet
- If you need direct access for testing, use a VPN or SSH tunnel

### Device Trust

- ESP32 devices send `Device-Id` (MAC) and `Client-Id` (UUID) headers
- V1 does not verify these — V2 will add device allowlist

### Resource Limits

- `docker-compose.yml` sets `mem_limit` on each service to prevent OOM
- `bridge` 200M, `web` 50M, `openclaw` 800M, `caddy` 100M
- Total: ~1.2 GB minimum (with 1G swap)

### Updates

- Watch the GitHub repo for security advisories
- `docker compose pull && docker compose up -d` to update
- Subscribe to releases: https://github.com/hqgaofeng/xiaozhi-bridge/releases

## Known Limitations

V1 has the following known security limitations (acceptable for personal use):

1. No device allowlist — anyone with the Bearer token can connect
2. No rate limiting on WebSocket messages
3. No message size limits beyond `max_message_size` config
4. ASR/TTS API keys are sent in plaintext to the bridge (use HTTPS for the API endpoints)
5. LLM tool calls (V2) will be sandboxed — bridge will only allow whitelisted tools
