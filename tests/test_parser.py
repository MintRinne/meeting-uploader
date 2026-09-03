from datetime import date

import pytest

from meeting_uploader.parser import FileNameError, parse_filename


def test_parse_basic():
    doc = parse_filename("2026-09-03_주간개발회의.docx")
    assert doc.meeting_date == date(2026, 9, 3)
    assert doc.title == "주간개발회의"
    assert doc.ext == "docx"


def test_parse_without_extension_google_doc():
    doc = parse_filename("2026-09-03_스프린트 회고")
    assert doc.title == "스프린트 회고"
    assert doc.ext == ""


def test_title_may_contain_underscore_and_space():
    doc = parse_filename("2026-09-03_주간 개발_회의.hwp")
    assert doc.title == "주간 개발_회의"
    assert doc.ext == "hwp"


def test_author_defaults_to_unknown():
    # 작성자는 파일명이 아니라 Drive 에서 채워지므로 파서 단계에선 기본값
    assert parse_filename("2026-09-03_회의.docx").author == "(알 수 없음)"


def test_post_title_and_archive_path():
    doc = parse_filename("2026-09-03_주간개발회의.docx")
    assert doc.post_title == "[회의록] 2026-09-03 주간개발회의"
    assert doc.archive_path() == "minutes/2026/09/2026-09-03_주간개발회의.docx"


def test_extension_is_case_insensitive():
    assert parse_filename("2026-09-03_회의.DOCX").ext == "docx"


@pytest.mark.parametrize(
    "bad",
    [
        "회의록.docx",
        "2026-9-3_회의.docx",  # 0-padding 안 됨
        "2026-09-03.docx",  # 제목 구분자(_) 없음
        "2026-09-03_",  # 제목 없음
        "2026-13-40_회의.docx",  # 존재하지 않는 날짜
        "6차_멘토링_회의록_260902.docx",  # 구 명명 규칙
    ],
)
def test_invalid_names_raise(bad):
    with pytest.raises(FileNameError):
        parse_filename(bad)
