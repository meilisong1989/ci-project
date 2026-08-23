# 多阶段构建：最终镜像仅保留 Nginx、dist 和代理配置。
FROM node:22-alpine AS builder
WORKDIR /app
RUN corepack enable
COPY package.json ./
COPY pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
