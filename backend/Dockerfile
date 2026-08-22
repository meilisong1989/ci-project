# 构建阶段安装依赖，运行阶段只复制运行所需文件。
FROM python:3.12-alpine AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.12-alpine
WORKDIR /app
COPY --from=builder /wheels /wheels
RUN pip install --no-cache /wheels/* && rm -rf /wheels
COPY app ./app
EXPOSE 8080
# SERVER_PORT 可由 Compose 覆盖；默认 8080。
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${SERVER_PORT:-8080}"]
