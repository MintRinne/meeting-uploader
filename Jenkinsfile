// 회의록 자동 배포 파이프라인 (Phase 3+)
// 로컬 Windows Jenkins 에서 실행. 매일 자정(KST) 트리거.

pipeline {
    agent any

    triggers {
        // Jenkins 는 자체 타임존을 쓰므로 TZ 를 명시한다
        cron('TZ=Asia/Seoul\n0 0 * * *')
    }

    environment {
        GROUPWARE_API_TOKEN = credentials('groupware-api-token') // Secret text
        GDRIVE_FOLDER_ID    = '<Shared Drive 폴더 ID>'
        GROUPWARE_BASE_URL  = 'https://groupware.example.com'
        GROUPWARE_BOARD_ID  = '42'
        ARCHIVE_REPO_URL    = 'git@github.com:your-org/meeting-archive.git'
        ARCHIVE_WORK_DIR    = '.work/meeting-archive'
        ARCHIVE_PUSH        = 'true'
        MIN_FILE_AGE_MINUTES = '10'
    }

    options {
        timestamps()
        buildDiscarder(logRotator(numToKeepStr: '30'))
    }

    stages {
        stage('Checkout') {
            steps { checkout scm }
        }

        stage('Setup') {
            steps {
                bat '''
                    python -m venv .venv
                    .venv\\Scripts\\pip install --quiet -r requirements-dev.txt
                    .venv\\Scripts\\pip install --quiet -e .
                '''
            }
        }

        stage('Test') {           // 업로드 전 품질 게이트
            steps {
                bat '.venv\\Scripts\\pytest -q'
                bat '.venv\\Scripts\\ruff check src tests'
            }
        }

        stage('Sync') {
            steps {
                // Drive 서비스계정 키(파일) + 미러 저장소 push 용 SSH 키
                withCredentials([file(credentialsId: 'gdrive-sa-key', variable: 'GDRIVE_SA_KEY_PATH')]) {
                    sshagent(['meeting-archive-deploy-key']) {
                        bat '.venv\\Scripts\\python -m meeting_uploader run'
                    }
                }
            }
        }
    }

    post {
        always {
            archiveArtifacts artifacts: 'run-report-*.json', allowEmptyArchive: true
        }
        // slackSend 는 Slack Notification 플러그인 설치 후 사용
        unstable { echo '부분 실패 — run-report 확인' }
        failure  { echo '배포 실패' }
        success  { echo '회의록 배포 완료' }
    }
}
