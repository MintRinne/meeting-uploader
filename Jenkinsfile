// 회의록 자동 배포 파이프라인
// 로컬 Windows Jenkins 에서 Pipeline job (Pipeline script from SCM) 으로 실행.
// 매일 자정(KST) 트리거. 시크릿은 전부 Jenkins Credentials 에서 주입 (파일/env 하드코딩 없음).
//
// 필요한 Jenkins Credentials (Manage Jenkins > Credentials):
//   gdrive-sa-key      Secret file            Drive 서비스계정 JSON 키
//   groupware-api-token Secret text           그룹웨어 API 토큰 (mock 이면 아무 문자열)
//   archive-repo-pat   Username with password  meeting-archive push 용 GitHub PAT
//                                              (username: GitHub 계정명, password: PAT)

pipeline {
    agent any

    triggers {
        // Jenkins 는 자체 타임존을 쓰므로 TZ 를 명시한다
        cron('TZ=Asia/Seoul\n0 0 * * *')
    }

    environment {
        // 사용자 전용으로 설치된 Python 이라 Machine PATH 에 없음 -> 전체 경로 사용
        PY_EXE = 'C:\\Users\\Playdata\\AppData\\Local\\Programs\\Python\\Python314\\python.exe'

        GROUPWARE_API_TOKEN = credentials('groupware-api-token') // Secret text

        // 비밀 아닌 설정값
        GDRIVE_FOLDER_ID     = '1xrMwlVEYq7ksC0ZR79_uQB6n0c7gfLOv'
        GROUPWARE_BASE_URL   = 'http://127.0.0.1:8080' // mock. 실제 API 확정되면 교체
        GROUPWARE_BOARD_ID   = '1'
        ARCHIVE_WORK_DIR     = '.work/meeting-archive'
        ARCHIVE_PUSH         = 'true'
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
                    "%PY_EXE%" -m venv .venv
                    .venv\\Scripts\\pip.exe install --quiet -r requirements-dev.txt
                    .venv\\Scripts\\pip.exe install --quiet -e .
                '''
            }
        }

        stage('Test') {           // 업로드 전 품질 게이트
            steps {
                bat '.venv\\Scripts\\pytest.exe -q'
                bat '.venv\\Scripts\\ruff.exe check src tests'
            }
        }

        stage('Sync') {
            steps {
                withCredentials([
                    file(credentialsId: 'gdrive-sa-key', variable: 'GDRIVE_SA_KEY_PATH'),
                    usernamePassword(
                        credentialsId: 'archive-repo-pat',
                        usernameVariable: 'GIT_USER',
                        passwordVariable: 'GIT_PAT'
                    )
                ]) {
                    bat '''
                        set "GIT_TERMINAL_PROMPT=0"
                        set "ARCHIVE_REPO_URL=https://%GIT_USER%:%GIT_PAT%@github.com/MintRinne/meeting-archive.git"
                        .venv\\Scripts\\python.exe -m meeting_uploader run
                    '''
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
