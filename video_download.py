"""Single-video downloads, independent of the embedded player."""
import json
import os
import re
import hashlib
from pathlib import Path
from urllib.parse import urlsplit

from app_logging import get_logger, sanitize
from instagram.search import validate_reel_url
from tiktok.search import validate_search_result_url
from tiktok.video_controls import VideoControlError


class VideoDownloadError(Exception):
    pass


def settings_path(local_app_data=None):
    root = Path(local_app_data or os.environ.get('LOCALAPPDATA') or Path.home())
    return root / 'Accessible Reels' / 'download-settings.json'


def load_download_folder(*, local_app_data=None):
    try:
        value = json.loads(settings_path(local_app_data).read_text(encoding='utf-8'))
        folder = value.get('folder')
        return Path(folder) if isinstance(folder, str) and folder and Path(folder).is_absolute() else None
    except (OSError, ValueError, AttributeError):
        return None


def save_download_folder(folder, *, local_app_data=None):
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    target = settings_path(local_app_data)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps({'folder': str(folder)}, ensure_ascii=False), encoding='utf-8')
    temporary.replace(target)
    return folder


def video_url(value, platform):
    if platform == 'TikTok':
        return validate_search_result_url(value)
    if platform == 'Instagram':
        return validate_reel_url(value)
    raise VideoDownloadError('Plataforma não suportada.')


def media_url(value, platform):
    hosts = {'TikTok': ('tiktokcdn.com', 'tiktokcdn-us.com', 'tiktokcdn-eu.com', 'byteoversea.com', 'ibytedtos.com', 'muscdn.com'),
             'Instagram': ('cdninstagram.com', 'fbcdn.net')}.get(platform, ())
    try:
        parsed = urlsplit(value or '')
        tiktok_play = (platform == 'TikTok' and parsed.hostname in ('www.tiktok.com', 'tiktok.com')
                       and parsed.path.rstrip('/') == '/aweme/v1/play')
        tiktok_media = (platform == 'TikTok' and (parsed.hostname or '').endswith('.tiktok.com')
                        and parsed.path.startswith('/video/tos/'))
        if (parsed.scheme == 'https' and not parsed.username and not parsed.password
                and parsed.port in (None, 443)
                and (tiktok_play or tiktok_media or any(parsed.hostname == host or (parsed.hostname or '').endswith('.' + host) for host in hosts))):
            return value
    except ValueError:
        pass
    return None


def download_error(error):
    message = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', str(error))
    if 'Unexpected response from webpage request' in message:
        return ('O TikTok não forneceu os dados do vídeo ao downloader. '
                'Não foi possível baixar também pelo endereço de reprodução. '
                'Deixe o vídeo tocar por alguns segundos e tente Ctrl+B novamente.')
    return 'Não foi possível baixar o vídeo. ' + sanitize(message)[:450]


class _DownloadLogger:
    def debug(self, message): pass
    def warning(self, message): pass
    def error(self, message): pass


def download_video(url, platform, folder, progress=lambda message: None, *, direct_url=None, factory=None):
    sources = []
    try:
        sources.append(video_url(url, platform))
    except VideoControlError:
        pass
    direct = media_url(direct_url, platform)
    get_logger().info('Video download source: platform=%s direct_available=%s direct_accepted=%s',
                      platform, bool(direct_url), bool(direct))
    if direct:
        sources.insert(0, direct)
    if not sources:
        raise VideoDownloadError('Não foi possível identificar um endereço baixável para o vídeo ativo.')
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    if factory is None:
        from yt_dlp import YoutubeDL
        factory = YoutubeDL
    last_percent = -10

    def changed(value):
        nonlocal last_percent
        if value.get('status') == 'downloading':
            total = value.get('total_bytes') or value.get('total_bytes_estimate')
            if total:
                percent = min(100, int(100 * value.get('downloaded_bytes', 0) / total))
                if percent >= last_percent + 10:
                    last_percent = percent
                    progress(f'Baixando vídeo: {percent}%.')
        elif value.get('status') == 'finished':
            progress('Download recebido. Finalizando o arquivo...')

    options = {
        # Prefer an MP4 that already contains audio and video; no FFmpeg required.
        'format': 'best[ext=mp4]', 'noplaylist': True,
        'paths': {'home': str(folder)},
        'outtmpl': '%(extractor_key)s - %(title).120B [%(id)s].%(ext)s',
        'windowsfilenames': True, 'overwrites': False,
        'quiet': True, 'no_warnings': True, 'logger': _DownloadLogger(),
        'progress_hooks': [changed], 'socket_timeout': 20, 'retries': 3,
        'fragment_retries': 3, 'fixup': 'never',
        'color': 'no_color',
    }
    for index, source in enumerate(sources):
        try:
            with factory(options) as downloader:
                if source == direct:
                    # This is an already resolved media file, not a webpage.
                    identifier = hashlib.sha256(source.split('?')[0].encode()).hexdigest()[:16]
                    if url:
                        identifier = urlsplit(url).path.rstrip('/').split('/')[-1]
                    info = {'id': identifier, 'title': f'{platform} {identifier}',
                            'extractor_key': platform, 'url': source, 'ext': 'mp4',
                            'http_headers': {'Referer': 'https://www.tiktok.com/' if platform == 'TikTok'
                                             else 'https://www.instagram.com/'}}
                else:
                    info = downloader.extract_info(source, download=False)
                if not isinstance(info, dict) or info.get('_type') in ('playlist', 'multi_video'):
                    raise VideoDownloadError('Esse link contém vários itens; não foi possível identificar um vídeo individual.')
                info = downloader.process_ie_result(info, download=True)
                path = Path(downloader.prepare_filename(info)).resolve()
                if not path.is_file():
                    raise VideoDownloadError('O download terminou sem gerar o arquivo esperado.')
            get_logger().info('Video download completed: platform=%s', platform)
            return path
        except Exception as error:
            get_logger().warning('Video download failed: platform=%s kind=%s', platform, type(error).__name__)
            if index + 1 == len(sources):
                raise VideoDownloadError(download_error(error)) from error
            progress('Tentando outra forma de baixar o vídeo...')
