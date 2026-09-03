"""환경변수 기반 설정 로드 및 검증.

모든 설정값은 환경변수에서 온다. 코드에 하드코딩하지 않는다.
필수값이 없으면 즉시 ConfigError 를 던져 파이프라인을 세운다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:  # 로컬 개발 편의: .env 자동 로드 (운영/Jenkins 에서는 없어도 됨)
    from dotenv import load_dotenv

    load_dotenv()
except ModuleNotFoundError:  # pragma: no cover
    pass


class ConfigError(RuntimeError):
    """필수 설정 누락 등 설정 관련 오류."""


_TRUTHY = {"1", "true", "yes", "on"}


def _require(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise ConfigError(f"환경변수 {name} 가 설정되지 않았습니다")
    return val


def _optional(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Config:
    # Google Drive (항상 필요)
    gdrive_sa_key_path: Path
    gdrive_folder_id: str
    # Git 미러 저장소 (항상 필요)
    archive_repo_url: str
    archive_work_dir: Path
    archive_push: bool
    # 그룹웨어 (실제 업로드 시에만 필요 — dry-run 에서는 비어 있어도 됨)
    groupware_base_url: str
    groupware_api_token: str
    groupware_board_id: str
    # 동작 옵션
    dry_run: bool
    min_file_age_minutes: int
    slack_webhook_url: str

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            gdrive_sa_key_path=Path(_require("GDRIVE_SA_KEY_PATH")),
            gdrive_folder_id=_require("GDRIVE_FOLDER_ID"),
            archive_repo_url=_require("ARCHIVE_REPO_URL"),
            archive_work_dir=Path(_optional("ARCHIVE_WORK_DIR", ".work/meeting-archive")),
            archive_push=_optional("ARCHIVE_PUSH", "true").lower() in _TRUTHY,
            groupware_base_url=_optional("GROUPWARE_BASE_URL").rstrip("/"),
            groupware_api_token=_optional("GROUPWARE_API_TOKEN"),
            groupware_board_id=_optional("GROUPWARE_BOARD_ID"),
            dry_run=_optional("DRY_RUN", "false").lower() in _TRUTHY,
            min_file_age_minutes=int(_optional("MIN_FILE_AGE_MINUTES", "10")),
            slack_webhook_url=_optional("SLACK_WEBHOOK_URL"),
        )

    def require_groupware(self) -> None:
        """실제 업로드 직전 호출. 그룹웨어 설정이 없으면 ConfigError."""
        missing = [
            name
            for name, value in (
                ("GROUPWARE_BASE_URL", self.groupware_base_url),
                ("GROUPWARE_API_TOKEN", self.groupware_api_token),
                ("GROUPWARE_BOARD_ID", self.groupware_board_id),
            )
            if not value
        ]
        if missing:
            raise ConfigError(f"그룹웨어 설정 누락: {', '.join(missing)}")
