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


def test_missing_source_does_not_start_downloader(tmp_path):
    factory = Mock()
    with pytest.raises(VideoDownloadError):
        download_video('', 'Instagram', tmp_path, factory=factory)
    factory.assert_not_called()


def test_feed_media_fallback_and_progress(tmp_path):
    output = tmp_path / 'video.mp4'
    direct = 'https://s.cdninstagram.com/video.mp4?token=example'
    downloader = Mock()
    downloader.__enter__ = Mock(return_value=downloader)
    downloader.__exit__ = Mock(return_value=False)
    downloader.process_ie_result.side_effect = lambda info, download: (output.write_bytes(b'video') and info)
    downloader.prepare_filename.return_value = str(output)
    factory = Mock(return_value=downloader)
    progress = Mock()
    assert download_video('https://www.instagram.com/reel/ABC/', 'Instagram', tmp_path,
                          progress, direct_url=direct, factory=factory) == output
    downloader.extract_info.assert_not_called()
    assert downloader.process_ie_result.call_args.args[0]['url'] == direct
    options = factory.call_args.args[0]
    assert options['overwrites'] is False
    options['progress_hooks'][0]({'status': 'downloading', 'downloaded_bytes': 50, 'total_bytes': 100})
    progress.assert_called_with('Baixando vídeo: 50%.')


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


def test_direct_failure_uses_webpage_fallback(tmp_path):
    output = tmp_path / 'video.mp4'
    output.write_bytes(b'test')
    downloader = Mock()
    downloader.__enter__ = Mock(return_value=downloader)
    downloader.__exit__ = Mock(return_value=False)
    downloader.extract_info.return_value = {'id': 'ABC'}
    downloader.process_ie_result.side_effect = [RuntimeError('expired media URL'), {'id': 'ABC'}]
    downloader.prepare_filename.return_value = str(output)
    link = 'https://www.instagram.com/reel/ABC/'
    assert download_video(link, 'Instagram', tmp_path, direct_url='https://s.cdninstagram.com/v.mp4',
                          factory=Mock(return_value=downloader)) == output
    downloader.extract_info.assert_called_once_with(link, download=False)


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


@pytest.mark.parametrize('direct_route', [False, True])
def test_real_ytdlp_downloads_file(tmp_path, monkeypatch, direct_route):
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from yt_dlp import YoutubeDL
    from yt_dlp.extractor.common import InfoExtractor

    payload = b'local transfer fixture' * 1024
    (tmp_path / 'fixture.mp4').write_bytes(payload)
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path)))
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()

    class FixtureIE(InfoExtractor):
        _VALID_URL = r'https://www\.instagram\.com/reel/(?P<id>TEST)/'

        def _real_extract(self, url):
            return {'id': 'TEST', 'title': 'Teste de download', 'ext': 'mp4',
                    'url': f'http://127.0.0.1:{server.server_port}/fixture.mp4'}

    def factory(options):
        downloader = YoutubeDL(options, auto_init=False)
        downloader.add_info_extractor(FixtureIE())
        return downloader

    try:
        direct = None
        if direct_route:
            direct = f'http://127.0.0.1:{server.server_port}/fixture.mp4'
            monkeypatch.setattr('video_download.media_url', lambda value, platform: value if value == direct else None)
        path = download_video('https://www.instagram.com/reel/TEST/', 'Instagram',
                              tmp_path / 'output', factory=factory, direct_url=direct)
        assert path.read_bytes() == payload
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
