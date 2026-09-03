import pytest

from meeting_uploader.config import Config, ConfigError

_ALWAYS_REQUIRED = [
    "GDRIVE_SA_KEY_PATH",
    "GDRIVE_FOLDER_ID",
    "ARCHIVE_REPO_URL",
]
_GROUPWARE = ["GROUPWARE_BASE_URL", "GROUPWARE_API_TOKEN", "GROUPWARE_BOARD_ID"]


@pytest.fixture
def base_env(monkeypatch):
    """dry-run 에 충분한 최소 환경 (그룹웨어 없음)."""
    values = {
        "GDRIVE_SA_KEY_PATH": "./secrets/sa.json",
        "GDRIVE_FOLDER_ID": "folder123",
        "ARCHIVE_REPO_URL": "https://github.com/org/meeting-archive.git",
    }
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    for k in (*_GROUPWARE, "ARCHIVE_PUSH", "DRY_RUN", "MIN_FILE_AGE_MINUTES", "SLACK_WEBHOOK_URL"):
        monkeypatch.delenv(k, raising=False)
    return values


def test_missing_always_required_raises(monkeypatch):
    for k in _ALWAYS_REQUIRED:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ConfigError):
        Config.from_env()


def test_groupware_optional_for_dry_run(base_env):
    cfg = Config.from_env()  # 그룹웨어 없어도 로드된다
    assert cfg.groupware_base_url == ""


def test_require_groupware_raises_when_absent(base_env):
    with pytest.raises(ConfigError, match="그룹웨어 설정 누락"):
        Config.from_env().require_groupware()


def test_require_groupware_ok_when_present(base_env, monkeypatch):
    monkeypatch.setenv("GROUPWARE_BASE_URL", "https://gw.example.com/")
    monkeypatch.setenv("GROUPWARE_API_TOKEN", "tok")
    monkeypatch.setenv("GROUPWARE_BOARD_ID", "42")
    cfg = Config.from_env()
    cfg.require_groupware()  # raises 하지 않음
    assert cfg.groupware_base_url == "https://gw.example.com"  # 뒤 슬래시 제거


def test_defaults(base_env):
    cfg = Config.from_env()
    assert cfg.archive_push is True
    assert cfg.dry_run is False
    assert cfg.min_file_age_minutes == 10


def test_dry_run_flag(base_env, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")
    assert Config.from_env().dry_run is True
