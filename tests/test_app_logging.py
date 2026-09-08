import logging

from app_logging import LOGGER_NAME, configure_logging, sanitize


def _clear_handlers():
    logger = logging.getLogger(LOGGER_NAME)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()


def test_sanitize_removes_url_queries_and_credentials():
    value = sanitize('https://example.test/video?a=secret&b=2 token=private cookie: value')
    assert value == 'https://example.test/video token=*** cookie=***'


def test_configure_logging_creates_a_local_file_without_secrets(tmp_path):
    _clear_handlers()
    try:
        path = configure_logging(local_app_data=tmp_path)
        logger = logging.getLogger(LOGGER_NAME)
        logger.warning('Request failed at https://example.test/path?token=private')
        for handler in logger.handlers:
            handler.flush()
        content = path.read_text(encoding='utf-8')
        assert path == tmp_path / 'Accessible Reels' / 'logs' / 'accessible-reels.log'
        assert 'https://example.test/path' in content
        assert 'token=private' not in content
    finally:
        _clear_handlers()
