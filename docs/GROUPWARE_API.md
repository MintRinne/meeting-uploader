# 그룹웨어 API 연동 — 확인 체크리스트

사내 자체 구축 그룹웨어이므로 백엔드 담당자에게 아래를 확인해야 한다.
받은 값에 맞춰 `src/meeting_uploader/groupware.py` 를 수정한다 (실제 API 코드는 30줄 남짓).

## 1. 인증

- [ ] 인증 방식: Bearer 토큰 / API Key 헤더 / 세션 쿠키 / mTLS 중 무엇인가
- [ ] 토큰 발급 방법 (관리자 발급 / OAuth client_credentials / 개인 PAT)
- [ ] 토큰 만료·갱신 정책
- [ ] 회의록 게시용 **전용 서비스 계정** 생성 가능 여부 (권장)

## 2. 게시판 식별

- [ ] 회의록을 올릴 게시판의 ID 또는 코드
- [ ] 게시판 목록/상세 조회 API (선택)

## 3. 게시글 생성

- [ ] 엔드포인트 (`POST /...`)
- [ ] 요청 형식: JSON / multipart/form-data
- [ ] 필수 필드명: 제목, 본문(HTML? 마크다운? 플레인?), 게시판, 작성자, 분류
- [ ] 첨부파일 방식:
      - 게시글 생성과 동시에 multipart 로 첨부하는가
      - 아니면 별도 "파일 업로드 API" 로 먼저 올리고 file_id 를 본문에 연결하는가
- [ ] 첨부 용량 제한 / 허용 확장자 (.docx, .hwp 통과 여부)
- [ ] 응답: 생성된 게시글 ID, 조회 URL 이 응답에 오는가

## 4. 게시글 조회 (멱등성 3차 방어용)

- [ ] 제목/날짜로 기존 게시글 검색 API 가 있는가
- [ ] 없으면: 중복 방지는 로컬 manifest + Drive 토큰(1·2차 방어)만으로 충분한지 합의

## 5. 운영

- [ ] Rate limit (분당/일당 요청 수)
- [ ] 에러 응답 형식 (HTTP status code 규칙, 에러 body 스키마)
- [ ] 테스트/스테이징 환경 존재 여부 — **운영에 스팸 올리지 않도록 먼저 여기서 검증**
- [ ] 방화벽: Jenkins 가 도는 PC 에서 그룹웨어 API 호스트로 아웃바운드 허용되는가

## 현재 코드가 가정하는 형태 (groupware.py)

```
GET  {BASE}/api/boards/{BOARD_ID}/posts?query=<제목>
     -> 200 {"items": [{"id": ..., "title": ..., "url": ...}]}

POST {BASE}/api/boards/{BOARD_ID}/posts
     multipart: title=<제목>, content=<본문HTML>, attachment=<파일>
     -> 201 {"id": ..., "url": ...}

인증: Authorization: Bearer <TOKEN>
5xx -> 재시도(지수 백오프 3회) / 4xx -> 즉시 실패
```

실제 스펙을 받으면 이 가정과의 차이만 `groupware.py` 에 반영하면 된다.
그때까지는 `tools/mock_groupware.py` 로 대체해 전체 파이프라인을 검증한다.
