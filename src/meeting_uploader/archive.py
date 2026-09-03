"""Git 미러 저장소 = 회의록 아카이브 + 파이프라인 상태 저장소.

이 저장소가 상태 DB 역할을 겸한다 (외부 DB 불필요, Jenkins 재설치에도 생존).
    state/drive_page_token   : 다음 changes.list 시작 커서
    state/manifest.json      : fileId -> 처리 상태 (git / groupware 각각)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from git import Repo

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
        if (self._dir / ".git").exists():
            repo = Repo(self._dir)
            repo.remotes.origin.pull()
        else:
            self._dir.parent.mkdir(parents=True, exist_ok=True)
            repo = Repo.clone_from(self._url, self._dir)
        self._repo = repo

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
    def add_document(self, src: Path, rel_path: str) -> str:
        """파일을 미러에 복사하고 커밋. 커밋 SHA 반환."""
        dest = self._dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
        repo = self._require_repo()
        repo.index.add([rel_path])
        commit = repo.index.commit(f"chore(minutes): add {rel_path}")
        return commit.hexsha

    def commit_state(self) -> None:
        repo = self._require_repo()
        repo.index.add([TOKEN_FILE, MANIFEST_FILE])
        if repo.is_dirty(index=True, working_tree=False):
            repo.index.commit("chore(state): update drive token and manifest")

    def push(self) -> None:
        self._require_repo().remotes.origin.push()

    def _require_repo(self) -> Repo:
        if self._repo is None:
            raise RuntimeError("sync() 를 먼저 호출해야 합니다")
        return self._repo
