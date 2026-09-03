import pytest

from meeting_uploader.config import Config, ConfigError

_REQUIRED = [
    "GDRIVE_SA_KEY_PATH",
    "GDRIVE_FOLDER_ID",
    "GROUPWARE_BASE_URL",
    "GROUPWARE_API_TOKEN",
    "GROUPWARE_BOARD_ID",
    "ARCHIVE_REPO_URL",
]


@pytest.fixture
def full_env(monkeypatch):
    values = {
        "GDRIVE_SA_KEY_PATH": "./secrets/sa.json",
        "GDRIVE_FOLDER_ID": "folder123",
        "GROUPWARE_BASE_URL": "https://gw.example.com/",
        "GROUPWARE_API_TOKEN": "tok",
        "GROUPWARE_BOARD_ID": "42",
        "ARCHIVE_REPO_URL": "git@github.com:org/meeting-archive.git",
    }
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    for k in ("ARCHIVE_PUSH", "DRY_RUN", "MIN_FILE_AGE_MINUTES", "SLACK_WEBHOOK_URL"):
        monkeypatch.delenv(k, raising=False)
    return values


def test_missing_required_raises(monkeypatch):
    for k in _REQUIRED:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ConfigError):
        Config.from_env()


def test_defaults_and_normalisation(full_env):
    cfg = Config.from_env()
    assert cfg.groupware_base_url == "https://gw.example.com"  # 뒤 슬래시 제거
    assert cfg.archive_push is True
    assert cfg.dry_run is False
    assert cfg.min_file_age_minutes == 10


def test_dry_run_flag(full_env, monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")
    assert Config.from_env().dry_run is True
