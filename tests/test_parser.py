from datetime import date

import pytest

from meeting_uploader.parser import FileNameError, parse_filename


def test_parse_basic():
    doc = parse_filename("2026-09-03_주간개발회의_김철수.docx")
    assert doc.meeting_date == date(2026, 9, 3)
    assert doc.title == "주간개발회의"
    assert doc.author == "김철수"
    assert doc.ext == "docx"


def test_title_may_contain_underscore():
    doc = parse_filename("2026-09-03_주간_개발_회의_김철수.hwp")
    assert doc.title == "주간_개발_회의"
    assert doc.author == "김철수"
    assert doc.ext == "hwp"


def test_post_title_and_archive_path():
    doc = parse_filename("2026-09-03_주간개발회의_김철수.docx")
    assert doc.post_title == "[회의록] 2026-09-03 주간개발회의"
    assert doc.archive_path() == "minutes/2026/09/2026-09-03_주간개발회의_김철수.docx"


def test_extension_is_case_insensitive():
    assert parse_filename("2026-09-03_회의_김철수.DOCX").ext == "docx"


@pytest.mark.parametrize(
    "bad",
    [
        "회의록.docx",
        "2026-9-3_회의_김철수.docx",  # 0-padding 안 됨
        "2026-09-03_회의.docx",  # 작성자 없음
        "2026-09-03_회의_김철수.pdf",  # 미지원 확장자
        "2026-13-40_회의_김철수.docx",  # 존재하지 않는 날짜
    ],
)
def test_invalid_names_raise(bad):
    with pytest.raises(FileNameError):
        parse_filename(bad)
