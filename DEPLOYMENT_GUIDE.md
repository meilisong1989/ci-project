# CI/CD 部署手册

本文档说明用例管理平台在一台 Ubuntu 云服务器上的完整发布流程：GitHub 提交触发 Jenkins，Jenkins 构建前后端镜像并推送至阿里云容器镜像服务，再通过 Docker Compose 部署到同一台服务器。

## 1. 架构与职责

```text
开发机 → GitHub（main） → Jenkins 容器 → 阿里云镜像仓库
                                      ↓
                            宿主机 Docker Compose
浏览器 → frontend（Nginx :80） → backend（FastAPI :8080） → postgres
```

| 组件            | 职责                                                               |
| ------------- | ---------------------------------------------------------------- |
| `frontend` 镜像 | 使用 Node 22 构建 Vue 静态资源；运行时仅包含 Nginx 和 `dist`。                    |
| `backend` 镜像  | 运行 FastAPI/Uvicorn，监听容器内 `8080`。                                 |
| `postgres` 容器 | 使用官方 `postgres:17-alpine`，数据保存在 Docker volume，不安装宿主机 PostgreSQL。 |
| Jenkins 容器    | 拉取代码、构建镜像、推送仓库、更新部署版本并检查健康状态。                                    |

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

| 文件                          | 用途                                       |
| --------------------------- | ---------------------------------------- |
| `Jenkinsfile`               | Jenkins 声明式流水线。                          |
| `frontend/Dockerfile`       | Node 22 构建 Vue，复制 `dist/` 内容至 Nginx 根目录。 |
| `frontend/nginx.conf`       | 静态资源和 `/api/` 到后端的反向代理。                  |
| `backend/Dockerfile`        | Python 3.12/FastAPI 镜像。                  |
| `deploy/docker-compose.yml` | 前端、后端、PostgreSQL 的运行编排。                  |
| `deploy/init.sql`           | PostgreSQL 第一次创建数据卷时执行的初始化 SQL。          |
| `deploy/.env.example`       | 不含机密值的变量参考。                              |

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

## 8. Jenkinsfile 核心流水线：提交、打包、推送、部署如何串起来

本项目每次发布都以 Git 提交的短 SHA 作为版本号（`TAG`）。前端和后端虽然分别构建为两个镜像，但它们使用同一个 `TAG`，因此可以准确追溯“线上这一版对应哪一次代码提交”。

```text
开发者 git push main
        │
        ├─ GitHub Webhook 请求 /github-webhook/
        ▼
Jenkins 读取 Jenkinsfile，并 checkout 本次构建所解析到的 main 提交
        ▼
TAG = git rev-parse --short HEAD
        ▼
构建 frontend-TAG 镜像  +  构建 backend-TAG 镜像
        ▼
推送两个镜像到阿里云镜像仓库
        ▼
将云服务器 /opt/ci-project/.env 中 IMAGE_TAG 更新为 TAG
        ▼
docker compose pull && docker compose up -d
        ▼
容器内检查首页 / 和接口 /api/health
        ├─ 成功：本次发布完成
        └─ 失败：恢复 .env.previous 中的上一个 TAG 后重新部署
```

### 8.1 任务开始前：Jenkins 从哪里得到代码

Jenkins 任务配置中的仓库地址和分支 `*/main` 决定了构建的来源。每次手动点击 **Build Now**，或 GitHub Webhook 收到 `main` 的 Push 事件，都会开始一次流水线。

Jenkins 有两次与 SCM 相关的动作，目的不同：

1. **读取 Jenkinsfile**：任务为“Pipeline script from SCM”时，Jenkins 先从 GitHub 获取仓库根目录的 `Jenkinsfile`，知道本次该执行什么流程。
2. **拉取完整工作区代码**：流水线的 `Checkout` 阶段执行 `checkout scm`。因为全局配置了 `skipDefaultCheckout()`，Jenkins 不会隐式拉取代码，而是由这一步显式完成，避免取代码时机不清楚。

```groovy
stage('Checkout') {
  steps {
    checkout scm
    script {
      env.TAG = sh(
        script: 'git rev-parse --short HEAD',
        returnStdout: true
      ).trim()
    }
  }
}
```

`git rev-parse --short HEAD` 的输出，例如 `bdec71c`，被保存为环境变量 `TAG`。后续所有镜像名称和部署引用都使用这个值；它就是本次发布的“版本号”。

> `disableConcurrentBuilds()` 会阻止两次发布同时修改服务器上的 `.env` 和容器；`buildDiscarder(...)` 只保留最近 20 次构建记录。两者都是为了让部署过程可预测。

### 8.2 打包前端：实际执行什么命令

前端阶段执行的核心命令是：

```bash
docker build --pull -t $IMAGE_REPOSITORY:frontend-$TAG frontend
```

各参数含义如下：

| 部分 | 实际值/作用 |
| --- | --- |
| `frontend` | Docker 构建上下文，即仓库中的 `frontend/` 目录；使用该目录的 `Dockerfile`。 |
| `--pull` | 每次构建前尝试拉取最新基础镜像，避免长期使用本机陈旧的基础镜像缓存。 |
| `$IMAGE_REPOSITORY` | 阿里云仓库地址：`crpi-fzzu10dkr9pvcmtt.cn-hangzhou.personal.cr.aliyuncs.com/mydev1/dev`。 |
| `frontend-$TAG` | 前端镜像标签，例如 `frontend-bdec71c`。 |

`frontend/Dockerfile` 内部再完成前端真正的“打包”：使用 Node 22、`corepack enable`、`pnpm install --frozen-lockfile` 和 `pnpm build`。构建出的 `dist/` 静态文件被复制到最终的 Nginx 镜像中。因此线上前端容器运行的是 Nginx，不需要 Node 或 pnpm。

### 8.3 打包后端：构建后立即做最小校验

后端阶段的命令是：

```bash
docker build --pull -t $IMAGE_REPOSITORY:backend-$TAG backend
docker run --rm $IMAGE_REPOSITORY:backend-$TAG python -c "import app.main; print('backend import check passed')"
```

第一行以 `backend/` 为构建上下文，生成标签如 `backend-bdec71c` 的镜像。第二行临时启动这个刚构建的镜像，只验证 Python 能成功导入 FastAPI 应用入口 `app.main`；`--rm` 表示检查结束后自动删除临时容器。

这不是完整接口测试，也不会连接 PostgreSQL。它的价值是提前拦截依赖缺失、模块路径错误、启动入口语法错误等基础问题，避免把明显不可启动的镜像推到仓库。

### 8.4 推送镜像：凭据、产物和版本如何对应

构建成功后，流水线从 Jenkins 凭据库中读取 ID 为 `registry-credentials` 的用户名和密码：

```groovy
withCredentials([usernamePassword(
  credentialsId: 'registry-credentials',
  usernameVariable: 'REGISTRY_USER',
  passwordVariable: 'REGISTRY_TOKEN'
)]) {
  sh '''
    echo "$REGISTRY_TOKEN" | docker login "$REGISTRY_HOST" -u "$REGISTRY_USER" --password-stdin
    docker push $IMAGE_REPOSITORY:frontend-$TAG
    docker push $IMAGE_REPOSITORY:backend-$TAG
  '''
}
```

这里不会把密码写进代码或控制台参数中。`docker login` 只在 Jenkins 运行环境中建立到私有仓库的登录状态，然后把两份产物推送出去：

```text
同一 Git 提交 bdec71c
 ├─ frontend-bdec71c   ← 前端 Nginx + dist 静态资源
 └─ backend-bdec71c    ← FastAPI 应用
```

推送成功是部署的前提。当前 Jenkins 与业务容器在同一台云主机，且 Jenkins 容器挂载了 Docker Socket；因此后续 `docker compose pull` 使用的是同一台主机的 Docker 引擎。流水线此处不执行 `docker logout`，以保留私有仓库拉取镜像所需的登录状态。

### 8.5 部署：服务器上的哪个文件被改、运行什么命令

部署阶段并不把源代码复制到线上运行。它只同步 Compose 编排文件、修改部署目录的镜像版本，然后让 Docker 拉取刚推送的镜像：

```bash
test -f deploy/docker-compose.yml
test -f $DEPLOY_PATH/.env
cp deploy/docker-compose.yml $DEPLOY_PATH/docker-compose.yml
cd $DEPLOY_PATH
cp .env .env.previous
sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=$TAG/" .env
docker compose pull
docker compose up -d --remove-orphans
```

这几行按顺序表示：

1. 检查代码仓库中存在 `deploy/docker-compose.yml`，并检查云服务器已有敏感配置 `/opt/ci-project/.env`；如果 `.env` 不存在，立即失败，防止使用默认值误部署。
2. 将本次代码仓库中的 Compose 文件复制到 `/opt/ci-project/docker-compose.yml`，使编排定义能随代码演进；数据库密码、JWT 密钥等仍只保留在服务器 `.env`，不会被 Git 覆盖。
3. 先把当前 `.env` 备份为 `.env.previous`，为回滚保留上一版 `IMAGE_TAG`。
4. 用 `sed` 将 `IMAGE_TAG` 变成当前提交的 SHA。
5. `docker compose pull` 根据 `.env` 中的 `IMAGE_REPOSITORY` 和新 `IMAGE_TAG` 拉取 `frontend-$TAG`、`backend-$TAG`；PostgreSQL 使用公开的 `postgres:17-alpine` 镜像。
6. `docker compose up -d --remove-orphans` 在后台创建或更新容器，并清理由旧 Compose 定义遗留、但当前已不再定义的容器。

`deploy/docker-compose.yml` 将镜像引用拼成：

```yaml
frontend: ${IMAGE_REPOSITORY}:frontend-${IMAGE_TAG}
backend:  ${IMAGE_REPOSITORY}:backend-${IMAGE_TAG}
```

因此 `.env` 中单独变更一次 `IMAGE_TAG=bdec71c`，会把前后端一起切换到同一提交版本。Compose 同时创建内部网络，前端通过服务名 `backend` 代理 `/api/` 请求；PostgreSQL 数据保存在命名卷 `postgres-data`，不会因为应用容器更新而被删除。

### 8.6 发布验证与自动回滚：检查在哪里执行

部署后最多检查 6 次、每次间隔 10 秒：

```bash
cd "$DEPLOY_PATH"
docker compose exec -T frontend sh -ec \
  'wget -q -O /dev/null http://127.0.0.1/ && \
   wget -q -O - http://127.0.0.1/api/health'
```

命令在 **frontend 容器内部** 执行，而不是 Jenkins 容器或 Jenkins 所在主机的 `127.0.0.1`：

- `http://127.0.0.1/` 检查 Nginx 是否能正常返回前端首页；
- `http://127.0.0.1/api/health` 检查 Nginx 的 `/api/` 反向代理、后端服务及健康接口是否连通；
- `-T` 禁用伪终端，适合 Jenkins 非交互环境；任一 `wget` 失败都会使本次检查返回非零。

6 次都失败时，流水线执行：

```bash
cd $DEPLOY_PATH
cp .env.previous .env
docker compose pull
docker compose up -d --remove-orphans
```

也就是恢复上一次 `.env` 记录的 `IMAGE_TAG`，重新拉取并启动上一个前后端镜像版本，随后将构建标记为失败。**首次发布没有有效的上一版本时无法可靠回滚**：`IMAGE_TAG=initial` 只是示例值，必须先确认它存在，或者在首次发布失败后修复问题并重新发布。

### 8.7 一次发布的状态流转速查

| 阶段 | 输入 | 产生/修改的结果 | 下游如何使用 |
| --- | --- | --- | --- |
| GitHub Push | `main` 上的一次提交 | Git SHA，例如 `bdec71c` | Webhook 触发 Jenkins。 |
| Checkout | Jenkins 任务 SCM 配置 | 完整工作区、`TAG=bdec71c` | 两个 `docker build` 都使用该 TAG。 |
| Build | `frontend/`、`backend/` 和 Dockerfile | 本机镜像 `frontend-bdec71c`、`backend-bdec71c` | Push 阶段上传到私有仓库。 |
| Push | 两个本地镜像、Jenkins 仓库凭据 | 阿里云私有仓库中的两个可追溯版本标签镜像 | `docker compose pull` 从这里下载。 |
| Deploy | `/opt/ci-project/.env`、Compose 文件 | `.env` 的 `IMAGE_TAG=bdec71c`、运行中的容器 | Compose 用变量解析具体镜像地址。 |
| Health Check | 新运行的 frontend/backend/postgres | 成功，或恢复 `.env.previous` | 决定 Jenkins 构建最终成功/失败。 |

如果 GitHub Webhook 暂时未配置或公网不可达，仍可在 Jenkins 页面手动点击 **Build Now**；其后的 Checkout、打包、推送、部署和验证链路完全相同。
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

手动回滚到某个已发布 SHA

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
