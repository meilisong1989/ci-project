# CI/CD 部署手册

本文档说明用例管理平台在一台 Ubuntu 云服务器上的完整发布流程：GitHub 提交触发 Jenkins，Jenkins 构建前后端镜像并推送至阿里云容器镜像服务，再通过 Docker Compose 部署到同一台服务器。

## 1. 架构与职责

```text
开发机 → GitHub（main） → Jenkins 容器 → 阿里云镜像仓库
                                      ↓
                            宿主机 Docker Compose
浏览器 → frontend（Nginx :80） → backend（FastAPI :8080） → postgres
```

| 组件 | 职责 |
| --- | --- |
| `frontend` 镜像 | 使用 Node 22 构建 Vue 静态资源；运行时仅包含 Nginx 和 `dist`。 |
| `backend` 镜像 | 运行 FastAPI/Uvicorn，监听容器内 `8080`。 |
| `postgres` 容器 | 使用官方 `postgres:17-alpine`，数据保存在 Docker volume，不安装宿主机 PostgreSQL。 |
| Jenkins 容器 | 拉取代码、构建镜像、推送仓库、更新部署版本并检查健康状态。 |

前端和后端必须使用两个镜像：它们独立构建、独立版本化；数据库则使用官方镜像和持久化数据卷。

## 2. 仓库与镜像命名

GitHub 仓库分支：`main`。

阿里云镜像仓库：

```text
crpi-fzzu10dkr9pvcmtt.cn-hangzhou.personal.cr.aliyuncs.com/mydev1/dev
```

每次流水线使用 Git 短 SHA 作为镜像版本，例如：

```text
.../dev:frontend-a1b2c3d
.../dev:backend-a1b2c3d
```

不要使用 `latest` 作为生产部署版本；短 SHA 可以精确定位和回滚发布版本。

## 3. 关键项目文件

| 文件 | 用途 |
| --- | --- |
| `Jenkinsfile` | Jenkins 声明式流水线。 |
| `frontend/Dockerfile` | Node 22 构建 Vue，复制 `dist/` 内容至 Nginx 根目录。 |
| `frontend/nginx.conf` | 静态资源和 `/api/` 到后端的反向代理。 |
| `backend/Dockerfile` | Python 3.12/FastAPI 镜像。 |
| `deploy/docker-compose.yml` | 前端、后端、PostgreSQL 的运行编排。 |
| `deploy/init.sql` | PostgreSQL 第一次创建数据卷时执行的初始化 SQL。 |
| `deploy/.env.example` | 不含机密值的变量参考。 |

`deploy/.env` 被 Git 忽略，必须仅保留在服务器上。

## 4. 云服务器准备

### 4.1 Docker 与网络

宿主机需要安装 Docker Engine 和 Docker Compose v2。Ubuntu 可按 Docker 官方安装文档配置 Docker 软件源后安装 `docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin`；安装后验证：

```bash
docker version
docker compose version
```

应用端口：

- `80/tcp`：对公网开放，访问网站。
- `22/tcp`：仅允许管理 IP。
- `8080/tcp`：Jenkins 管理端口；建议只允许管理 IP 或经 HTTPS 反向代理访问。
- `5432/tcp`：不要对公网开放。

### 4.2 部署目录

服务器部署目录固定为 `/opt/ci-project`：

```bash
sudo mkdir -p /opt/ci-project
sudo chown -R 1000:1000 /opt/ci-project
```

将以下文件放入该目录：

```text
docker-compose.yml
init.sql
.env
```

其中前两个来自仓库 `deploy/` 目录，`.env` 在服务器手工创建。

### 4.3 生产 `.env`

在 `/opt/ci-project/.env` 中填写。原始密码用于 PostgreSQL 容器；`POSTGRES_PASSWORD_URLENCODED` 用于后端连接 URL，须是同一密码的 URL 编码值（例如 `@` 编码为 `%40`）：

```env
IMAGE_REPOSITORY=crpi-fzzu10dkr9pvcmtt.cn-hangzhou.personal.cr.aliyuncs.com/mydev1/dev
IMAGE_TAG=initial

POSTGRES_DB=ci-project
POSTGRES_USER=postgres
POSTGRES_PASSWORD=replace_with_a_strong_password
POSTGRES_PASSWORD_URLENCODED=replace_with_the_url_encoded_password
JWT_SECRET=replace_with_a_random_secret_at_least_32_characters
SERVER_PORT=8080
CORS_ORIGINS=*
```

设置文件权限：

```bash
sudo chown 1000:1000 /opt/ci-project/.env
sudo chmod 600 /opt/ci-project/.env
```

首次 `docker compose up` 会创建 PostgreSQL 数据卷并执行 `init.sql`。已有数据卷时，修改 `POSTGRES_PASSWORD` 不会自动修改数据库内用户密码。首次流水线没有可回滚的已发布镜像，若健康检查失败，应查看日志、修复后重新发布；不要依赖 `IMAGE_TAG=initial` 自动回滚。

## 5. Jenkins 容器要求

官方 Jenkins 镜像不自带 Git、Docker CLI 和 Docker Compose 插件。本项目需要自定义镜像；在 `/opt/jenkins/Dockerfile` 创建：

```dockerfile
FROM docker.io/jenkins/jenkins:lts-jdk21
USER root
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl git lsb-release \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://download.docker.com/linux/debian/gpg -o /usr/share/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker.asc] https://download.docker.com/linux/debian $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*
USER jenkins
RUN jenkins-plugin-cli --plugins "git github credentials-binding workflow-aggregator pipeline-model-definition ws-cleanup"
```

在 `/opt/jenkins/compose.yml` 使用：

```yaml
services:
  jenkins:
    build: .
    image: ci-jenkins:latest
    container_name: jenkins
    restart: unless-stopped
    ports: ["8080:8080"]
    group_add: ["${DOCKER_GID}"]
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /opt/ci-project:/opt/ci-project
      - /opt/jenkins/jenkins_home:/var/jenkins_home
```

启动前生成 Socket 的组 ID：

```bash
cd /opt/jenkins
echo "DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)" | sudo tee .env
sudo docker compose -f compose.yml up -d --build
```

验证容器工具和 Socket 权限：

```bash
docker exec jenkins git --version
docker exec jenkins docker version
docker exec jenkins docker compose version
```

`/var/run/docker.sock` 使 Jenkins 能控制宿主机 Docker。因此仅运行受信任仓库的 Pipeline，并限制 Jenkins 管理端口访问。

容器 DNS 必须能解析 GitHub。验证：

```bash
docker exec jenkins getent ahostsv4 github.com
docker exec jenkins git ls-remote -h https://github.com/meilisong1989/ci-project HEAD
```
## 6. Jenkins 任务配置

首次进入 Jenkins 时安装或确认以下插件：Git、Pipeline、GitHub、Credentials Binding、Workspace Cleanup。后者是 `cleanWs(...)` 所必需的插件。

创建类型选择 **Pipeline**，并配置：

```text
Definition:        Pipeline script from SCM
SCM:               Git
Repository URL:    https://github.com/meilisong1989/ci-project.git
Branches to build: */main
Script Path:       Jenkinsfile
```

公开仓库不需要 GitHub 凭据。

在 **Manage Jenkins → Credentials → System → Global credentials** 创建阿里云 Registry 凭据：

```text
Kind:     Username with password
ID:       registry-credentials
Username: 阿里云 Registry 登录用户名
Password: 阿里云 Registry 密码或访问凭据
```

`ID` 必须与 `Jenkinsfile` 完全一致。密码不能写入代码、构建参数或 `.env`。

## 7. GitHub Webhook（自动触发）

在 Jenkins 的 **Manage Jenkins → System → Jenkins Location** 设置一个 GitHub 可访问的 Jenkins URL。若经 Nginx 反向代理，请确保该路径也转发至 Jenkins。

在 GitHub 仓库的 **Settings → Webhooks → Add webhook** 中填写：

```text
Payload URL: https://<Jenkins 域名>/github-webhook/
Content type: application/json
Events: Just the push event
```

推送后在 GitHub 的 Recent Deliveries 中确认返回 2xx。若 Jenkins 的 `8080` 仅允许管理 IP，必须通过 HTTPS 反向代理公开 webhook 路径，或为 GitHub Webhook 配置受控的访问规则。

## 8. 流水线执行逻辑

每次手动构建或推送 `main` 后，流水线依次执行：

1. 拉取 `main` 并取得 Git 短 SHA。
2. 构建前端镜像。Node 22 + pnpm 根据锁文件安装依赖，`pnpm-workspace.yaml` 允许 `esbuild`、`vue-demi` 构建脚本。
3. 构建后端镜像，并运行 `import app.main` 检查。
4. 登录阿里云镜像仓库，推送两个 SHA Tag 镜像。
5. 更新 `/opt/ci-project/.env` 的 `IMAGE_TAG`，执行 `docker compose pull && docker compose up -d --remove-orphans`。
6. 在前端容器内同时请求首页 `/` 和 `/api/health`。
7. 健康检查连续失败时，恢复 `.env.previous` 中的上一个 Tag 并重新部署。

Jenkins 在容器内运行，因此不能使用 Jenkins 容器的 `127.0.0.1` 访问网站；健康检查必须通过 `docker compose exec frontend` 执行。

## 9. 发布与验证

本地提交并推送：

```powershell
cd F:\ai-pri-git\ci-project
git add .
git commit -m "feat: change"
git push origin main
```

手动触发时，在 Jenkins 任务页面选择 **Build Now**。

服务器验证：

```bash
cd /opt/ci-project
docker compose ps
docker compose exec -T frontend wget -q -O - http://127.0.0.1/api/health
docker compose exec -T frontend wget -q -O /dev/null http://127.0.0.1/
```

公网访问：

```text
http://<服务器公网IP>/
http://<服务器公网IP>/api/health
```

前端、后端和数据库均应显示 `healthy`。首次演示账号为 `admin / 123456` 时，必须尽快修改或移除。

## 10. 常见故障排查

### GitHub 无法拉取：`Could not resolve host: github.com`

这是 Jenkins 容器 DNS 问题，不是 Git 凭据问题。检查：

```bash
docker exec jenkins cat /etc/resolv.conf
docker exec jenkins getent ahostsv4 github.com
```

若使用 Podman 的 `docker` 兼容层，容器可能使用 `dns.podman` 网络，和本流水线预期的 Docker Socket 模型不兼容。建议使用 Docker Engine。

### `Invalid option type "timestamps"`

Jenkins 未安装 Timestamper 插件。流水线已经移除该非必要选项；不要重新加入，除非明确安装并维护该插件。

### `pnpm` 要求更高 Node 版本

前端构建使用 `node:22-alpine`。Node 20 与 pnpm 11.22 不兼容。

### `ERR_PNPM_IGNORED_BUILDS`

确认 `frontend/pnpm-workspace.yaml` 存在 `allowBuilds` 配置，并且 Dockerfile 在 `pnpm install` 前复制该文件。

### Jenkins 找不到 `registry-credentials`

在 Jenkins 全局凭据中创建 `Username with password`，ID 必须为 `registry-credentials`。

### 首页返回 Nginx 500，日志含 `internal redirection cycle`

通常是 `/usr/share/nginx/html/index.html` 缺失。前端 Dockerfile 必须使用：

```dockerfile
COPY --from=builder /app/dist/ /usr/share/nginx/html/
```

并在 `frontend/nginx.conf` 中声明相同的站点根目录：

```nginx
root /usr/share/nginx/html;
index index.html;
```

两者共同确保 `index.html` 位于 Nginx 实际使用的站点根目录。

### 部署成功但 Jenkins 健康检查访问不到 `127.0.0.1:80`

Jenkins 在容器中，`127.0.0.1` 指向 Jenkins 自身。通过以下方式检查：

```bash
cd /opt/ci-project
docker compose exec -T frontend wget -q -O - http://127.0.0.1/api/health
```

## 11. 日常运维

查看服务：

```bash
cd /opt/ci-project
docker compose ps
docker compose logs --tail=100 frontend
docker compose logs --tail=100 backend
docker compose logs --tail=100 postgres
```

查看当前部署版本：

```bash
grep '^IMAGE_TAG=' /opt/ci-project/.env
```

手动回滚到某个已发布 SHA：

```bash
cd /opt/ci-project
sed -i 's/^IMAGE_TAG=.*/IMAGE_TAG=<目标短SHA>/' .env
docker compose pull
docker compose up -d --remove-orphans
```

不要删除 `postgres-data` volume；删除它会永久丢失数据库数据。
## 12. 部署难点与注意事项

本节汇总本项目实际部署中出现过、且在同类项目中最容易复发的问题。上线前应逐项检查。

### 12.1 Git 分支、Jenkinsfile 与文件编码

- Jenkins 任务的 `Branches to build` 必须与真实分支一致。本项目使用 `*/main`；保留默认的 `*/master` 会导致无法拉到预期版本。
- Pipeline 类型必须选择 **Pipeline script from SCM**，脚本路径为根目录 `Jenkinsfile`。
- `Jenkinsfile` 应保存为 UTF-8。通过部分 Windows PowerShell 命令改写文件时，可能破坏中文文本或引号，进而导致 Groovy 编译失败。提交前应检查 `git diff`，并在 Jenkins 中用一次构建验证语法。
- GitHub 公开仓库无需 Clone 凭据；`Could not resolve host: github.com` 是 DNS 问题，不是 Token、证书或分支权限问题。

### 12.2 Jenkins 容器与宿主机 Docker 的边界

- 官方 Jenkins 镜像默认没有 Git、Docker CLI 和 Compose 插件，必须使用自定义镜像或独立 Agent 补齐。
- 本方案挂载 `/var/run/docker.sock`，Jenkins 通过宿主机 Docker 构建和运行应用。Socket 或 Docker 组等价于高权限，应仅允许可信管理员和可信仓库使用。
- 不要将 Podman 的 `docker` 兼容层与 Docker Socket 方案混用。Podman 网络、Compose 语义和 Socket 路径不同，容易造成 DNS、构建和部署行为不一致。
- Jenkins 容器的 `127.0.0.1` 指向 Jenkins 容器本身，不是宿主机网站。部署检查必须经由 `docker compose exec frontend`，或显式使用宿主机网络。
- Jenkins 容器必须能解析 GitHub 和镜像仓库域名；先用 `getent ahostsv4 github.com` 验证 DNS，再排查 Git 配置。

### 12.3 前端依赖构建的可重复性

- pnpm 版本必须与 Node 版本兼容。本项目的 pnpm 11.22 需要 Node 22，因此前端构建镜像使用 `node:22-alpine`。
- pnpm 的构建脚本许可写在 `pnpm-workspace.yaml`。Dockerfile 必须在 `pnpm install --frozen-lockfile` 之前复制该文件，否则 `esbuild` 等依赖会被拒绝执行，构建失败。
- 使用 `--frozen-lockfile`，避免 CI 过程悄然改写依赖版本。
- 建议后续在 `package.json` 固定 `packageManager` 版本，并将基础镜像固定到 digest，以增强可重复构建能力。

### 12.4 前端静态文件和 Nginx 反向代理

- Nginx 的 SPA 回退规则依赖站点根目录存在 `index.html`。若日志出现 `rewrite or internal redirection cycle while internally redirecting to "/index.html"`，说明根目录缺少入口文件，浏览器会收到 500。
- Dockerfile 应明确使用：

  ```dockerfile
  COPY --from=builder /app/dist/ /usr/share/nginx/html/
  ```

  这会将构建产物内容放入 Nginx 根目录。
- `/api/health` 返回 200 只代表后端和代理正常；部署健康检查还必须请求首页 `/`，否则静态站点故障会被误判为发布成功。

### 12.5 镜像仓库、机密与配置

- `IMAGE_REPOSITORY` 必须是完整的阿里云镜像地址；前端、后端仅通过 `frontend-<SHA>`、`backend-<SHA>` Tag 区分。
- Jenkins 全局或 Folder 凭据中必须存在 ID 为 `registry-credentials` 的 **Username with password**；凭据 ID 不匹配会在推送阶段失败。
- Registry 密码、数据库密码、JWT 密钥和 Jenkins 密钥不得写入 Git。服务器 `/opt/ci-project/.env` 只保存在主机上，并设置为 `600` 权限。
- 当前 Compose 使用 `POSTGRES_PASSWORD` 初始化数据库，并使用同一密码的 `POSTGRES_PASSWORD_URLENCODED` 拼入 `DB_URL`；两者必须匹配。原密码可包含特殊字符，但 URL 编码值必须正确（例如 `@` 写为 `%40`）。
- 定期轮换 Registry、数据库和 JWT 机密；多人团队应转向 Vault 或云厂商的 Secret/KMS 服务。

### 12.6 数据库、回滚与数据安全

- PostgreSQL 由 Compose 启动，无需在宿主机安装。数据保存在 `postgres-data` volume；绝不能将该 volume 当作普通缓存清理。
- `init.sql` 仅在数据卷第一次创建时执行。后续表结构变更必须使用数据库迁移工具，不能依赖重启容器。
- 首次发布没有可回滚的已发布镜像。当前流水线会先把 `.env` 复制为 `.env.previous`；若首发健康检查失败，回滚逻辑会恢复原来的 `IMAGE_TAG=initial` 并尝试拉取，因此不能作为可靠回滚。首发失败时应保留日志、修复后重新发布；后续发布才具备回滚到上一 SHA Tag 的基础。
- 建立数据库定期备份、异地保存和恢复演练；没有验证过恢复的备份不等于可用备份。

### 12.7 网络、访问控制与发布治理

- 外网访问业务只需要 `80/tcp`（以及后续 HTTPS 的 `443/tcp`）；不要开放 `5432`。
- Jenkins `8080` 应限制管理 IP/VPN，并通过 HTTPS 反向代理暴露 GitHub Webhook 所需的 `/github-webhook/` 路径。
- 推送 `main` 自动部署适合内部测试环境。生产环境建议引入 `dev/test/prod` 环境、分支保护、镜像扫描、人工审批和 Tag 发布。
- 运行中应监控容器状态、CPU/内存、磁盘、数据库容量与镜像空间；同时保留 Jenkins 构建记录和应用日志，便于审计与故障追踪。
