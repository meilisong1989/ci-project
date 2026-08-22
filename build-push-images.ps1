# 构建并推送前端与后端镜像。
# 示例（Docker Hub，已提前 docker login）：
#   .\build-push-images.ps1 -ImageRepository "your-dockerhub-id/ci-project"
# 示例（私有仓库）：
#   .\build-push-images.ps1 -ImageRepository "registry.example.com/team/ci-project" -Registry "registry.example.com"
# 示例（在 CI 中传入 Token，避免交互式登录）：
#   .\build-push-images.ps1 -ImageRepository "your-dockerhub-id/ci-project" -RegistryUser "your-dockerhub-id" -RegistryToken $env:REGISTRY_TOKEN

[CmdletBinding()]
param(
    # 镜像仓库名，不包含 Tag。例如：meilisong/ci-project 或 registry.example.com/team/ci-project
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ImageRepository,

    # 同一次发布的两个镜像共用同一个版本 Tag。
    [string]$ImageTag = (Get-Date -Format "yyyyMMddHHmmss"),

    # 私有镜像仓库地址；Docker Hub 请保持为空。
    [string]$Registry,

    # 仅当同时提供 RegistryUser 与 RegistryToken 时执行非交互式 docker login。
    [string]$RegistryUser,
    [string]$RegistryToken,

    # 构建时拉取基础镜像的最新版本。
    [switch]$Pull
)

$ErrorActionPreference = "Stop"

function Invoke-Docker {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)

    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker $($Arguments -join ' ') 执行失败，退出码：$LASTEXITCODE"
    }
}

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$frontendImage = "${ImageRepository}:frontend-$ImageTag"
$backendImage = "${ImageRepository}:backend-$ImageTag"

if ([string]::IsNullOrWhiteSpace($RegistryUser) -xor [string]::IsNullOrWhiteSpace($RegistryToken)) {
    throw "RegistryUser 和 RegistryToken 必须同时提供；否则请都不提供并先手动执行 docker login。"
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "未找到 docker 命令。请安装 Docker Desktop（本机）或 Docker Engine（服务器）后重试。"
}

Invoke-Docker version --format '{{.Server.Version}}' | Out-Null

if ($RegistryUser) {
    Write-Host "登录镜像仓库..." -ForegroundColor Cyan
    # password-stdin 可避免 Token 出现在命令行历史或构建日志中。
    if ($Registry) {
        $RegistryToken | & docker login $Registry --username $RegistryUser --password-stdin
    } else {
        $RegistryToken | & docker login --username $RegistryUser --password-stdin
    }
    if ($LASTEXITCODE -ne 0) { throw "镜像仓库登录失败。" }
}

$buildOptions = @('build')
if ($Pull) { $buildOptions += '--pull' }

Write-Host "构建前端镜像：$frontendImage" -ForegroundColor Cyan
Invoke-Docker @buildOptions -t $frontendImage (Join-Path $projectRoot 'frontend')

Write-Host "构建后端镜像：$backendImage" -ForegroundColor Cyan
Invoke-Docker @buildOptions -t $backendImage (Join-Path $projectRoot 'backend')

Write-Host "推送前端镜像：$frontendImage" -ForegroundColor Cyan
Invoke-Docker push $frontendImage

Write-Host "推送后端镜像：$backendImage" -ForegroundColor Cyan
Invoke-Docker push $backendImage

Write-Host "`n发布完成：" -ForegroundColor Green
Write-Host "  $frontendImage"
Write-Host "  $backendImage"
Write-Host "部署时将 deploy/.env 中的 IMAGE_REPOSITORY 设为 $ImageRepository，IMAGE_TAG 设为 $ImageTag。" -ForegroundColor Green
