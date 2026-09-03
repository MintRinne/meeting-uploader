"""파이프라인 오케스트레이션.

흐름
    1. 미러 저장소 clone/pull -> 상태(token, manifest) 로드
    2. token 이 있으면 Drive changes.list, 없으면 폴더 전체 스캔(백필)
    3. 파일별로:
        - 파일명 파싱 (실패 -> SKIPPED)
        - cutoff / 최근수정 필터 (-> SKIPPED)
        - manifest 대조 (이미 done -> SKIPPED)
        - 다운로드 -> Git 미러 커밋(미완료분) -> 그룹웨어 등록(미완료분)
    4. token / manifest 갱신 커밋 & push
    5. 리포트 반환

fan-out 부분 실패
    Git 성공 / 그룹웨어 실패 -> status=git_done, 다음 회차에 그룹웨어만 재시도.
    파일 단위로 예외를 격리하므로 한 건 실패가 나머지를 막지 않는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from .archive import (
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_GIT_DONE,
    STATUS_PENDING,
    ArchiveRepo,
    Entry,
)
from .config import Config
from .drive import DriveClient
from .groupware import GroupwareClient, build_post_body
from .parser import FileNameError, parse_filename

log = logging.getLogger(__name__)


@dataclass
class Report:
    uploaded: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "counts": {
                "uploaded": len(self.uploaded),
                "skipped": len(self.skipped),
                "failed": len(self.failed),
            },
            "uploaded": self.uploaded,
            "skipped": self.skipped,
            "failed": self.failed,
        }


def run(cfg: Config, *, since: str | None = None) -> Report:
    report = Report()

    drive = DriveClient(cfg.gdrive_sa_key_path)
    archive = ArchiveRepo(cfg.archive_repo_url, cfg.archive_work_dir)
    archive.sync()
    groupware = GroupwareClient(
        cfg.groupware_base_url, cfg.groupware_api_token, cfg.groupware_board_id
    )

    manifest = archive.load_manifest()
    token = archive.read_page_token()

    if token:
        changed, new_token = drive.list_changes(token)
        log.info("changes.list: %d 건", len(changed))
    else:
        log.warning("저장된 page token 없음 -> 폴더 전체 스캔(백필)")
        changed = drive.list_folder(cfg.gdrive_folder_id)
        new_token = drive.get_start_page_token()
        log.info("폴더 스캔: %d 건", len(changed))

    cutoff = date.fromisoformat(since) if since else None
    fresh_before = datetime.now(UTC) - timedelta(minutes=cfg.min_file_age_minutes)
    download_dir = Path(cfg.archive_work_dir).parent / "_download"

    for f in changed:
        name = f["name"]

        try:
            doc = parse_filename(name)
        except FileNameError as e:
            log.warning("SKIP %s", e)
            report.skipped.append({"file": name, "reason": str(e)})
            continue

        if cutoff and doc.meeting_date < cutoff:
            report.skipped.append({"file": name, "reason": f"cutoff {cutoff} 이전"})
            continue

        modified = datetime.fromisoformat(f["modifiedTime"].replace("Z", "+00:00"))
        if modified > fresh_before:
            report.skipped.append({"file": name, "reason": "최근 수정 — 다음 회차 처리"})
            continue

        revision = f.get("headRevisionId") or f.get("md5Checksum") or f["modifiedTime"]
        entry = manifest.get(
            f["id"], Entry(file_id=f["id"], revision=revision, filename=name)
        )
        if entry.status == STATUS_DONE and entry.revision == revision:
            report.skipped.append({"file": name, "reason": "이미 처리됨"})
            continue

        entry.revision = revision
        entry.filename = name

        if cfg.dry_run:
            report.uploaded.append(
                {
                    "file": name,
                    "dry_run": True,
                    "post_title": doc.post_title,
                    "archive_path": doc.archive_path(),
                }
            )
            continue

        try:
            _process_one(f, doc, entry, drive, archive, groupware, download_dir)
            report.uploaded.append(
                {
                    "file": name,
                    "status": entry.status,
                    "post_id": entry.groupware_post_id,
                    "git_path": entry.git_path,
                }
            )
        except Exception as e:  # noqa: BLE001 - 파일 단위 격리
            log.exception("처리 실패: %s", name)
            entry.status = STATUS_FAILED
            entry.error = str(e)
            report.failed.append({"file": name, "error": str(e)})
        finally:
            entry.touch()
            manifest[f["id"]] = entry

    if not cfg.dry_run:
        archive.write_page_token(new_token)
        archive.save_manifest(manifest)
        archive.commit_state()
        if cfg.archive_push:
            archive.push()

    return report


def _process_one(
    f: dict,
    doc,
    entry: Entry,
    drive: DriveClient,
    archive: ArchiveRepo,
    groupware: GroupwareClient,
    download_dir: Path,
) -> None:
    local = drive.download(f, download_dir)

    # 1) Git 미러 (미완료분만)
    if entry.status in (STATUS_PENDING, STATUS_FAILED):
        rel = doc.archive_path()
        archive.add_document(local, rel)
        entry.git_path = rel
        entry.committed_at = datetime.now(UTC).isoformat()
        entry.status = STATUS_GIT_DONE
        entry.error = ""

    # 2) 그룹웨어 (미완료분만)
    if entry.status in (STATUS_GIT_DONE, STATUS_FAILED):
        existing = groupware.find_post(doc.post_title)
        result = existing or groupware.create_post(
            title=doc.post_title,
            body_html=build_post_body(doc),
            attachment=local,
        )
        entry.groupware_post_id = result.post_id
        entry.groupware_url = result.url
        entry.status = STATUS_DONE
        entry.error = ""
