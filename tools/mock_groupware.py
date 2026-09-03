"""학습용 가짜 그룹웨어 API 서버 (표준 라이브러리만 사용).

meeting_uploader.groupware.GroupwareClient 가 기대하는 최소 엔드포인트만 구현한다.
실제 사내 API 스펙을 받으면 src/meeting_uploader/groupware.py 를 그쪽에 맞추고
이 파일은 버리면 된다.

  GET  /api/boards/{board_id}/posts?query=<제목>   -> {"items": [{id,title,url}]}
  POST /api/boards/{board_id}/posts                -> 201 {"id","title","url"}
       (multipart/form-data: title, content, attachment)

실행:
  .venv\\Scripts\\python tools\\mock_groupware.py --port 8080
"""

from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

_POSTS: dict[str, dict] = {}  # title -> {id, title, url}
_SEQ = [0]
_PATH = re.compile(r"^/api/boards/([^/]+)/posts/?$")


class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if not _PATH.match(urlparse(self.path).path):
            return self._json(404, {"error": "not found"})
        query = parse_qs(urlparse(self.path).query).get("query", [""])[0]
        items = [p for title, p in _POSTS.items() if title == query]
        self._json(200, {"items": items})

    def do_POST(self) -> None:  # noqa: N802
        if not _PATH.match(urlparse(self.path).path):
            return self._json(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        title = _form_field(raw, "title")

        _SEQ[0] += 1
        pid = f"mock-{_SEQ[0]}"
        post = {
            "id": pid,
            "title": title,
            "url": f"http://{self.headers.get('Host', 'localhost')}/posts/{pid}",
        }
        _POSTS[title] = post
        print(f"[mock-groupware] 게시글 생성: {title!r} (본문+첨부 {length} bytes)")
        self._json(201, post)

    def log_message(self, *_args) -> None:  # 기본 액세스 로그 억제
        pass


def _form_field(raw: bytes, name: str) -> str:
    """multipart/form-data 에서 텍스트 필드 값만 대충 추출 (학습용)."""
    marker = f'name="{name}"'.encode()
    idx = raw.find(marker)
    if idx == -1:
        return ""
    start = raw.find(b"\r\n\r\n", idx) + 4
    end = raw.find(b"\r\n--", start)
    return raw[start : end if end != -1 else None].decode("utf-8", "replace")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"가짜 그룹웨어: http://127.0.0.1:{args.port}  (Ctrl+C 로 종료)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료")


if __name__ == "__main__":
    main()
