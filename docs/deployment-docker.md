# Docker Compose 部署

> 推荐的生产部署方式：一个 `docker compose up -d` 启动所有服务

## 1. 前置条件

```bash
# Docker 24+
docker --version

# Docker Compose v2+
docker compose version
```

另外，**本项目使用宿主上已有的 nginx 做 HTTPS 反代**（因为 VPS 上 nginx 已经在 80/443 上服了其他子域名）。需要你的 nginx 跑着、占着 80/443；本项目**不再**起容器内的 caddy（参看 `docker-compose.yml` 中已删除的 caddy service）。

## 2. 第一次部署

### 2.1 克隆

```bash
git clone https://github.com/hqgaofeng/xiaozhi-bridge.git
cd xiaozhi-bridge
```

### 2.2 配置 bridge

```bash
cp config/config.example.yaml config/config.yaml
nano config/config.yaml
```

`config.yaml` 里：

```yaml
openclaw:
  base_url: http://host.docker.internal:18789
  api_key: "<你的 openclaw gateway token>"
  model: openclaw
  user: xiaozhi-bridge
```

`api_key` 在宿主机 `~/.openclaw/openclaw.json` 的 `gateway.auth.token` 字段。
`config.yaml` 在 `.gitignore` 里——不会被 commit。

**V2 #1 起（v0.2.2）还要多一步：下载 sherpa-onnx ASR 模型。**

```bash
# 一次性下载到 host（~500MB）
mkdir -p /opt/xiaozhi-bridge/models
cd /opt/xiaozhi-bridge/models
curl -L -o sherpa-bilingual.tar.bz2 \
  https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20.tar.bz2
tar -xjf sherpa-bilingual.tar.bz2
rm sherpa-bilingual.tar.bz2   # 省 500MB 磁盘

# docker-compose.yml 里 bridge 服务的 volumes 段已包含：
#   /opt/xiaozhi-bridge/models:/opt/xiaozhi-bridge/models:ro
# （V2 #1 改动）所以这一步只需要保证 host 路径有东西。
```

**如果不准备模型**（只跑开发 / 不需要真 ASR），可以在 `config.yaml` 里：

```yaml
asr:
  provider: mock   # 走虚拟抑 ASR，不加载模型
```

### 2.3 准备宿主上的 openclaw（必做）

`xiaozhi-bridge` 通过 `host.docker.internal` 调宿主上的 openclaw，需要
两步让 openclaw 可用：

#### 2.3.1 开启 chatCompletions endpoint

bridge 调 openclaw 的 `/v1/chat/completions`，openclaw 默认**不**暴露这个端点。
在宿主 `~/.openclaw/openclaw.json` 的 `gateway` 块下加：

```json
{
  "gateway": {
    "http": { "endpoints": { "chatCompletions": { "enabled": true } } }
  }
}
```

#### 2.3.2 把 openclaw 绑到非 loopback

openclaw 默认只听 `127.0.0.1`，bridge 容器从 `host.docker.internal` 走不通。
把 `gateway.bind` 改成 `lan`（绑定 0.0.0.0）或 `auto`：

```json
{
  "gateway": {
    "bind": "lan"
  }
}
```

```bash
openclaw config validate    # 确认合法
systemctl --user restart openclaw-gateway
ss -tlnp | grep 18789       # 应看到 0.0.0.0:18789
```

**安全提醒**：`bind: lan` 会让 openclaw 在 VPS 内网所有接口监听。如果你的
VPS 内网有其他租户/不可信用户，**不要**用 `lan`，改用 `custom` 绑一个内网 IP：

```json
{
  "gateway": {
    "bind": "custom",
    "customBindHost": "172.17.0.1"   // docker bridge gateway IP
  }
}
```

### 2.4 准备宿主上的 nginx（必做，因为容器内的 caddy 已删）

本项目**不再**起 caddy service（删了，避免和已有 nginx 抢 80/443）。
改用宿主上已经在 80/443 的 nginx 加一个 server block：

```bash
nano /etc/nginx/conf.d/jarvis.beallen.top.conf
```

```nginx
server {
    listen 80;
    server_name jarvis.beallen.top;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name jarvis.beallen.top;
    ssl_certificate     /etc/letsencrypt/live/jarvis.beallen.top/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/jarvis.beallen.top/privkey.pem;

    # Web 智控台
    location / {
        proxy_pass http://127.0.0.1:5180;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # bridge HTTP API (V2 #3)
    # bridge-api 是独立进程，跑到 8001 端口。
    # proxy_buffering off + 长 read_timeout 让 SSE 日志流能实达。
    location /api/ {
        proxy_pass http://127.0.0.1:8001/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400s;
    }

    # bridge WebSocket
    location /xiaozhi/ {
        proxy_pass http://127.0.0.1:8000/xiaozhi/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 3600s;
    }

    # 健康检查
    location = /health {
        proxy_pass http://127.0.0.1:8000/health;
    }
}
```

签证书：

```bash
certbot certonly --nginx -d jarvis.beallen.top \
  --email you@example.com --agree-tos --no-eff-email
nginx -t && systemctl reload nginx
```

### 2.5 启动

```bash
docker compose up -d
```

查看启动状态：

```bash
docker compose ps
docker compose logs -f
```

## 3. 服务清单

启动后会有 2 个容器（openclaw 在 host 上，不在 docker 里）：

| 服务 | 端口 | 内存限制 | 说明 |
|---|---|---|---|
| `xiaozhi-bridge` | 127.0.0.1:8000 | 200MB | 桥接服务（WebSocket） |
| `xiaozhi-web` | 127.0.0.1:5180 | 50MB | 智控台静态文件 |
| openclaw (host) | 0.0.0.0:18789 | 200-300MB | LLM/agent 运行时 |
| nginx (host) | 80, 443 | - | 反代 + HTTPS |

总内存上限：~500MB（不算 openclaw 和 nginx）

## 4. 验证

```bash
# 检查所有服务健康
docker compose ps

# 智控台 (本机直连)
curl -I http://127.0.0.1:5180

# 域名 HTTPS
curl -I https://jarvis.beallen.top

# Bridge WebSocket (本机直连)
curl -I http://127.0.0.1:8000/xiaozhi/v1/

# OpenClaw 健康 (本机)
curl http://127.0.0.1:18789/health
```

打开浏览器：
- 本地：http://localhost:5180
- 生产：https://jarvis.beallen.top

### 4.1 Smoke test（运行端到端检验脚本）

上面那些 `curl` 只检查进程是否在听端口。**不**检查“设备到
ESR/EL/ML 脑子 + DB 写”这整条链路。运行 `scripts/e2e_smoke.py`
可以验证：

  - WebSocket 握手成功（已修复 websockets 16+ API 变更问题）
  - STT + LLM + TTS 整轮跑完并收到 `tts.stop`
  - `/api/devices` 真出现行（esp32-001 / esp32-002 / unknown）
  - `/api/devices/{id}/conversations` 真返回 N 条
  - Bridge 测试表中有“设备 × 对话”关联

```bash
# 从项目根目录跑，默认指向 https://jarvis.beallen.top
python scripts/e2e_smoke.py

# 跑单个 case（prefix 匹配）
python scripts/e2e_smoke.py --case esp32-001 -v

# 指向本地 bridge
XIAOZHI_BRIDGE_WS_URL=ws://127.0.0.1:8000/xiaozhi/v1/ \
  python scripts/e2e_smoke.py
```

脚本会连续 5 轮以不同 Device-Id 发 hello→listen→stop，并检查
sqlite 中的 conversation 表。期望输出： `5/5 cases landed a
conversation row in sqlite`（V2 #4 之后）。

**V2 #1 还多一个真 ASR smoke**：`scripts/v2_1_asr_smoke.py`
发一段真实中文 wav（从 sherpa-onnx test_wavs 取）过完整链路，
验证 sherpa-onnx 在生产环境里真能转写、且 sqlite 中存了转写
结果。

```bash
# 默认指向 https://jarvis.beallen.top，sherpa-onnx 测试模型
python scripts/v2_1_asr_smoke.py
```

**V2 #2 edge-tts smoke**：v0.2.3 不需要新脚本。`v2_1_asr_smoke.py`
已覆盖 TTS 链路（V1 时代起就用过 mock TTS 跑过），edge-tts 改
默认与否仅影响 TTS 实际声音。在你 flip `config.yaml` 到
`provider: edge` 之前，prod TTS 仍是 mock。**V2 #2.1 (egress 修复) 后**，
要补一个 `scripts/v2_2_tts_smoke.py` 验声音 + server log 有
`edge_tts_synthesis_done` 事件。

**V2 #2 (edge-tts) 部署检查表**：

- [ ] `config/config.yaml`：`tts.provider` 仍为 `mock`（默认）
- [ ] VPS host iptables：`FORWARD` 链验证允许 docker bridge
  egress（v0.2.3 部署时实测是被默认 DROP 拦截，**别 flip 默认**）
- [ ] `bridge` 镜像 ffmpeg 验证（V1 装的，V2 #2 复用）：
  `docker exec xiaozhi-bridge ffmpeg -version | head -1`
- [ ] **V2 #2.1**（egress 修复后）：改 `tts.provider: edge`，
  重启 bridge，跑 `v2_1_asr_smoke.py` 验证 server log 有
  `edge_tts_synthesis_start/done` 事件
- [ ] **V2 #2.1**（egress 修复后）：在容器内 `python3 -c "import
  edge_tts; ..."` 跑连接性 spot-check

预期输出类似：
```
v2-1-asr: 163200 bytes PCM → 85 Opus frames @ 60ms
v2-1-asr: server session_id = 'xiaozhi-4fa60a3f9f90'
label      device              tts.stop  stt_text           db_row_text
v2-1-asr   xiaozhi-4fa60a3f9f90  ✓         这是第一种第二种…   这是第一种第二种…
```

**`✓ tts.stop` 和 `db_row_text` 不为空** 才是 V2 #1 部署验收的两点。
如果脚本卡在 `tts.stop` 上超过 60s，多半是 openclaw thinking 模式
起用了；该脚本设了 120s 总体 deadline，正常情况 30s 内完。

**注意**：v2_1_asr_smoke.py 需要 `opuslib` （bridge 运行时已含，但
本地开发环境要 `pip install opuslib`）。
conversation row in sqlite`。

> 不依赖 pytest，**也不走 CI**（CI 没跑着 openclaw + bridge
> 实例）。它是“人类巡检”工具——升级后、重启后、改动 db 后、调试
> websockets 版本类问题后，手动跑一轮。

## 5. 升级

```bash
git pull
docker compose build --pull
docker compose up -d
```

或者只重建一个服务：

```bash
docker compose build bridge
docker compose up -d bridge
```

## 6. 备份

V1 是无状态的——对话历史是 V2 才有。建议备份：

- `.env`（如果用了 V2 占位变量；V1 不需要）
- `config/config.yaml`（应用配置）
- `config/openclaw.json`（在宿主上，不在项目里）

```bash
# 打包宿主机上的配置
cd /root/projects/xiaozhi-bridge
sudo tar -czf xiaozhi-bridge-config-$(date +%Y%m%d).tar.gz \
    .env config/
```

## 7. 开发模式

```bash
# Live reload、debug 端口、源码挂载
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

特点：
- 桥接服务：源码挂载，watchmedo 自动重启
- 智控台：Vite dev server，HMR 热更新（http://localhost:3000）
- 暴露 debugpy 端口 5678

## 8. 故障排查

### 8.1 openclaw 启动失败（跑在 host 上）

```bash
journalctl --user -u openclaw-gateway -n 50
```

常见原因：
- `gateway.http.endpoints.chatCompletions.enabled` 未设为 `true`
- `gateway.bind` 仍是 `loopback`（bridge 容器走 host.docker.internal 会被拒）
- 端口 18789 冲突

### 8.2 bridge 启动失败

```bash
docker compose logs bridge
```

常见原因：
- `config/config.yaml` 不存在（没 `cp config/config.example.yaml config/config.yaml`）
- `openclaw.api_key` 跟宿主 `~/.openclaw/openclaw.json` 的 `gateway.auth.token` 对不上
- 端口 8000 冲突

### 8.3 设备连不上

检查清单：
- [ ] VPS 防火墙开放 443
- [ ] 域名 DNS 解析正确
- [ ] nginx 拿到证书：`ls -la /etc/letsencrypt/live/<domain>/`
- [ ] nginx 反代生效：`nginx -t && systemctl status nginx`
- [ ] 设备的 `WEBSOCKET_URL` 是 `wss://jarvis.beallen.top/xiaozhi/v1/`
- [ ] 如果设了 `device.auth_token`，设备的 `Authorization: Bearer ...` 跟 `XIAOZHI_DEVICE__AUTH_TOKEN` 一致

### 8.4 智控台打不开

- 看 web 容器日志：`docker logs xiaozhi-web`
- 看 nginx 反代是否转发到 web 5180：`curl -I http://127.0.0.1:5180`（应 200）
- 浏览器 DevTools 看 Network（应看到 `/` 返回 200 + JS bundle）

## 9. 生产优化建议

### 9.1 持久化日志

挂载日志卷到 host：

```yaml
# docker-compose.yml
bridge:
  volumes:
    - ./logs/bridge:/var/log/xiaozhi-bridge
```

### 9.2 镜像加速

使用 `watchtower` 自动更新：

```bash
docker run -d \
  --name watchtower \
  -v /var/run/docker.sock:/var/run/docker.sock \
  containrrr/watchtower \
  xiaozhi-bridge xiaozhi-web
```

### 9.3 监控

接入 Prometheus：

```yaml
# docker-compose.monitoring.yml
prometheus:
  image: prom/prometheus
  volumes:
    - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
  ports:
    - "127.0.0.1:9090:9090"
```

## 10. 卸载

```bash
# 停掉并删除所有容器 + 网络
docker compose down

# 删除所有数据卷（**会丢失对话历史等**）
docker compose down -v

# 删除项目目录
cd .. && rm -rf xiaozhi-bridge
```
