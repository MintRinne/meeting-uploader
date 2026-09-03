"""알림 (Slack incoming webhook).

의존성을 늘리지 않기 위해 표준 라이브러리(urllib)만 사용한다.
webhook 미설정 시에는 조용히 로그만 남긴다.
"""

from __future__ import annotations

import json
import logging
import urllib.request

log = logging.getLogger(__name__)


def notify_slack(webhook_url: str, text: str) -> None:
    if not webhook_url:
        log.info("Slack webhook 미설정 — 알림 생략: %s", text)
        return
    req = urllib.request.Request(
        webhook_url,
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=10)  # noqa: S310 (신뢰된 URL)
    except Exception:  # noqa: BLE001 - 알림 실패가 파이프라인을 세우면 안 됨
        log.exception("Slack 알림 실패")
