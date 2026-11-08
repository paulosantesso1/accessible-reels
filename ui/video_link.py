"""Recognize pasted video links without opening a separate browser session."""
import re
from urllib.parse import urlsplit

from instagram.search import validate_reel_url
from tiktok.search import validate_search_result_url
from tiktok.video_controls import VideoControlError


def parse_video_link(value):
    value = str(value or '').strip()
    if '://' not in value:
        value = 'https://' + value
    try:
        url = urlsplit(value)
        if (url.scheme != 'https' or url.username is not None or url.password is not None
                or url.port not in (None, 443) or any(c.isspace() for c in value)
                or '\\' in value):
            raise ValueError
        if url.hostname in ('instagram.com', 'www.instagram.com'):
            return 'Instagram', validate_reel_url(value)
        if url.hostname in ('tiktok.com', 'www.tiktok.com', 'live.tiktok.com'):
            if re.fullmatch(r'/t/[A-Za-z0-9_-]+/?', url.path):
                return 'TikTok', f'https://www.tiktok.com{url.path}'
            live_match = re.fullmatch(r'/(@[A-Za-z0-9_.-]+)/live/?', url.path)
            if live_match:
                return 'TikTok', f'https://www.tiktok.com/{live_match.group(1)}/live'
            if url.hostname == 'live.tiktok.com':
                direct_live = re.fullmatch(r'/(@[A-Za-z0-9_.-]+)(/live)?/?', url.path)
                if direct_live:
                    return 'TikTok', f'https://www.tiktok.com/{direct_live.group(1)}/live'
            return 'TikTok', validate_search_result_url(value)
        if url.hostname in ('vm.tiktok.com', 'vt.tiktok.com') and re.fullmatch(
                r'/[A-Za-z0-9_-]+/?', url.path):
            return 'TikTok', f'https://{url.hostname}{url.path}'
        if url.hostname in ('youtube.com', 'www.youtube.com', 'm.youtube.com'):
            from youtube.search import validate_youtube_url
            return 'YouTube', validate_youtube_url(value)
    except (ValueError, VideoControlError):
        pass
    raise VideoControlError('Cole um link de vídeo do TikTok, Reel do Instagram ou Short do YouTube.')
