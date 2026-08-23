pipeline {
  agent any

  options {
    skipDefaultCheckout()
    disableConcurrentBuilds()
    buildDiscarder(logRotator(numToKeepStr: '20'))
  }

  environment {
    // 阿里云个人版容器镜像服务。前端与后端通过 Tag 区分。
    REGISTRY_HOST = 'crpi-fzzu10dkr9pvcmtt.cn-hangzhou.personal.cr.aliyuncs.com'
    IMAGE_REPOSITORY = 'crpi-fzzu10dkr9pvcmtt.cn-hangzhou.personal.cr.aliyuncs.com/mydev1/dev'
    // Jenkins 和业务容器部署在同一台 Ubuntu 云服务器。
    DEPLOY_PATH = '/opt/ci-project'
  }

  triggers {
    // GitHub Webhook 地址：https://<jenkins-domain>/github-webhook/
    githubPush()
  }

  stages {
    stage('Checkout') {
      options { timeout(time: 10, unit: 'MINUTES') }
      steps {
        echo '使用 Jenkins 任务中配置的 GitHub SCM 拉取 main 分支代码'
        checkout scm
        script {
          env.TAG = sh(script: 'git rev-parse --short HEAD', returnStdout: true).trim()
        }
      }
    }

    stage('Build Frontend') {
      options { timeout(time: 15, unit: 'MINUTES') }
      steps {
        echo '按照 pnpm-lock.yaml 在 Docker 中构建前端'
        sh 'docker build --pull -t $IMAGE_REPOSITORY:frontend-$TAG frontend'
      }
    }

    stage('Build Backend') {
      options { timeout(time: 15, unit: 'MINUTES') }
      steps {
        echo '构建后端镜像，并校验应用模块可导入'
        sh '''
          docker build --pull -t $IMAGE_REPOSITORY:backend-$TAG backend
          docker run --rm $IMAGE_REPOSITORY:backend-$TAG python -c "import app.main; print('backend import check passed')"
        '''
      }
    }

    stage('Push Images') {
      options { timeout(time: 10, unit: 'MINUTES') }
      steps {
        withCredentials([usernamePassword(
          credentialsId: 'registry-credentials',
          usernameVariable: 'REGISTRY_USER',
          passwordVariable: 'REGISTRY_TOKEN'
        )]) {
          sh '''
            echo "$REGISTRY_TOKEN" | docker login "$REGISTRY_HOST" -u "$REGISTRY_USER" --password-stdin
            docker push $IMAGE_REPOSITORY:frontend-$TAG
            docker push $IMAGE_REPOSITORY:backend-$TAG
            # 同一 Jenkins 用户随后要执行 docker compose pull 拉取私有镜像，不能在此退出仓库。
            echo "镜像构建并推送成功: $IMAGE_REPOSITORY:frontend-$TAG"
            echo "镜像构建并推送成功: $IMAGE_REPOSITORY:backend-$TAG"
          '''
        }
      }
    }

    stage('Deploy') {
      options { timeout(time: 10, unit: 'MINUTES') }
      steps {
        sh '''
          test -f $DEPLOY_PATH/docker-compose.yml
          test -f $DEPLOY_PATH/.env
          cd $DEPLOY_PATH
          cp .env .env.previous
          sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=$TAG/" .env
          docker compose pull
          docker compose up -d --remove-orphans
        '''
      }
    }

    stage('Health Check and Rollback') {
      options { timeout(time: 10, unit: 'MINUTES') }
      steps {
        script {
          def good = false
          for (int i = 0; i < 6; i++) {
            sleep time: 10, unit: 'SECONDS'
            if (sh(script: 'curl -fsS http://127.0.0.1/api/health', returnStatus: true) == 0) {
              good = true
              break
            }
          }
          if (!good) {
            sh '''
              cd $DEPLOY_PATH
              cp .env.previous .env
              docker compose pull
              docker compose up -d --remove-orphans
            '''
            error('健康检查失败，已回滚到上一个镜像版本')
          }
        }
      }
    }
  }

  post {
    success { echo "部署成功：${IMAGE_REPOSITORY}，版本 ${env.TAG ?: 'unknown'}" }
    failure { echo "部署失败：${IMAGE_REPOSITORY}，版本 ${env.TAG ?: 'unknown'}" }
    always { cleanWs(deleteDirs: true, notFailBuild: true) }
  }
}
