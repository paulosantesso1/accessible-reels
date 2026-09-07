"""Verified installer updates from this project's GitHub Releases."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib import error, request

from app_version import APP_NAME, APP_VERSION, GITHUB_REPOSITORY, SETUP_ASSET_NAME, SETUP_CHECKSUM_ASSET_NAME

API_URL = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
TIMEOUT_SECONDS = 20
CHUNK_SIZE = 256 * 1024


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    notes: str
    installer_url: str
    installer_size: int
    checksum_url: str


def normalize_version(value: str) -> str:
    match = re.search(r"\d+(?:\.\d+)*", str(value or ""))
    return match.group(0) if match else ""


def is_newer_version(candidate: str, current: str) -> bool:
    def key(value: str) -> tuple[int, ...]:
        return tuple(int(part) for part in normalize_version(value).split(".") if part) or (0,)
    return key(candidate) > key(current)


def release_from_payload(payload: dict, *, current_version: str = APP_VERSION) -> UpdateInfo | None:
    latest_version = normalize_version(payload.get("tag_name") or payload.get("name") or "")
    if not latest_version:
        raise UpdateError("A release não informa uma versão válida.")
    if not is_newer_version(latest_version, current_version):
        return None
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("A release não contém os arquivos da atualização.")
    by_name = {str(asset.get("name") or "").casefold(): asset for asset in assets}
    installer = by_name.get(SETUP_ASSET_NAME.casefold())
    checksum = by_name.get(SETUP_CHECKSUM_ASSET_NAME.casefold())
    if not installer or not checksum:
        raise UpdateError("A release não publicou o instalador e o checksum obrigatórios.")
    installer_url = str(installer.get("browser_download_url") or "").strip()
    checksum_url = str(checksum.get("browser_download_url") or "").strip()
    if not installer_url or not checksum_url:
        raise UpdateError("A release possui links de download incompletos.")
    return UpdateInfo(current_version, latest_version, str(payload.get("body") or "").strip(), installer_url,
                      int(installer.get("size") or 0), checksum_url)


def check_for_update() -> UpdateInfo | None:
    return release_from_payload(_fetch_json(API_URL))


def download_update(info: UpdateInfo, progress_callback=None) -> Path:
    directory = Path(tempfile.mkdtemp(prefix="accessible-reels-update-"))
    installer_path = directory / SETUP_ASSET_NAME
    try:
        _download(info.installer_url, installer_path, info.installer_size, progress_callback)
        expected = re.search(r"\b[a-fA-F0-9]{64}\b", _read_text(info.checksum_url))
        if not expected or _sha256(installer_path).casefold() != expected.group(0).casefold():
            raise UpdateError("O instalador baixado não passou na validação de segurança.")
        return installer_path
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def can_self_update() -> bool:
    return sys.platform.startswith("win") and bool(getattr(sys, "frozen", False))


def launch_installer(installer: Path) -> None:
    if not can_self_update():
        raise UpdateError("A instalação automática está disponível apenas no aplicativo instalado para Windows.")
    if not installer.is_file():
        raise UpdateError("O instalador baixado não foi encontrado.")
    runner_dir = Path(tempfile.mkdtemp(prefix="accessible-reels-setup-"))
    runner = runner_dir / SETUP_ASSET_NAME
    shutil.copy2(installer, runner)
    try:
        subprocess.Popen([str(runner), "/VERYSILENT", "/SP-", "/SUPPRESSMSGBOXES", "/NORESTART", "/NOCANCEL"],
                         cwd=runner_dir, close_fds=True)
    except OSError as exc:
        raise UpdateError("Não foi possível iniciar o instalador da atualização.") from exc


def _fetch_json(url: str) -> dict:
    try:
        payload = json.loads(_read_text(url, "application/vnd.github+json"))
    except (error.URLError, error.HTTPError, json.JSONDecodeError) as exc:
        raise UpdateError("Não foi possível verificar as atualizações no GitHub.") from exc
    if not isinstance(payload, dict):
        raise UpdateError("A resposta do GitHub para a atualização é inválida.")
    return payload


def _read_text(url: str, accept: str = "text/plain") -> str:
    with request.urlopen(request.Request(url, headers={"Accept": accept, "User-Agent": f"{APP_NAME}/{APP_VERSION}"}),
                         timeout=TIMEOUT_SECONDS) as response:
        return response.read().decode("utf-8")


def _download(url: str, target: Path, expected_size: int, callback) -> None:
    downloaded = 0
    with request.urlopen(request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"}), timeout=TIMEOUT_SECONDS) as response:
        total = int(response.headers.get("Content-Length") or expected_size or 0)
        with target.open("wb") as destination:
            while chunk := response.read(CHUNK_SIZE):
                destination.write(chunk)
                downloaded += len(chunk)
                if callback:
                    callback(downloaded, total)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()
