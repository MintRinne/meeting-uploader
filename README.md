# meeting-uploader
<<<<<<< HEAD

회의록 자동 배포 파이프라인.

**원본은 Google Drive 에 그대로 두고**, 매일 자정 Jenkins 가 새 회의록을 수집해
① Git 미러 저장소에 아카이브(회의 1건 = 커밋 1개)하고
② 그룹웨어 게시판에 게시글로 등록한다.

전체 설계는 [docs/DESIGN.md](docs/DESIGN.md) 참고.

## 구성요소

| 모듈 | 역할 |
|---|---|
| `config.py` | 환경변수 로드·검증 |
| `drive.py` | Google Drive 클라이언트 (read-only, `changes` 커서, 다운로드) |
| `parser.py` | 파일명 → 회의 날짜/제목/작성자 |
| `groupware.py` | 그룹웨어 REST 클라이언트 (재시도 포함) |
| `archive.py` | Git 미러 저장소 = 아카이브 + 상태 저장소(`state/`) |
| `pipeline.py` | fan-out 오케스트레이션 + 부분 실패 복구 |
| `notifier.py` | Slack 알림 |
| `cli.py` | `python -m meeting_uploader ...` |

## 로컬 개발

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\pip install -e .
copy .env.example .env        # 값 채우기
.venv\Scripts\pytest -q
```

## 명령어

```bash
# 파일명 파싱 확인 (자격증명 불필요)
python -m meeting_uploader parse 2026-09-03_주간개발회의.docx

# Phase 0: Drive 파일 1건 다운로드 (GDRIVE_SA_KEY_PATH 만 필요)
python -m meeting_uploader fetch --file-id <DRIVE_FILE_ID> --dest ./_download

# 미러 저장소 상태 확인 (ARCHIVE_REPO_URL 만 필요)
python -m meeting_uploader state

# 파이프라인 dry-run — Drive + 미러 저장소만으로 "무엇을 올릴지" 확인 (그룹웨어 불필요)
python -m meeting_uploader run --dry-run
python -m meeting_uploader run --dry-run --since 2026-09-01

# 실제 실행 (그룹웨어 설정 필요)
python -m meeting_uploader run
```

### 전체 파이프라인을 로컬에서 끝까지 (가짜 그룹웨어)

실제 사내 API 스펙을 받기 전까지는 `tools/mock_groupware.py` 로 검증한다.
자세한 확인 항목은 [docs/GROUPWARE_API.md](docs/GROUPWARE_API.md).

```bash
# 터미널 1 — 가짜 그룹웨어
.venv\Scripts\python tools\mock_groupware.py --port 8080

# 터미널 2 — .env 의 GROUPWARE_BASE_URL=http://127.0.0.1:8080 확인 후
.venv\Scripts\python -m meeting_uploader run
```

## 진행 단계

- [x] **Phase 0** — 스캐폴딩, 파일명 파서, Drive 단건 다운로드, 미러 저장소 연동
- [x] **Phase 1** — `changes` 커서 + manifest + dry-run + fan-out 부분실패 처리 (로컬 수동)
- [ ] **Phase 2** — Jenkins Freestyle job, cron 00:00
- [ ] **Phase 3** — Jenkinsfile, 시크릿 3개, 스테이지 분리
- [ ] **Phase 4** — pytest/ruff 게이트, Slack 알림, 리포트 아티팩트, UNSTABLE
- [ ] **Phase 5** — Drive Push Notification 준실시간, Google Docs → Markdown 커밋

## 남은 과제 (Phase 2 이전)

- **그룹웨어 API 문서 확보** → `groupware.py` 의 엔드포인트/스키마 확정 (`⚠️` 주석 위치).
  이게 있어야 `run` (dry-run 아닌) 이 동작.
=======
jenkins ci/cd 구글드라이브- 회의록 자동 받아오기
>>>>>>> 5049ea5216f95a5a99879ae31aee1c958bcd4a76
