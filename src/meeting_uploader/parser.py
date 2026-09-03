"""회의록 파일명 파싱.

표준 명명 규칙:  YYYY-MM-DD_회의명_작성자.(docx|hwp)
    예) 2026-09-03_주간개발회의_김철수.docx

- 회의 날짜는 파일명 접두사를 신뢰한다 (Drive 메타데이터는 보조 검증용).
- 회의명에는 밑줄이 들어갈 수 있으나, 작성자에는 들어갈 수 없다 (마지막 밑줄 기준 분리).
- 규칙 위반 파일은 배포하지 않고 리포트에 SKIPPED 로 남긴다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

SUPPORTED_EXTENSIONS = ("docx", "hwp")

_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})_(?P<title>.+?)_(?P<author>[^_]+)\.(?P<ext>docx|hwp)$",
    re.IGNORECASE,
)


class FileNameError(ValueError):
    """파일명이 표준 명명 규칙을 따르지 않음."""


@dataclass(frozen=True)
class MeetingDoc:
    filename: str
    meeting_date: date
    title: str
    author: str
    ext: str

    @property
    def post_title(self) -> str:
        return f"[회의록] {self.meeting_date.isoformat()} {self.title}"

    def archive_path(self) -> str:
        """미러 저장소 내 상대 경로: minutes/YYYY/MM/<원본파일명>"""
        d = self.meeting_date
        return f"minutes/{d.year:04d}/{d.month:02d}/{self.filename}"


def parse_filename(filename: str) -> MeetingDoc:
    m = _PATTERN.match(filename.strip())
    if not m:
        raise FileNameError(
            f"명명 규칙 위반: {filename!r} (기대 형식: YYYY-MM-DD_회의명_작성자.docx|hwp)"
        )
    try:
        meeting_date = date.fromisoformat(m.group("date"))
    except ValueError as e:
        raise FileNameError(f"날짜 파싱 실패: {filename!r}") from e
    return MeetingDoc(
        filename=filename.strip(),
        meeting_date=meeting_date,
        title=m.group("title").strip(),
        author=m.group("author").strip(),
        ext=m.group("ext").lower(),
    )
