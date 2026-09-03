"""명령줄 진입점.

    python -m meeting_uploader parse <파일명>          # 파일명 파싱 확인 (자격증명 불필요)
    python -m meeting_uploader fetch --file-id <ID>    # Phase 0: Drive 파일 1건 다운로드
    python -m meeting_uploader run [--dry-run] [--since YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from .config import Config, ConfigError
from .parser import FileNameError, parse_filename


def _print_json(obj: object) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _cmd_parse(args: argparse.Namespace) -> int:
    try:
        doc = parse_filename(args.filename)
    except FileNameError as e:
        print(e, file=sys.stderr)
        return 1
    _print_json(
        {
            "meeting_date": doc.meeting_date.isoformat(),
            "title": doc.title,
            "author": doc.author,
            "ext": doc.ext,
            "post_title": doc.post_title,
            "archive_path": doc.archive_path(),
        }
    )
    return 0


def _cmd_fetch(args: argparse.Namespace) -> int:
    """Phase 0 진단 도구: Drive 자격증명만으로 파일 1건을 받아본다."""
    import os

    from .drive import DriveClient

    key_path = os.environ.get("GDRIVE_SA_KEY_PATH", "").strip()
    if not key_path:
        raise ConfigError("환경변수 GDRIVE_SA_KEY_PATH 가 설정되지 않았습니다")
    client = DriveClient(Path(key_path))
    meta = client.get_file(args.file_id)
    out = client.download(meta, Path(args.dest))
    _print_json({"downloaded": str(out), "name": meta["name"], "mimeType": meta["mimeType"]})
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from . import pipeline
    from .notifier import notify_slack

    cfg = Config.from_env()
    if args.dry_run:
        cfg = dataclasses.replace(cfg, dry_run=True)

    report = pipeline.run(cfg, since=args.since)
    data = report.as_dict()

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    Path(f"run-report-{stamp}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _print_json(data)

    c = data["counts"]
    summary = (
        f"회의록 파이프라인: 업로드 {c['uploaded']} / "
        f"건너뜀 {c['skipped']} / 실패 {c['failed']}"
    )
    notify_slack(cfg.slack_webhook_url, summary)

    return 1 if data["failed"] else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="meeting_uploader")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("parse", help="파일명 파싱 확인")
    sp.add_argument("filename")
    sp.set_defaults(func=_cmd_parse)

    sf = sub.add_parser("fetch", help="Drive 파일 1건 다운로드 (Phase 0)")
    sf.add_argument("--file-id", required=True)
    sf.add_argument("--dest", default="./_download")
    sf.set_defaults(func=_cmd_fetch)

    sr = sub.add_parser("run", help="전체 파이프라인 실행")
    sr.add_argument("--dry-run", action="store_true", help="스캔/판정만, 업로드 안 함")
    sr.add_argument("--since", metavar="YYYY-MM-DD", help="이 날짜 이전 회의록 무시")
    sr.set_defaults(func=_cmd_run)
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as e:
        print(f"설정 오류: {e}", file=sys.stderr)
        return 2
