# Case Management Platform

用例管理平台：Vue 3 前端、FastAPI 后端、PostgreSQL 与 Docker Compose。

```text
浏览器 → Nginx（frontend:80）→ /api → FastAPI（backend:8080）→ PostgreSQL
GitHub main push → Jenkins → 阿里云容器镜像服务 → 云服务器 Docker Compose
```

默认初始化账号仅用于本地演示：`admin / 123456`。部署到任何可访问环境后必须立即修改或移除该账号。

## 本地开发

后端需要 Python 3.12 与 PostgreSQL；前端需要 Node.js 20 和 pnpm。Windows 可使用：

```powershell
.\start.ps1
```

该脚本仅用于本地开发，不能用于生产部署。

## 生产发布

本项目的正式发布链路为 GitHub → Jenkins → 阿里云容器镜像服务 → 云服务器。完整的服务器准备、Jenkins 凭据、GitHub Webhook、回滚与验证步骤见 [deploy.md](deploy.md)。

镜像仓库使用单仓库（默认配置为阿里云 Registry 的
`crpi-fzzu10dkr9pvcmtt.cn-hangzhou.personal.cr.aliyuncs.com/mydev1/dev`）：

```text
<镜像仓库>:frontend-<commit-sha>
<镜像仓库>:backend-<commit-sha>
```

如不使用 Jenkins，也可以在安装 Docker 的 Windows 主机上手动构建并推送两个镜像：

```powershell
# 先执行 docker login，或传入 -Registry、-RegistryUser、-RegistryToken
.\build-push-images.ps1 -ImageRepository "<镜像仓库>" -ImageTag "v1"
```

脚本会分别构建并推送 `frontend-v1` 与 `backend-v1`；部署时将这两个参数分别写入
`IMAGE_REPOSITORY` 和 `IMAGE_TAG`。

服务器上的部署文件位于 `/opt/ci-project`，其中 `.env` 为生产机密配置，已被 `.gitignore` 忽略，绝不能提交。
