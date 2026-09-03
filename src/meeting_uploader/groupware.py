"""그룹웨어 REST API 클라이언트.

⚠️ Phase 0 과제: 실제 그룹웨어 API 문서를 확보한 뒤 아래를 맞춰야 한다.
   - 인증 방식 (Bearer 토큰 가정)
   - 게시글 조회 엔드포인트 / 응답 스키마
   - 게시글 생성 + 첨부 업로드 방식 (multipart 가정)
   현재 코드는 흔한 형태를 가정한 골격이며, 엔드포인트/필드명을 바꿔 끼우면 된다.

재시도 정책
   - 5xx / 네트워크 오류: 지수 백오프로 3회 재시도
   - 4xx: 재시도해도 소용없으므로 즉시 실패
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .parser import MeetingDoc


@dataclass(frozen=True)
class PostResult:
    post_id: str
    url: str


class GroupwareError(RuntimeError):
    """그룹웨어 API 오류 (재시도 불가)."""


class GroupwareServerError(GroupwareError):
    """일시적 서버/네트워크 오류 (재시도 대상)."""


def build_post_body(doc: MeetingDoc) -> str:
    return (
        "<table>"
        f"<tr><th>회의일자</th><td>{doc.meeting_date.isoformat()}</td></tr>"
        f"<tr><th>회의명</th><td>{html.escape(doc.title)}</td></tr>"
        f"<tr><th>작성자</th><td>{html.escape(doc.author)}</td></tr>"
        f"<tr><th>원본파일</th><td>{html.escape(doc.filename)}</td></tr>"
        "</table>"
        "<p>상세 내용은 첨부파일을 참조하세요.</p>"
    )


class GroupwareClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        board_id: str,
        *,
        timeout: float = 30.0,
    ):
        self._base = base_url.rstrip("/")
        self._board_id = board_id
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {token}"})

    # --- 공개 API -------------------------------------------------------
    def find_post(self, title: str) -> PostResult | None:
        """멱등성 3차 방어: 같은 제목의 게시글이 이미 있으면 재사용."""
        resp = self._session.get(
            f"{self._base}/api/boards/{self._board_id}/posts",
            params={"query": title},
            timeout=self._timeout,
        )
        self._check(resp)
        for item in resp.json().get("items", []):
            if item.get("title") == title:
                return PostResult(str(item["id"]), item.get("url", ""))
        return None

    @retry(
        retry=retry_if_exception_type((requests.RequestException, GroupwareServerError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    def create_post(self, *, title: str, body_html: str, attachment: Path) -> PostResult:
        with attachment.open("rb") as fh:
            resp = self._session.post(
                f"{self._base}/api/boards/{self._board_id}/posts",
                data={"title": title, "content": body_html},
                files={"attachment": (attachment.name, fh)},
                timeout=self._timeout,
            )
        self._check(resp)
        data = resp.json()
        return PostResult(str(data["id"]), data.get("url", ""))

    # --- 내부 ----------------------------------------------------------
    @staticmethod
    def _check(resp: requests.Response) -> None:
        if resp.status_code >= 500:
            raise GroupwareServerError(f"서버 오류 {resp.status_code}: {resp.text[:200]}")
        if resp.status_code >= 400:
            raise GroupwareError(f"요청 오류 {resp.status_code}: {resp.text[:200]}")
