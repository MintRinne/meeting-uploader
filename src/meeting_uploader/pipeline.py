"""파이프라인 오케스트레이션.

흐름
    1. 미러 저장소 clone/pull -> 상태(token, manifest) 로드
    2. token 이 있으면 Drive changes.list(증분), 없으면 폴더 전체 스캔(백필)
    3. 파일별로:
        - 파일명 파싱 (실패 -> SKIPPED)
        - cutoff / 최근수정 필터 (-> SKIPPED)
        - manifest 대조 (이미 done + 같은 revision -> SKIPPED)
        - (dry-run) 예정 동작만 기록
        - (실제)  다운로드 -> Git 미러 커밋(미완료분) -> 그룹웨어 등록(미완료분)
    4. token / manifest 갱신 커밋 & push
    5. 리포트 반환

멱등성 3단 방어
    1) Drive startPageToken  : 지난 실행 이후 변경분만
    2) manifest.json         : 파일별 git / groupware 완료 여부
    3) groupware.find_post   : 업로드 직전 동일 제목 게시글 확인

fan-out 부분 실패
    Git 성공 / 그룹웨어 실패 -> status=git_done, 다음 회차에 그룹웨어만 재시도.
    파일 단위로 예외를 격리하므로 한 건 실패가 나머지를 막지 않는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
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
from .drive import DriveClient, author_of
from .groupware import GroupwareClient, build_post_body
from .parser import FileNameError, MeetingDoc, parse_filename

log = logging.getLogger(__name__)


@dataclass
class Report:
    processed: list[dict] = field(default_factory=list)  # 실제 업로드 완료/부분완료
    planned: list[dict] = field(default_factory=list)  # dry-run 예정
    skipped: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "counts": {
                "processed": len(self.processed),
                "planned": len(self.planned),
                "skipped": len(self.skipped),
                "failed": len(self.failed),
            },
            "processed": self.processed,
            "planned": self.planned,
            "skipped": self.skipped,
            "failed": self.failed,
        }


def _revision_of(f: dict) -> str:
    return f.get("headRevisionId") or f.get("md5Checksum") or f["modifiedTime"]


def _planned_action(prior: Entry | None) -> str:
    if prior is None:
        return "create (git + groupware)"
    if prior.status == STATUS_GIT_DONE:
        return "resume (groupware only)"
    if prior.status == STATUS_FAILED:
        return "retry"
    return "update (revision changed)"


def run(cfg: Config, *, since: str | None = None) -> Report:
    report = Report()

    if not cfg.dry_run:
        cfg.require_groupware()

    drive = DriveClient(cfg.gdrive_sa_key_path)
    archive = ArchiveRepo(cfg.archive_repo_url, cfg.archive_work_dir)
    archive.sync()
    groupware = (
        None
        if cfg.dry_run
        else GroupwareClient(
            cfg.groupware_base_url, cfg.groupware_api_token, cfg.groupware_board_id
        )
    )

    manifest = archive.load_manifest()
    token = archive.read_page_token()

    if token:
        changed, new_token = drive.list_changes(token)
        log.info("changes.list: %d 건 (증분)", len(changed))
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

        doc = replace(doc, author=author_of(f) or doc.author)

        if cutoff and doc.meeting_date < cutoff:
            report.skipped.append({"file": name, "reason": f"cutoff {cutoff} 이전"})
            continue

        modified = datetime.fromisoformat(f["modifiedTime"].replace("Z", "+00:00"))
        if modified > fresh_before:
            report.skipped.append({"file": name, "reason": "최근 수정 — 다음 회차 처리"})
            continue

        revision = _revision_of(f)
        prior = manifest.get(f["id"])
        if prior and prior.status == STATUS_DONE and prior.revision == revision:
            report.skipped.append({"file": name, "reason": "이미 처리됨"})
            continue

        if cfg.dry_run:
            report.planned.append(
                {
                    "file": name,
                    "meeting_date": doc.meeting_date.isoformat(),
                    "title": doc.title,
                    "author": doc.author,
                    "revision": revision[:12],
                    "action": _planned_action(prior),
                    "post_title": doc.post_title,
                    "archive_path": doc.archive_path(),
                }
            )
            continue

        entry = prior or Entry(file_id=f["id"], revision=revision, filename=name)
        entry.revision = revision
        entry.filename = name
        try:
            _process_one(f, doc, entry, drive, archive, groupware, download_dir)
            report.processed.append(
                {
                    "file": name,
                    "status": entry.status,
                    "post_id": entry.groupware_post_id,
                    "git_path": entry.git_path,
                }
            )
        except Exception as e:  # noqa: BLE001 - 파일 단위 격리
            log.exception("처리 실패: %s", name)
            entry.error = str(e)
            # 이미 진척된 단계(git_done)는 유지 -> 다음 회차에 그룹웨어만 재시도
            if entry.status not in (STATUS_GIT_DONE, STATUS_DONE):
                entry.status = STATUS_FAILED
            report.failed.append(
                {"file": name, "status": entry.status, "error": str(e)}
            )
        finally:
            entry.touch()
            manifest[f["id"]] = entry

    if not cfg.dry_run:
        archive.write_page_token(new_token)
        archive.save_manifest(manifest)
        archive.commit_state()
        if cfg.archive_push:
            archive.push()
    else:
        log.info("dry-run: 상태(token/manifest)와 커밋은 건드리지 않음")

    return report


def _process_one(
    f: dict,
    doc: MeetingDoc,
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
        archive.add_document(
            local, rel, message=f"chore(minutes): {doc.post_title} ({doc.author})"
        )
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
