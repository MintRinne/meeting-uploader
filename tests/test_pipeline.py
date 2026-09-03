"""pipeline.run 의 선별 로직 테스트.

Drive / 미러 저장소 / 그룹웨어를 모두 가짜(fake)로 대체해
"어떤 파일이 대상이고 어떤 파일이 왜 건너뛰어지는가"를 검증한다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from meeting_uploader import pipeline
from meeting_uploader.archive import STATUS_DONE, STATUS_GIT_DONE, Entry
from meeting_uploader.config import Config, ConfigError
from meeting_uploader.groupware import PostResult


# --- 가짜 구현 --------------------------------------------------------
class FakeDrive:
    def __init__(self, files: list[dict]):
        self._files = files
        self.downloaded: list[str] = []

    def list_changes(self, token):  # noqa: ARG002
        raise AssertionError("token 없는 테스트에서 호출되면 안 됨")

    def list_folder(self, folder_id):  # noqa: ARG002
        return self._files

    def get_start_page_token(self):
        return "TOKEN-NEXT"

    def download(self, f, dest_dir):
        self.downloaded.append(f["name"])
        p = Path(dest_dir) / f["name"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"dummy")
        return p


class FakeArchive:
    def __init__(self, manifest: dict[str, Entry] | None = None):
        self._manifest = manifest or {}
        self.token: str | None = None
        self.saved_manifest: dict[str, Entry] | None = None
        self.committed = False
        self.pushed = False
        self.added: list[str] = []

    def sync(self):
        pass

    def read_page_token(self):
        return self.token

    def write_page_token(self, token):
        self.token = token

    def load_manifest(self):
        return dict(self._manifest)

    def save_manifest(self, manifest):
        self.saved_manifest = manifest

    def commit_state(self):
        self.committed = True

    def push(self):
        self.pushed = True

    def add_document(self, src, rel_path, *, message=None):  # noqa: ARG002
        self.added.append(rel_path)
        return "deadbeef"


class FakeGroupware:
    def __init__(self):
        self.created: list[str] = []
        self.bodies: list[str] = []

    def find_post(self, title):  # noqa: ARG002
        return None

    def create_post(self, *, title, body_html, attachment):  # noqa: ARG002
        self.created.append(title)
        self.bodies.append(body_html)
        return PostResult(post_id="p-1", url="https://gw/p-1")


# --- 헬퍼 -----------------------------------------------------------
def _cfg(tmp_path: Path, **over) -> Config:
    base = dict(
        gdrive_sa_key_path=tmp_path / "sa.json",
        gdrive_folder_id="F",
        archive_repo_url="https://example/repo.git",
        archive_work_dir=tmp_path / "work" / "mirror",
        archive_push=False,
        groupware_base_url="",
        groupware_api_token="",
        groupware_board_id="",
        dry_run=True,
        min_file_age_minutes=10,
        slack_webhook_url="",
    )
    base.update(over)
    return Config(**base)


def _file(name: str, *, minutes_old: int = 60, rev: str = "r1", author: str = "김철수") -> dict:
    mtime = (datetime.now(UTC) - timedelta(minutes=minutes_old)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )
    return {
        "id": f"id::{name}",
        "name": name,
        "mimeType": "application/octet-stream",
        "modifiedTime": mtime,
        "headRevisionId": rev,
        "lastModifyingUser": {"displayName": author},
    }


@pytest.fixture
def wire(monkeypatch):
    """DriveClient / ArchiveRepo / GroupwareClient 를 가짜로 교체."""

    def _apply(files, *, manifest=None, groupware=None):
        drive = FakeDrive(files)
        archive = FakeArchive(manifest)
        gw = groupware or FakeGroupware()
        monkeypatch.setattr(pipeline, "DriveClient", lambda *a, **k: drive)
        monkeypatch.setattr(pipeline, "ArchiveRepo", lambda *a, **k: archive)
        monkeypatch.setattr(pipeline, "GroupwareClient", lambda *a, **k: gw)
        return drive, archive, gw

    return _apply


# --- 테스트 ---------------------------------------------------------
def test_dry_run_selects_only_valid_files(tmp_path, wire):
    drive, archive, _ = wire(
        [
            _file("2026-09-03_주간회의.docx"),
            _file("엉망진창이름.txt"),
            _file("6차_멘토링_회의록_260902.docx"),  # 구 명명 규칙
            _file("2026-09-03_긴급회의.docx", minutes_old=1),  # 너무 최근
        ]
    )
    report = pipeline.run(_cfg(tmp_path, dry_run=True))
    data = report.as_dict()

    assert data["counts"]["planned"] == 1
    assert report.planned[0]["file"] == "2026-09-03_주간회의.docx"
    assert report.planned[0]["author"] == "김철수"
    assert report.planned[0]["post_title"] == "[회의록] 2026-09-03 주간회의"

    reasons = {s["file"]: s["reason"] for s in report.skipped}
    assert "엉망진창이름.txt" in reasons
    assert "6차_멘토링_회의록_260902.docx" in reasons
    assert "최근 수정" in reasons["2026-09-03_긴급회의.docx"]

    # dry-run 은 상태를 건드리지 않는다
    assert archive.committed is False
    assert archive.token is None
    assert drive.downloaded == []


def test_since_cutoff(tmp_path, wire):
    wire(
        [
            _file("2026-08-01_옛날회의.docx"),
            _file("2026-09-03_최근회의.docx"),
        ]
    )
    report = pipeline.run(_cfg(tmp_path, dry_run=True), since="2026-09-01")
    assert [p["file"] for p in report.planned] == ["2026-09-03_최근회의.docx"]


def test_already_done_same_revision_skipped(tmp_path, wire):
    name = "2026-09-03_주간회의.docx"
    manifest = {
        f"id::{name}": Entry(
            file_id=f"id::{name}", revision="r1", filename=name, status=STATUS_DONE
        )
    }
    wire([_file(name, rev="r1")], manifest=manifest)
    report = pipeline.run(_cfg(tmp_path, dry_run=True))
    assert report.planned == []
    assert report.skipped[0]["reason"] == "이미 처리됨"


def test_revision_change_replans(tmp_path, wire):
    name = "2026-09-03_주간회의.docx"
    manifest = {
        f"id::{name}": Entry(
            file_id=f"id::{name}", revision="OLD", filename=name, status=STATUS_DONE
        )
    }
    wire([_file(name, rev="NEW")], manifest=manifest)
    report = pipeline.run(_cfg(tmp_path, dry_run=True))
    assert report.planned[0]["action"] == "update (revision changed)"


def test_real_run_requires_groupware(tmp_path, wire):
    wire([])
    with pytest.raises(ConfigError, match="그룹웨어"):
        pipeline.run(_cfg(tmp_path, dry_run=False))


def test_real_run_fans_out_and_updates_state(tmp_path, wire):
    name = "2026-09-03_주간회의.docx"
    drive, archive, gw = wire([_file(name, author="이영희")])
    cfg = _cfg(
        tmp_path,
        dry_run=False,
        groupware_base_url="https://gw",
        groupware_api_token="t",
        groupware_board_id="1",
    )
    report = pipeline.run(cfg)

    assert report.as_dict()["counts"]["processed"] == 1
    assert archive.added == ["minutes/2026/09/2026-09-03_주간회의.docx"]
    assert gw.created == ["[회의록] 2026-09-03 주간회의"]
    assert "이영희" in gw.bodies[0]  # 작성자는 Drive 최종 수정자에서
    assert archive.token == "TOKEN-NEXT"
    assert archive.committed is True
    entry = archive.saved_manifest[f"id::{name}"]
    assert entry.status == STATUS_DONE
    assert entry.groupware_post_id == "p-1"


def test_partial_failure_keeps_git_done(tmp_path, wire):
    name = "2026-09-03_주간회의.docx"

    class FlakyGroupware(FakeGroupware):
        def create_post(self, **kwargs):
            raise RuntimeError("그룹웨어 500")

    drive, archive, gw = wire([_file(name)], groupware=FlakyGroupware())
    cfg = _cfg(
        tmp_path,
        dry_run=False,
        groupware_base_url="https://gw",
        groupware_api_token="t",
        groupware_board_id="1",
    )
    report = pipeline.run(cfg)

    assert report.as_dict()["counts"]["failed"] == 1
    assert archive.added == ["minutes/2026/09/2026-09-03_주간회의.docx"]  # git 은 됨
    entry = archive.saved_manifest[f"id::{name}"]
    assert entry.status == STATUS_GIT_DONE  # 다음 회차에 그룹웨어만 재시도
    assert "그룹웨어 500" in entry.error
