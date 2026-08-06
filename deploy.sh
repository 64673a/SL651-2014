#!/usr/bin/env bash
# SL651 中心站调试助手 — 简单部署脚本
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

IMAGE="${IMAGE:-sl651-center:latest}"
NAME="${NAME:-sl651-center}"
WEB_PORT="${WEB_PORT:-9080}"
TCP_PORT="${TCP_PORT:-9090}"
AUTO_ACK="${AUTO_ACK:-1}"

usage() {
  cat <<EOF
用法: $0 <命令>

命令:
  build     构建 Docker 镜像
  start     构建（如需）并启动容器
  stop      停止并删除容器
  restart   重启
  logs      查看日志（Ctrl+C 退出）
  status    查看容器状态
  shell     进入容器 shell

环境变量:
  WEB_PORT=8080   Web 端口映射
  TCP_PORT=9000   RTU TCP 端口映射
  AUTO_ACK=1      是否自动应答（0 关闭）
  IMAGE=...       镜像名
  NAME=...        容器名

示例:
  $0 start
  WEB_PORT=8088 TCP_PORT=9001 $0 start
  $0 logs
  $0 stop
EOF
}

need_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "错误: 未找到 docker，请先安装 Docker" >&2
    exit 1
  fi
}

cmd_build() {
  need_docker
  echo "==> 构建镜像 ${IMAGE}"
  docker build -t "${IMAGE}" .
  echo "==> 构建完成"
}

cmd_start() {
  need_docker
  if ! docker image inspect "${IMAGE}" >/dev/null 2>&1; then
    cmd_build
  fi

  if docker ps -a --format '{{.Names}}' | grep -qx "${NAME}"; then
    echo "==> 容器 ${NAME} 已存在，先移除"
    docker rm -f "${NAME}" >/dev/null
  fi

  ACK_ARGS=()
  if [ "${AUTO_ACK}" = "0" ]; then
    ACK_ARGS=(--no-ack)
  fi

  echo "==> 启动 ${NAME}"
  echo "    Web  http://127.0.0.1:${WEB_PORT}"
  echo "    RTU  TCP 0.0.0.0:${TCP_PORT}"

  DATA_DIR="${DATA_DIR:-$ROOT/data}"
  mkdir -p "${DATA_DIR}"

  # 挂载宿主机时区文件（与宿主机北京时间对齐）
  TZ_MOUNTS=()
  if [ -f /etc/localtime ]; then
    TZ_MOUNTS+=(-v /etc/localtime:/etc/localtime:ro)
  fi
  if [ -f /etc/timezone ]; then
    TZ_MOUNTS+=(-v /etc/timezone:/etc/timezone:ro)
  fi

  docker run -d \
    --name "${NAME}" \
    --restart unless-stopped \
    -p "${WEB_PORT}:8080" \
    -p "${TCP_PORT}:9000" \
    -e TZ=Asia/Shanghai \
    -e WEB_HOST=0.0.0.0 \
    -e WEB_PORT=8080 \
    -e TCP_PORT=9000 \
    -e AUTO_ACK="${AUTO_ACK}" \
    -e SL651_DB=/data/messages.db \
    -v "${DATA_DIR}:/data" \
    "${TZ_MOUNTS[@]+"${TZ_MOUNTS[@]}"}" \
    "${IMAGE}" \
    python main.py web --host 0.0.0.0 --port 8080 --tcp-port 9000 "${ACK_ARGS[@]+"${ACK_ARGS[@]}"}"

  echo "==> 已启动"
  echo "    打开浏览器: http://127.0.0.1:${WEB_PORT}"
  echo "    查看日志:   $0 logs"
}

cmd_stop() {
  need_docker
  if docker ps -a --format '{{.Names}}' | grep -qx "${NAME}"; then
    echo "==> 停止并删除 ${NAME}"
    docker rm -f "${NAME}" >/dev/null
    echo "==> 已停止"
  else
    echo "容器 ${NAME} 不存在"
  fi
}

cmd_restart() {
  cmd_stop
  cmd_start
}

cmd_logs() {
  need_docker
  docker logs -f --tail 200 "${NAME}"
}

cmd_status() {
  need_docker
  docker ps -a --filter "name=^${NAME}$" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
}

cmd_shell() {
  need_docker
  docker exec -it "${NAME}" /bin/sh
}

case "${1:-}" in
  build)   cmd_build ;;
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  restart) cmd_restart ;;
  logs)    cmd_logs ;;
  status)  cmd_status ;;
  shell)   cmd_shell ;;
  -h|--help|help|"") usage ;;
  *)
    echo "未知命令: $1" >&2
    usage
    exit 1
    ;;
esac
