# 部署指南

> 把 xiaozhi-bridge 部署到生产 VPS 的完整步骤

## 1. 硬件要求

**最低配置**：
- CPU：1 核
- 内存：1GB（+ 1GB swap 凑合）
- 磁盘：10GB
- 系统：Ubuntu 24.04 LTS（推荐）

**推荐配置**：
- CPU：2 核
- 内存：2GB
- 磁盘：20GB

> ⚠️ **V1 单设备运行时 1GB + 1GB swap 勉强可用**。多设备或启用本地 ASR (FunASR) 时建议 4GB+。

## 2. 系统依赖

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install -y \
    python3.12 python3.12-venv python3-pip \
    nodejs npm \
    libopus0 libopus-dev \
    ffmpeg \
    build-essential git curl

# 启用 pnpm
npm install -g pnpm
```

## 3. 部署 openclaw（前置）

如果还没有 openclaw：

```bash
# 按 openclaw 官方文档安装
curl -fsSL https://docs.openclaw.ai/install | bash
openclaw onboard
# 选 minimax-cn-api，填入 MiniMax API key
```

验证 openclaw 跑起来：
```bash
curl http://127.0.0.1:18789/health
```

## 4. 部署 xiaozhi-bridge

### 方式 A：一键脚本

```bash
git clone https://github.com/hqgaofeng/xiaozhi-bridge /root/projects/xiaozhi-bridge
cd /root/projects/xiaozhi-bridge
./deploy/scripts/install.sh
```

### 方式 B：手动

```bash
# 1. 克隆
git clone https://github.com/hqgaofeng/xiaozhi-bridge /root/projects/xiaozhi-bridge

# 2. Python 桥接
cd /root/projects/xiaozhi-bridge/bridge
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 3. Web 智控台
cd /root/projects/xiaozhi-bridge/web
pnpm install
pnpm build

# 4. 配置
cd /root/projects/xiaozhi-bridge
cp config/config.example.yaml config/config.yaml
nano config/config.yaml  # 填入 key 等

# 5. systemd
sudo cp deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now xiaozhi-bridge xiaozhi-web

# 6. 日志目录
sudo mkdir -p /var/log/xiaozhi-bridge
sudo chown -R $USER /var/log/xiaozhi-bridge
```

## 5. 反向代理（HTTPS）

### 用 Caddy（推荐）

```bash
# 安装 Caddy
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/deb.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy

# 部署配置
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile  # 改 YOUR_DOMAIN
sudo systemctl reload caddy
```

Caddy 会自动申请 Let's Encrypt 证书。

### 用 nginx

参见 `deploy/nginx.conf.example`（待补充）。

## 6. 配置 ESP32 固件

烧录 xiaozhi-esp32 固件后，修改 `WEBSOCKET_URL`：

```cpp
// main/application.cc 或配置文件中
#define WEBSOCKET_URL "ws://your-vps-ip:8000/xiaozhi/v1/"
// 或 HTTPS：
#define WEBSOCKET_URL "wss://xiaozhi.example.com/xiaozhi/v1/"
```

重新烧录，连接 Wi-Fi，设备就会连到你的后端。

## 7. 验证

```bash
# 检查服务状态
sudo systemctl status xiaozhi-bridge xiaozhi-web

# 实时日志
sudo journalctl -u xiaozhi-bridge -f

# 测试 WebSocket 连接
wscat -c ws://localhost:8000/xiaozhi/v1/
# 发送：{"type":"hello","version":1,"features":{"mcp":true},"transport":"websocket","audio_params":{"format":"opus","sample_rate":16000,"channels":1,"frame_duration":60}}
# 应该收到：{"type":"hello","transport":"websocket","session_id":"...","audio_params":{...}}
```

打开浏览器：
- 智控台：http://your-vps-ip:3000
- API 文档：http://your-vps-ip:8000/docs（V2）

## 8. 升级

```bash
cd /root/projects/xiaozhi-bridge
./deploy/scripts/update.sh
```

## 9. 常见问题

### 9.1 启动失败：`Address already in use`

端口 8000/3000 被占用：
```bash
sudo lsof -i :8000
# 杀掉占用进程
```

### 9.2 设备连不上

检查清单：
- [ ] 服务器防火墙开放 8000 端口（或 443 给 wss）
- [ ] 设备的 `WEBSOCKET_URL` 正确
- [ ] 服务在运行：`sudo systemctl status xiaozhi-bridge`
- [ ] 日志无错误：`journalctl -u xiaozhi-bridge -n 50`

### 9.3 ASR 报错

Mock 模式不会报错。真接阿里云/讯飞时：
- 检查 API key 是否正确
- 检查网络：`curl https://api.aliyun.com`
- 查看详细日志：`logging.level: DEBUG`

### 9.4 openclaw 调不通

```bash
# 测试 openclaw HTTP API
curl -X POST http://127.0.0.1:18789/v1/messages \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{"model":"minimax/MiniMax-M3","max_tokens":50,"messages":[{"role":"user","content":"hi"}]}'
```

如果不通，先解决 openclaw 的问题，再来跑 bridge。

### 9.5 内存不够

openclaw + bridge 吃 600-800MB 内存。VPS 1GB 时：
```bash
# 加 swap
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

或者升级 VPS 到 2GB。

## 10. 监控（可选 V2）

- 用 `systemd` 自带的资源监控
- 用 `node_exporter` + Prometheus
- 用 `uptime-kuma` 做健康检查页面

## 11. 备份

V1 几乎无状态，对话历史是 V2 才有。建议备份：
- `/root/projects/xiaozhi-bridge/config/config.yaml`
- `/var/log/xiaozhi-bridge/`（日志）
