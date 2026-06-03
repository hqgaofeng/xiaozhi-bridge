# Docker Compose 部署

> 推荐的生产部署方式：一个 `docker compose up -d` 启动所有服务

## 1. 前置条件

```bash
# Docker 24+
docker --version

# Docker Compose v2+
docker compose version
```

## 2. 第一次部署

### 2.1 克隆

```bash
git clone https://github.com/hqgaofeng/xiaozhi-bridge.git
cd xiaozhi-bridge
```

### 2.2 配置环境变量

```bash
cp .env.example .env
nano .env

# Also create openclaw.json from template:
cp config/openclaw.json.example config/openclaw.json
nano config/openclaw.json  # fill in MiniMax API key
```

填入：
- `MINIMAX_API_KEY` — MiniMax API key
- `LOG_LEVEL` — `INFO`（生产）/ `DEBUG`（调试）
- 可选：`XIAOZHI_DEVICE__AUTH_TOKEN` — 设备鉴权 token

### 2.3 配置应用

```bash
cp config/config.example.yaml config/config.yaml
nano config/config.yaml
```

### 2.4 修改 Caddy 域名

```bash
nano deploy/Caddyfile
# 把 YOUR_DOMAIN 改成你的实际域名
# 例：xiaozhi.example.com
```

需要先：
- 域名 DNS A 记录指向 VPS IP
- 80/443 端口开放

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

启动后会有 4 个容器：

| 服务 | 端口 | 内存限制 | 说明 |
|---|---|---|---|
| `xiaozhi-openclaw` | 18789 (内) | 800MB | LLM 推理 |
| `xiaozhi-bridge` | 8000 (内) | 200MB | 桥接服务 |
| `xiaozhi-web` | 80 (内) | 50MB | 智控台静态文件 |
| `xiaozhi-caddy` | 80, 443 (外) | 100MB | 反代 + HTTPS |

总内存上限：~1.2GB

## 4. 验证

```bash
# 检查所有服务健康
docker compose ps

# 智控台
curl -I http://localhost:8080

# Bridge WebSocket（应返回 426 Upgrade Required）
curl -I http://localhost:8000/xiaozhi/v1/

# OpenClaw 健康
curl http://localhost:18789/health
```

打开浏览器：
- 本地：http://localhost:8080
- 生产：https://your-domain.com

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

需要备份的：
- `.env`（API key 等）
- `config/config.yaml`（应用配置）
- `deploy/Caddyfile`（HTTPS 配置）
- 命名 volumes（`xiaozhi-bridge_openclaw-data` 等）

```bash
# 备份所有 volumes
docker compose down
sudo tar -czf xiaozhi-backup-$(date +%Y%m%d).tar.gz \
    .env config/config.yaml deploy/Caddyfile \
    /var/lib/docker/volumes/xiaozhi-bridge_*
```

## 7. 开发模式

```bash
# Live reload、debug 端口、源码挂载
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

特点：
- 桥接服务：源码挂载，watchmedo 自动重启
- 智控台：Vite dev server，HMR 热更新
- Caddy：直连无 HTTPS
- 暴露 debugpy 端口 5678

## 8. 故障排查

### 8.1 openclaw 启动失败

```bash
docker compose logs openclaw
```

常见原因：
- `MINIMAX_API_KEY` 无效
- 端口 18789 冲突
- openclaw 镜像不存在（需确认镜像名）

### 8.2 bridge 启动失败

```bash
docker compose logs bridge
```

常见原因：
- `config/config.yaml` 不存在或格式错
- 找不到 `openclaw` 服务（depends_on 等待超时）
- 端口 8000 冲突

### 8.3 设备连不上

检查清单：
- [ ] VPS 防火墙开放 443
- [ ] 域名 DNS 解析正确
- [ ] Caddy 拿到证书：`docker compose logs caddy`
- [ ] 设备的 `WEBSOCKET_URL` 正确
- [ ] 设备的 `Authorization` Bearer token 跟 `XIAOZHI_DEVICE__AUTH_TOKEN` 一致

### 8.4 智控台打不开

- 看 web 容器日志
- 看 Caddy 反代是否转发到 web
- 浏览器 DevTools 看 Network

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
