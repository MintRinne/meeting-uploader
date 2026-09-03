"""Google Drive 클라이언트 (read-only).

원본은 절대 수정하지 않는다. 스코프는 drive.readonly 하나뿐.

핵심 개념
- changes.getStartPageToken / changes.list : "지난 실행 이후 무엇이 바뀌었나"를
  서버가 커서로 알려준다. 이것이 파이프라인 멱등성의 1차 방어선.
- 네이티브 Google Docs 는 바이너리가 아니므로 files.export 로 .docx 변환해 받는다.
- 업로드된 .docx/.hwp 는 files.get_media 로 원본 그대로 받는다.
"""

from __future__ import annotations

from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

_FOLDER_MIME = "application/vnd.google-apps.folder"

# 네이티브 Google 문서 -> 내보내기 MIME
_EXPORT_MIME = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
}

_FILE_FIELDS = (
    "id,name,mimeType,md5Checksum,modifiedTime,trashed,parents,headRevisionId"
)


class DriveClient:
    def __init__(self, sa_key_path: Path):
        creds = service_account.Credentials.from_service_account_file(
            str(sa_key_path), scopes=SCOPES
        )
        self._svc = build("drive", "v3", credentials=creds, cache_discovery=False)

    # --- 메타데이터 -------------------------------------------------------
    def get_file(self, file_id: str) -> dict:
        return (
            self._svc.files()
            .get(fileId=file_id, supportsAllDrives=True, fields=_FILE_FIELDS)
            .execute()
        )

    def get_start_page_token(self) -> str:
        resp = (
            self._svc.changes()
            .getStartPageToken(supportsAllDrives=True)
            .execute()
        )
        return resp["startPageToken"]

    # --- 변경 감지 -------------------------------------------------------
    def list_changes(self, page_token: str) -> tuple[list[dict], str]:
        """page_token 이후 변경된(삭제 제외) 파일 목록과 다음 시작 토큰."""
        files: list[dict] = []
        token = page_token
        while True:
            resp = (
                self._svc.changes()
                .list(
                    pageToken=token,
                    spaces="drive",
                    includeRemoved=False,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    fields=(
                        "nextPageToken,newStartPageToken,"
                        f"changes(fileId,file({_FILE_FIELDS}))"
                    ),
                )
                .execute()
            )
            for change in resp.get("changes", []):
                f = change.get("file")
                if f and not f.get("trashed") and f.get("mimeType") != _FOLDER_MIME:
                    files.append(f)
            if "nextPageToken" in resp:
                token = resp["nextPageToken"]
            else:
                return files, resp["newStartPageToken"]

    def list_folder(self, folder_id: str) -> list[dict]:
        """폴더(하위 폴더 포함) 내 전체 파일. 토큰 유실 시 백필/폴백용."""
        out: list[dict] = []
        stack = [folder_id]
        while stack:
            current = stack.pop()
            page_token = None
            while True:
                resp = (
                    self._svc.files()
                    .list(
                        q=f"'{current}' in parents and trashed=false",
                        spaces="drive",
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True,
                        pageToken=page_token,
                        fields=f"nextPageToken,files({_FILE_FIELDS})",
                    )
                    .execute()
                )
                for f in resp.get("files", []):
                    if f["mimeType"] == _FOLDER_MIME:
                        stack.append(f["id"])
                    else:
                        out.append(f)
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break
        return out

    # --- 다운로드 -------------------------------------------------------
    def download(self, file: dict, dest_dir: Path) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        mime = file.get("mimeType", "")
        if mime in _EXPORT_MIME:
            export_mime, suffix = _EXPORT_MIME[mime]
            request = self._svc.files().export_media(
                fileId=file["id"], mimeType=export_mime
            )
            out = dest_dir / f"{file['name']}{suffix}"
        else:
            request = self._svc.files().get_media(
                fileId=file["id"], supportsAllDrives=True
            )
            out = dest_dir / file["name"]

        with open(out, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _status, done = downloader.next_chunk()
        return out
