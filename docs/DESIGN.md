# 회의록 자동 배포 파이프라인 — 확정 설계

## 1. 목표

Google Shared Drive 에 쌓이는 회의록을 매일 자정 Jenkins 가 수집해, **원본은 손대지 않고**
① Git 저장소에 아카이브(회의 1건 = 커밋 1개)하고 ② 그룹웨어 게시판에 게시글로 등록한다.
CI/CD 핵심 개념(트리거, 멱등 배포, 시크릿 관리, 파이프라인 게이트, fan-out, 부분 실패 복구,
관측성)을 실제로 익히는 것이 목적.

## 2. 최종 아키텍처

```
Google Shared Drive (원본 · read-only)
        │  Drive changes.list (drive.readonly)
        ▼
Jenkins Pipeline · Windows · cron 0 0 * * * (KST)
        │  ← meeting-archive clone (state 로드)
        ▼
   manifest.json 대조 (파일별 git / groupware 상태)
        ▼
   신규·변경 파일 다운로드 → 임시 workspace
        ├────────────► Git 미러 저장소 커밋·push (미등록분만)
        └────────────► 그룹웨어 REST API 게시글 등록 (미등록분만)
        ▼
   drive_page_token + manifest.json 갱신 커밋
        ▼
   Slack/메일 알림 + 리포트 아티팩트
```

## 3. 저장소 3개

| 저장소 | 역할 | 접근 |
|---|---|---|
| Google Shared Drive | 회의록 원천. 절대 쓰지 않음 | 서비스 계정, `drive.readonly` |
| `meeting-archive` (Git) | 회의록 미러 + **파이프라인 상태 저장소** | 배포키(write) |
| `meeting-uploader` (Git) | 파이프라인 코드 + Jenkinsfile | Jenkins SCM |

`meeting-archive` 레이아웃:

```
minutes/2026/09/2026-09-03_주간개발회의.docx
state/
  drive_page_token          # 다음 changes.list 시작 커서
  manifest.json             # fileId -> {revision, git_path, committed_at,
                            #            groupware_post_id, status}
README.md
```

커밋 메시지: `chore(minutes): add minutes/2026/09/2026-09-03_주간개발회의.docx` (작성자: 홍길동)

## 4. 명명 규칙 (작성자 공지)

```
YYYY-MM-DD_제목[.docx|.hwp]
예) 2026-09-03_주간개발회의.docx
    2026-09-03_스프린트 회고          (확장자 없는 Google Docs 네이티브)
```

- 회의 날짜 = 파일명 접두사 (Drive `createdTime`·폴더 경로는 보조 검증용)
- 제목에는 밑줄·공백 허용
- **작성자는 파일명이 아니라 Drive `lastModifyingUser`(최종 수정자)에서 채운다**
- 규칙 위반 파일(구 `N차_멘토링_회의록_YYMMDD.docx` 등)은 배포하지 않고 `SKIPPED` + 알림
- 네이티브 Google Docs 는 `files.export` 로 `.docx` 변환 후 동일 처리
  (Phase 5 에서 `.md` 변환 추가 → git diff 로 내용 변경 추적)

## 5. 멱등성 & 부분 실패 처리 (이 프로젝트의 심장)

3단 방어:

1. **Drive `startPageToken`** — 지난 실행 이후 변경분만 서버가 알려줌
2. **`manifest.json`** — 파일별로 `git` / `groupware` 각각 완료 여부 기록
3. **그룹웨어 사전 조회** — 업로드 직전 `제목`으로 기존 게시글 확인

fan-out 부분 실패 시맨틱:

| Git | 그룹웨어 | 다음 실행 동작 | 빌드 상태 |
|---|---|---|---|
| ✅ | ✅ | skip | SUCCESS |
| ✅ | ❌ | 그룹웨어만 재시도 | UNSTABLE |
| ❌ | ❌ | 둘 다 재시도 | UNSTABLE |

토큰 유실 시 폴백: 전체 `files.list` 워크 + `manifest` 의 `fileId`+`headRevisionId`/`md5Checksum` 로 중복 판정.

## 6. 인증 & 시크릿 (Jenkins Credentials 3개)

| ID | 타입 | 용도 | 발급 |
|---|---|---|---|
| `gdrive-sa-key` | Secret file | Drive 읽기 | GCP 서비스계정 JSON → Shared Drive 에 뷰어로 추가 |
| `meeting-archive-deploy-key` | SSH key | 미러 push | 미러 저장소 Deploy key (write) |
| `groupware-api-token` | Secret text | 게시글 등록 | 그룹웨어 전용 계정, 해당 게시판 쓰기 권한만 |

- 코드/로그에 시크릿 금지
- 설정값은 전부 환경변수, `config.py` 에서 누락 시 즉시 실패
- 서비스 계정 + My Drive 는 불가 → 반드시 **Shared Drive**

## 7. 파이프라인 스테이지 (Jenkinsfile)

`Checkout → Setup(venv) → Test(pytest + ruff, 게이트) → Sync(run) → post(아티팩트 + 알림)`

`triggers { cron('TZ=Asia/Seoul\n0 0 * * *') }`

## 8. 단계별 로드맵 = CI/CD 학습 커리큘럼

| Phase | 산출물 | 익히는 개념 |
|---|---|---|
| 0. 통합 검증 | Drive 파일 1건 다운로드 → 미러 수동 커밋 → 그룹웨어 1건 등록 | 3개 API 인증, 첨부 업로드 |
| 1. 파이프라인 로직 | `changes.list` 커서 + manifest + dry-run + fan-out 부분실패 | 멱등성, 상태 관리, fan-out |
| 2. Jenkins Freestyle | Jenkins 설치, job 이 매일 00:00 실행 | 빌드 트리거, cron, workspace, 로그 |
| 3. Pipeline as Code | Jenkinsfile 전환, SCM 연동, 시크릿 3개, 스테이지 분리 | 선언적 파이프라인, Credentials, sshagent |
| 4. 운영 성숙도 | pytest·ruff 게이트, Slack 알림, 리포트 아티팩트, UNSTABLE | 품질 게이트, 관측성, 부분 실패 복구 |
| 5. 확장 | Drive Push Notification 준실시간, Google Docs → Markdown 커밋, 자동 PR | 이벤트 vs 스케줄 트리거, GitOps |

## 9. 리스크 & 주의점

1. **부분 실패가 정상 상황** — fan-out 한쪽만 성공은 늘 발생. manifest 상태 추적 + UNSTABLE + 자동 재시도가 Phase 1 필수.
2. **자정 저장 중 파일** — `modifiedTime` 이 최근 N분이면 이번 회차 보류(deferred).
   보류된 파일이 있으면 `drive_page_token` 을 전진시키지 않아 다음 회차에 다시 조회된다.
   커서가 꼬였을 때 복구는 `run --full-scan`.
3. **최초 실행 백필 폭탄** — `changes.getStartPageToken` 으로 시작점 잡고 과거분은 `--since` 커트오프.
4. **서비스 계정 + My Drive 불가** — 반드시 Shared Drive.
5. **미러 저장소 비대화** — 대용량 첨부는 Git LFS 검토.
6. **Jenkins Windows** — `git`/`python` PATH, SSH `known_hosts` 사전 등록, 서비스 계정으로 SSH 키 접근 가능해야.
7. **HWP** — 파싱 안 함. 바이너리로 미러 커밋 + 그룹웨어 첨부만.

## 10. Phase 0 체크리스트

- [ ] GCP 프로젝트 → Drive API 활성화 → 서비스계정 + JSON 키
- [ ] Shared Drive 에 서비스계정 이메일 뷰어 추가, 회의록 폴더 ID 확보
- [ ] `meeting-archive` 저장소 생성 + Deploy key
- [ ] 그룹웨어 API 문서로 `create_post`·첨부·게시글 조회 엔드포인트 확인 (최대 미지수)
- [x] `meeting-uploader` 스캐폴딩 + `parse` / `fetch` 명령
