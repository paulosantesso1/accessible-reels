from unittest.mock import Mock

import pytest

from video_download import download_video, media_url, VideoDownloadError, save_download_folder, load_download_folder, download_error
from ui.download_controls import DownloadControlsMixin


def test_folder_persists(tmp_path):
    folder = save_download_folder(tmp_path / 'videos', local_app_data=tmp_path)
    assert folder.is_dir()
    assert load_download_folder(local_app_data=tmp_path) == folder


@pytest.mark.parametrize('url', ['blob:https://www.instagram.com/123', 'file:///video.mp4',
                                'https://cdninstagram.com.evil.test/a.mp4', 'https://user@cdninstagram.com/a'])
def test_invalid_direct_sources(url):
    assert media_url(url, 'Instagram') is None


def test_download_errors_are_readable():
    assert '\x1b' not in download_error('\x1b[0;31mERROR:\x1b[0m failed')
    message = download_error('\x1b[0;31mERROR:\x1b[0m Unexpected response from webpage request; yt-dlp -U')
    assert 'Ctrl+B' in message
    assert 'yt-dlp -U' not in message


def test_tiktok_play_endpoint_is_media_but_feed_is_not():
    url = 'https://www.tiktok.com/aweme/v1/play/?video_id=example'
    assert media_url(url, 'TikTok') == url
    assert media_url('https://www.tiktok.com/foryou', 'TikTok') is None
    prime = 'https://v16-webapp-prime.us.tiktok.com/video/tos/useast5/example?signature=test'
    assert media_url(prime, 'TikTok') == prime
    assert media_url('https://v16-webapp-prime.us.tiktok.com/foryou', 'TikTok') is None
    assert media_url('https://v16-webapp-prime.us.tiktok.com.evil.test/video/tos/example', 'TikTok') is None


@pytest.mark.parametrize('platform', ['TikTok', 'Instagram'])
def test_ctrl_b_resolves_fresh_feed_video(platform):
    frame = Mock(_download_busy=False, _active_name=platform)
    frame.activities.GetSelection.return_value = 0
    client = Mock(pending=None)
    frame.clients = {platform: client}
    DownloadControlsMixin.start_video_download(frame)
    assert client.execute.call_args.args[:2] == ('download_link', None)
    result = {'ok': True, 'link': 'fresh-video'}
    client.execute.call_args.args[2](result)
    frame._download_resolved.assert_called_once_with(platform, result)


def test_cancel_folder_releases_download():
    frame = Mock(_closing_app=False, _download_folder=None, _download_busy=True)
    frame.choose_download_file.return_value = None
    DownloadControlsMixin._download_resolved(frame, 'Instagram', {'ok': True, 'link': 'video'})
    assert frame._download_busy is False


def test_no_duplicate_download():
    frame = Mock(_download_busy=True)
    DownloadControlsMixin.start_video_download(frame)
    frame.current.assert_not_called()


def test_progress_does_not_interrupt_speech():
    frame = Mock(_closing_app=False)
    DownloadControlsMixin._download_progress(frame, 'Baixando: 50%.')
    frame.SetStatusText.assert_called_once_with('Baixando: 50%.')
    frame.status.assert_not_called()


def test_download_asks_folder_even_when_previously_saved(tmp_path):
    frame = Mock(_closing_app=False, _download_folder=tmp_path, _download_busy=True)
    frame.choose_download_file.return_value = None
    DownloadControlsMixin._download_resolved(frame, 'TikTok', {'ok': True, 'link': 'video'})
    frame.choose_download_file.assert_called_once()
    frame._start_download_worker.assert_not_called()
    assert frame._download_busy is False


from unittest.mock import patch

def test_subprocess_parses_progress_and_returns_path(tmp_path):
    output_file = tmp_path / "video.mp4"
    output_file.touch()

    # Simulando a saída do terminal do yt-dlp.exe
    fake_stdout = [
        "[download] Destination: video.f137.mp4\n",
        "[download]  10.0% of ~ 10.00MiB at  1.00MiB/s ETA 00:10\n",
        "[download]  25.5% of ~ 10.00MiB at  1.00MiB/s ETA 00:08\n",
        "[download] 100.0% of ~ 10.00MiB at  1.00MiB/s ETA 00:00\n",
        f"{output_file}\n"
    ]

    mock_process = Mock()
    mock_process.stdout = fake_stdout
    mock_process.returncode = 0

    progress = Mock()
    
    with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
        result = download_video("https://www.instagram.com/reel/ABC/", "Instagram", tmp_path, progress)

    # Verifica se acionou o subprocess.Popen
    assert mock_popen.called
    command = mock_popen.call_args.args[0]
    assert "--newline" in command
    assert "--print" in command
    assert "after_move:filepath" in command

    # Verifica se extraiu a porcentagem
    progress.assert_any_call("Baixando vídeo: 10%.")
    progress.assert_any_call("Baixando vídeo: 25%.")
    progress.assert_any_call("Baixando vídeo: 100%.")

    # Verifica o caminho final
    assert result == output_file


def test_subprocess_fails_gracefully(tmp_path):
    mock_process = Mock()
    mock_process.stdout = ["[download] ERROR: Falha de rede\n"]
    mock_process.returncode = 1

    with patch("subprocess.Popen", return_value=mock_process):
        with pytest.raises(VideoDownloadError, match="O download terminou sem gerar o arquivo esperado"):
            download_video("https://www.tiktok.com/@user/video/123", "TikTok", tmp_path)
from unittest.mock import patch
