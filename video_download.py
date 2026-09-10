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
from youtube.search import validate_youtube_url


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
    if platform == 'YouTube':
        return validate_youtube_url(value)
    raise VideoDownloadError('Plataforma não suportada.')


def media_url(value, platform):
    hosts = {'TikTok': ('tiktokcdn.com', 'tiktokcdn-us.com', 'tiktokcdn-eu.com', 'byteoversea.com', 'ibytedtos.com', 'muscdn.com'),
             'Instagram': ('cdninstagram.com', 'fbcdn.net'),
             'YouTube': ('googlevideo.com',)}.get(platform, ())
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


def download_video(url, platform, folder, progress=lambda message: None, *, direct_url=None):
    import subprocess
    import sys
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
    
    frozen = getattr(sys, 'frozen', False)
    root_dir = Path(sys.executable).resolve().parent if frozen else Path(__file__).resolve().parent
    exe_name = 'yt-dlp.exe' if os.name == 'nt' else 'yt-dlp'
    exe_path = root_dir / exe_name
    
    if not exe_path.is_file():
        exe_path = exe_name
    else:
        exe_path = str(exe_path)

    for index, source in enumerate(sources):
        try:
            command = [
                exe_path,
                '-f', 'best[ext=mp4]',
                '--no-playlist',
                '-P', str(folder),
                '-o', '%(extractor_key)s - %(title).120B [%(id)s].%(ext)s',
                '--windows-filenames',
                '--no-overwrites',
                '--newline',
                '--no-warnings',
                '--socket-timeout', '20',
                '--retries', '3',
                '--fragment-retries', '3',
                '--fixup', 'never',
                '--color', 'no_color',
                '--print', 'after_move:filepath'
            ]

            if source == direct:
                identifier = hashlib.sha256(source.split('?')[0].encode()).hexdigest()[:16]
                if url:
                    identifier = urlsplit(url).path.rstrip('/').split('/')[-1]
                
                command.extend([
                    '-o', f'{platform} - {platform} {identifier} [{identifier}].mp4'
                ])
                
                referer = 'https://www.tiktok.com/' if platform == 'TikTok' else 'https://www.youtube.com/' if platform == 'YouTube' else 'https://www.instagram.com/'
                command.extend(['--add-header', f'Referer:{referer}'])

            command.append(source)
            
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=creationflags
            )
            
            final_path = None
            last_percent = -10
            
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                match = re.search(r'\[download\]\s+([\d\.]+)%', line)
                if match:
                    percent = float(match.group(1))
                    if percent >= last_percent + 10:
                        last_percent = int(percent)
                        progress(f'Baixando vídeo: {last_percent}%.')
                elif line.startswith('[download] Destination:'):
                    pass
                elif line.endswith('.mp4'):
                    candidate = Path(line)
                    if candidate.is_absolute() and candidate.is_file():
                        final_path = candidate

            process.wait()
            if process.returncode != 0 or not final_path:
                raise VideoDownloadError('O download terminou sem gerar o arquivo esperado.')

            get_logger().info('Video download completed: platform=%s', platform)
            return final_path
        except Exception as error:
            get_logger().warning('Video download failed: platform=%s kind=%s', platform, type(error).__name__)
            if index + 1 == len(sources):
                raise VideoDownloadError(download_error(error)) from error
            progress('Tentando outra forma de baixar o vídeo...')

def check_for_ytdlp_updates(parent_window=None, *, local_app_data=None):
    import threading
    import wx
    from urllib import request, error
    
    # Lendo configuração
    try:
        value = json.loads(settings_path(local_app_data).read_text(encoding='utf-8'))
        check = value.get('check_ytdlp_updates', True) # Default True
    except (OSError, ValueError, AttributeError):
        check = True
        
    if not check:
        return

    def update_task():
        import subprocess
        import sys
        
        frozen = getattr(sys, 'frozen', False)
        root_dir = Path(sys.executable).resolve().parent if frozen else Path(__file__).resolve().parent
        exe_name = 'yt-dlp.exe' if os.name == 'nt' else 'yt-dlp'
        exe_path = root_dir / exe_name
        
        if not exe_path.is_file():
            return

        # 1. Obter versão local
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            process = subprocess.run([str(exe_path), "--version"], capture_output=True, text=True, creationflags=creationflags)
            if process.returncode != 0:
                return
            local_version = process.stdout.strip()
        except Exception:
            return
            
        # 2. Obter versão online do github
        try:
            req = request.Request("https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest", headers={"User-Agent": "Accessible Reels Updater"})
            with request.urlopen(req, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
                remote_version = payload.get("tag_name", "").strip()
        except Exception:
            return
            
        if not remote_version or remote_version <= local_version:
            return
            
        # 3. Perguntar e atualizar
        def prompt_and_update():
            if not parent_window:
                return
            dlg = wx.MessageDialog(
                parent_window,
                f"O motor de downloads tem uma nova versão ({remote_version}). Você tem a versão {local_version}.\n\nDeseja atualizar agora para evitar problemas no download de vídeos?",
                "Atualização Disponível",
                wx.YES_NO | wx.ICON_INFORMATION
            )
            result = dlg.ShowModal()
            dlg.Destroy()
            if result == wx.ID_YES:
                def run_update_subprocess():
                    try:
                        subprocess.run([str(exe_path), "-U"], creationflags=creationflags)
                        wx.CallAfter(lambda: wx.MessageBox("Motor de download atualizado com sucesso! Pode voltar a baixar seus vídeos.", "Atualização Concluída", wx.OK | wx.ICON_INFORMATION, parent_window))
                    except Exception as e:
                        wx.CallAfter(lambda: wx.MessageBox(f"Erro ao tentar atualizar: {e}", "Erro", wx.OK | wx.ICON_ERROR, parent_window))
                
                threading.Thread(target=run_update_subprocess, daemon=True).start()

        wx.CallAfter(prompt_and_update)

    threading.Thread(target=update_task, daemon=True).start()

