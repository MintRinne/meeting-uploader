"""회의록 파일명 파싱.

표준 명명 규칙:  YYYY-MM-DD_제목[.docx|.hwp]
    예) 2026-09-03_주간개발회의.docx
        2026-09-03_스프린트 회고        (확장자 없는 Google Docs 네이티브 문서)

- 회의 날짜는 파일명 접두사를 신뢰한다 (Drive 메타데이터는 보조 검증용).
- 제목에는 밑줄·공백이 들어갈 수 있다.
- 작성자는 파일명이 아니라 Drive 의 lastModifyingUser 에서 채운다 (pipeline).
- 규칙 위반 파일은 배포하지 않고 리포트에 SKIPPED 로 남긴다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

SUPPORTED_EXTENSIONS = ("docx", "hwp")

_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})_(?P<title>.+?)(?:\.(?P<ext>docx|hwp))?$",
    re.IGNORECASE,
)

_UNKNOWN_AUTHOR = "(알 수 없음)"


class FileNameError(ValueError):
    """파일명이 표준 명명 규칙을 따르지 않음."""


@dataclass(frozen=True)
class MeetingDoc:
    filename: str
    meeting_date: date
    title: str
    ext: str = ""  # "" = 확장자 없음 (Google Docs 네이티브)
    author: str = _UNKNOWN_AUTHOR

    @property
    def post_title(self) -> str:
        return f"[회의록] {self.meeting_date.isoformat()} {self.title}"

    def archive_path(self) -> str:
        """미러 저장소 내 상대 경로: minutes/YYYY/MM/<원본파일명>"""
        d = self.meeting_date
        return f"minutes/{d.year:04d}/{d.month:02d}/{self.filename}"


def parse_filename(filename: str) -> MeetingDoc:
    name = filename.strip()
    m = _PATTERN.match(name)
    if not m:
        raise FileNameError(
            f"명명 규칙 위반: {filename!r} (기대 형식: YYYY-MM-DD_제목[.docx|.hwp])"
        )
    try:
        meeting_date = date.fromisoformat(m.group("date"))
    except ValueError as e:
        raise FileNameError(f"날짜 파싱 실패: {filename!r}") from e

    title = m.group("title").strip()
    if not title:
        raise FileNameError(f"제목이 비어 있음: {filename!r}")

    return MeetingDoc(
        filename=name,
        meeting_date=meeting_date,
        title=title,
        ext=(m.group("ext") or "").lower(),
    )
