# SL651-2014 中心站 RTU 调试助手

接收、解析、调试 RTU 按 **SL 651-2014** 上报的报文；含模拟 RTU 与 Web 控制台。

## 功能

| 能力 | 说明 |
|------|------|
| 协议解析 | 帧头 / 正文 / 要素 / CRC16，支持 2F/32/33/34 等 |
| 中心站 TCP | 粘包切分、多 RTU 会话、自动确认 |
| 模拟 RTU | 心跳、定时报、加报，可调水位/雨量/电压 |
| Web 控制台 | Vue3 实时报文、历史分页查询、下行调试 |
| SQLite 持久化 | 上下行报文落库，重启可查 |
| 离线解析 | CLI hex / 文件解析 |

## 前端开发

基于 **Vue 3 + Nuxt UI + Tailwind CSS**。

```bash
# 开发模式（Vite 热更新，代理到后端 8080）
python3 main.py web --port 8080 --tcp-port 9000   # 终端 1
cd web && npm install && npm run dev               # 终端 2 → http://127.0.0.1:5173

# 构建到 sl651/static（生产 / Docker 使用）
cd web && npm run build
```

数据库默认路径：`data/messages.db`，可用环境变量 `SL651_DB` 覆盖。

报文默认只保留最近 **3 天**，超时自动删除并 VACUUM，避免 SQLite 无限膨胀。可用 `SL651_RETENTION_DAYS` 调整天数，设为 `0` 关闭自动清理。

## 安装

```bash
cd sl651
pip install -r requirements.txt
```

## Docker 部署（推荐）

```bash
# 一键构建并启动
./deploy.sh start

# 浏览器打开 Web 控制台
open http://127.0.0.1:8080

# 查看日志 / 停止
./deploy.sh logs
./deploy.sh stop
```

也可用 compose：

```bash
docker compose up -d --build
docker compose logs -f
docker compose down
```

自定义端口：

```bash
WEB_PORT=8088 TCP_PORT=9001 ./deploy.sh start
# 或
WEB_PORT=8088 TCP_PORT=9001 docker compose up -d --build
```

## 本地快速开始

```bash
# 终端 1：启动 Web + 中心站（TCP 9000，Web 8080）
python3 main.py web --port 8080 --tcp-port 9000

# 浏览器打开
open http://127.0.0.1:8080

# 在 Web 页点击「模拟 RTU → 启动」，或终端 2：
python3 main.py rtu --host 127.0.0.1 --port 9000
```

Web 上可：
- 实时看上行/下行报文与解析
- 选择已连接 RTU，按功能码自动生成正文与结束符后下行（37 查实时、38 时段、3A 指定要素、4A 校时、49 改密等）
- 启动/停止内置模拟 RTU，手动触发心跳/定时报/加报
- 离线粘贴 hex 解析；清空报文记录

## 命令一览

```bash
# Web 控制台
python3 main.py web -p 8080 --tcp-port 9000

# 仅 TCP 中心站（无 Web）
python3 main.py listen -p 9000

# 模拟 RTU
python3 main.py rtu --host 127.0.0.1 --port 9000
python3 main.py rtu --once report   # 只发一帧定时报

# 离线解析
python3 main.py parse -f samples/regular_report.hex
python3 main.py parse -x "7E7E..." --json
```

## 端口

| 端口 | 用途 |
|------|------|
| 8080 | Web UI + API + WebSocket |
| 9000 | RTU 接入（SL651 TCP） |

## 目录

```
sl651/
  parser.py / encoder.py / framer.py / crc16.py
  center.py      # 多会话中心站
  bus.py         # 报文事件总线
  rtu.py         # 模拟 RTU
  webapp.py      # FastAPI + WS
  static/        # Web 前端
  cli.py
main.py
```

## API 摘要

- `GET  /api/status` — 中心站 / RTU / 客户端状态
- `GET  /api/messages` — 历史报文
- `POST /api/send` — 下行发送（hex / 按功能码构造帧）
- `POST /api/build-down` — 仅组帧预览（自动正文 + 默认结束符）
- `GET  /api/down-meta` — 功能码 schema / 结束符 / 标识符列表
- `POST /api/parse` — 离线解析
- `POST /api/rtu/start|stop|send` — 模拟 RTU
- `WS   /ws` — 实时推送 `message` / `clients` / `system`
