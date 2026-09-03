"""Git 미러 저장소 = 회의록 아카이브 + 파이프라인 상태 저장소.

이 저장소가 상태 DB 역할을 겸한다 (외부 DB 불필요, Jenkins 재설치에도 생존).
    state/drive_page_token   : 다음 changes.list 시작 커서
    state/manifest.json      : fileId -> 처리 상태 (git / groupware 각각)
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import stat
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from git import Repo

log = logging.getLogger(__name__)


def _force_rmtree(path: Path) -> None:
    """Windows 에서 .git 팩파일 등 읽기전용 파일까지 지운다."""

    def _on_error(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    shutil.rmtree(path, onexc=_on_error)

TOKEN_FILE = "state/drive_page_token"
MANIFEST_FILE = "state/manifest.json"

# 상태 값
STATUS_PENDING = "pending"
STATUS_GIT_DONE = "git_done"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


@dataclass
class Entry:
    file_id: str
    revision: str
    filename: str
    git_path: str = ""
    committed_at: str = ""
    groupware_post_id: str = ""
    groupware_url: str = ""
    status: str = STATUS_PENDING
    error: str = ""
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def touch(self) -> None:
        self.updated_at = datetime.now(UTC).isoformat()


class ArchiveRepo:
    def __init__(self, repo_url: str, work_dir: Path):
        self._url = repo_url
        self._dir = Path(work_dir)
        self._repo: Repo | None = None

    @property
    def path(self) -> Path:
        return self._dir

    def sync(self) -> None:
        """미러를 원격의 최신 상태로 맞춘다.

        미러는 우리가 전적으로 관리하는 대상이므로, 로컬 변경을 보존하려 애쓰지 않고
        원격 기준으로 강제 동기화한다 (fetch + reset --hard). 커밋이 없는 빈 저장소는
        그대로 재사용하고, 기존 클론이 손상됐으면 통째로 다시 클론한다.
        """
        if (self._dir / ".git").exists() and self._refresh():
            return
        if self._dir.exists():
            _force_rmtree(self._dir)
        self._dir.parent.mkdir(parents=True, exist_ok=True)
        self._repo = Repo.clone_from(self._url, self._dir)

    def _refresh(self) -> bool:
        try:
            repo = Repo(self._dir)
            repo.remotes.origin.fetch(prune=True)
        except Exception:
            log.warning("기존 미러 fetch 실패 -> 새로 clone", exc_info=True)
            return False

        try:
            tracking = repo.active_branch.tracking_branch()
        except (TypeError, ValueError):  # detached / unborn (빈 저장소)
            tracking = None

        if tracking is not None:
            try:
                repo.git.reset("--hard", tracking.name)
                repo.git.clean("-ffd")
            except Exception:
                log.warning("기존 미러 reset 실패 -> 새로 clone", exc_info=True)
                return False

        self._repo = repo
        return True

    # --- 상태 파일 I/O ------------------------------------------------
    def read_page_token(self) -> str | None:
        p = self._dir / TOKEN_FILE
        if not p.exists():
            return None
        return p.read_text(encoding="utf-8").strip() or None

    def write_page_token(self, token: str) -> None:
        p = self._dir / TOKEN_FILE
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(token + "\n", encoding="utf-8")

    def load_manifest(self) -> dict[str, Entry]:
        p = self._dir / MANIFEST_FILE
        if not p.exists():
            return {}
        raw = json.loads(p.read_text(encoding="utf-8"))
        return {k: Entry(**v) for k, v in raw.items()}

    def save_manifest(self, manifest: dict[str, Entry]) -> None:
        p = self._dir / MANIFEST_FILE
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {k: asdict(v) for k, v in sorted(manifest.items())}
        p.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    # --- 커밋 --------------------------------------------------------
    def add_document(self, src: Path, rel_path: str, *, message: str | None = None) -> str:
        """파일을 미러에 복사하고 커밋. 커밋 SHA 반환."""
        dest = self._dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
        repo = self._require_repo()
        repo.index.add([rel_path])
        commit = repo.index.commit(message or f"chore(minutes): add {rel_path}")
        return commit.hexsha

    def commit_state(self) -> None:
        repo = self._require_repo()
        paths = [p for p in (TOKEN_FILE, MANIFEST_FILE) if (self._dir / p).exists()]
        if not paths:
            return
        repo.index.add(paths)
        if repo.is_dirty(index=True, working_tree=False):
            repo.index.commit("chore(state): update drive token and manifest")

    def push(self) -> None:
        repo = self._require_repo()
        # 현재 브랜치를 원격에 push (upstream 이 없으면 생성)
        repo.git.push("origin", "HEAD", set_upstream=True)

    def _require_repo(self) -> Repo:
        if self._repo is None:
            raise RuntimeError("sync() 를 먼저 호출해야 합니다")
        return self._repo
