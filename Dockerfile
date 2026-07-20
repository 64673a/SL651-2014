# ── 阶段 1：构建 Vue 前端 ──────────────────────────────
FROM node:20-alpine AS frontend
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm install
COPY web/ ./
# 输出到 /out，避免依赖宿主机相对路径
RUN npx vite build --outDir /out --emptyOutDir

# ── 阶段 2：Python 运行时 ──────────────────────────────
FROM python:3.11-slim
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=8080 \
    TCP_PORT=9000 \
    AUTO_ACK=1 \
    SL651_DB=/data/messages.db

# 时区优先由运行时挂载宿主机 /etc/localtime 对齐；TZ 作兜底
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple

COPY main.py .
COPY sl651/ ./sl651/
COPY samples/ ./samples/
# 覆盖为 Vue 构建产物
RUN rm -rf ./sl651/static
COPY --from=frontend /out ./sl651/static

RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8080 9000

CMD ["sh", "-c", "python main.py web --host ${WEB_HOST} --port ${WEB_PORT} --tcp-port ${TCP_PORT} $([ \"${AUTO_ACK}\" = \"0\" ] && echo --no-ack || true)"]
