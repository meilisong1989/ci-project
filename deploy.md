# GitHub → Jenkins → 阿里云容器镜像服务 → 云服务器部署手册

本项目使用一个镜像仓库（当前配置为阿里云 Registry 的
`crpi-fzzu10dkr9pvcmtt.cn-hangzhou.personal.cr.aliyuncs.com/mydev1/dev`）。前端与后端镜像分别以
`frontend-<Git提交短SHA>` 和 `backend-<Git提交短SHA>` 为 Tag 发布。

## 0. 发布前准备

- GitHub 上创建一个公开仓库，并将本项目代码推送到 `main` 分支。
- 容器镜像服务中已创建目标仓库。
- 云服务器的安全组只开放 `22`（仅你的管理 IP）、`80`；Jenkins 的 `8080` 仅允许你的管理 IP 和 GitHub Webhook 访问。
- 生产数据库端口 `5432` 不开放公网。

## 1. 云服务器安装 Docker

在 Ubuntu 服务器执行：

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git docker.io docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

重新登录 SSH 后验证：

```bash
docker version
docker compose version
```

## 2. 初始化应用部署目录

```bash
sudo mkdir -p /opt/ci-project
sudo chown -R $USER:$USER /opt/ci-project
cd /opt/ci-project
```

从 GitHub 仓库复制 `deploy/docker-compose.yml`、`deploy/init.sql` 和 `deploy/.env.example` 到这个目录；然后：

```bash
cp .env.example .env
nano .env
```

至少修改 `POSTGRES_PASSWORD` 与 `JWT_SECRET`。两者均使用 32 位以上随机字符；数据库密码仅使用字母、数字、下划线，避免 URL 特殊字符导致连接失败。

首次启动可在 Jenkins 完成首个镜像发布后执行：

```bash
docker compose pull
docker compose up -d
docker compose ps
```

`init.sql` 仅会在 PostgreSQL 数据卷第一次创建时自动执行。今后修改表结构必须使用数据库迁移工具，不能依赖重启容器。

## 3. 安装 Jenkins

Jenkins 可以直接安装在这台云服务器上。安装 JDK 17 和 Jenkins 后，确保 Jenkins 用户可调用 Docker：

```bash
sudo usermod -aG docker jenkins
sudo systemctl restart jenkins
```

安装插件：Git、Pipeline、GitHub、SSH Agent、Credentials Binding、Workspace Cleanup。

Jenkins 不应使用默认管理员密码或将任何密码提交到 Git。首次登录后立即创建独立管理员账号，并删除初始解锁密钥文件。

## 4. Jenkins 凭据与主机校验

在 **Manage Jenkins → Credentials → System → Global credentials** 创建：

- `registry-credentials`：类型 **Username with password**；填写阿里云容器镜像服务的登录用户名和密码（或访问凭据）。
- `deploy-ssh-key`：类型 **SSH Username with private key**；使用部署用户的私钥。

创建专用部署密钥（不要复用你个人电脑的私钥）：

```bash
sudo -u jenkins ssh-keygen -t ed25519 -f /var/lib/jenkins/.ssh/ci-project-deploy -N ''
sudo -u jenkins cat /var/lib/jenkins/.ssh/ci-project-deploy.pub
```

将第二条命令输出的公钥追加到部署用户的 `~/.ssh/authorized_keys`，再把 `ci-project-deploy` 私钥内容保存为 Jenkins 的 `deploy-ssh-key` 凭据。部署用户应只拥有 Docker 与 `/opt/ci-project` 的必要权限。

流水线禁止跳过 SSH 主机校验。将部署服务器公钥写入 Jenkins 用户的 known_hosts：

```bash
sudo -u jenkins mkdir -p /var/lib/jenkins/.ssh
sudo -u jenkins ssh-keyscan -H <服务器公网IP或域名> | sudo -u jenkins tee -a /var/lib/jenkins/.ssh/known_hosts
sudo chmod 700 /var/lib/jenkins/.ssh
sudo chmod 600 /var/lib/jenkins/.ssh/known_hosts
```

如果 Jenkins 与应用在同一台服务器，也仍按此方式使用服务器的公网 IP 或域名，保持与未来拆分服务器时相同的流程。

## 5. 创建 Jenkins Pipeline

新建 **Pipeline** 任务：

1. Definition 选择 **Pipeline script from SCM**。
2. SCM 选择 Git，填写 GitHub 仓库地址，Branch Specifier 填 `*/main`，Script Path 填 `Jenkinsfile`。
3. 若 GitHub 仓库公开，无需 Git 凭据；私有仓库再添加 GitHub PAT 或 SSH Key。
4. 在 Jenkinsfile 中把 `DEPLOY_HOST` 修改为你的云服务器公网 IP 或域名，然后提交到 GitHub。

Jenkins 本机必须能执行 `docker version`、`docker compose version`、`ssh` 和 `curl`。执行构建的 Jenkins 用户必须有 Docker Socket 权限。

## 6. 配置 GitHub Webhook

GitHub 仓库进入 **Settings → Webhooks → Add webhook**：

- Payload URL：`https://<Jenkins域名>/github-webhook/`
- Content type：`application/json`
- Events：只选择 **Just the push event**。
- Active：勾选。

提交后，在 GitHub Webhook 的 Recent Deliveries 中确认返回 2xx。若 Jenkins 没有 HTTPS 域名，可临时使用 `http://<公网IP>:8080/github-webhook/`，但正式使用应通过 HTTPS 和访问控制保护 Jenkins。

## 7. 验证发布与回滚

向 `main` 提交代码：

```bash
git add .
git commit -m "ci: trigger deployment"
git push origin main
```

Jenkins 会构建并推送两个镜像，更新 `/opt/ci-project/.env` 中的 `IMAGE_TAG`，再执行 `docker compose pull && docker compose up -d`。它通过服务器本机的 `http://127.0.0.1/api/health` 检查服务；连续失败会恢复 `.env.previous` 中的上一个 Tag。

服务器检查命令：

```bash
cd /opt/ci-project
docker compose ps
docker compose logs --tail=100 backend
curl -fsS http://127.0.0.1/api/health
```
