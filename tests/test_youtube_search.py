from youtube.search import normalize_youtube_results


def test_youtube_search_results_keep_only_canonical_shorts():
    results = normalize_youtube_results([
        {
            'url': 'https://www.youtube.com/shorts/AbCdEfGhI_j?feature=share',
            'author': ' Canal de História ',
            'description': ' Curiosidade  histórica ',
        },
        {'url': 'https://www.youtube.com/shorts/AbCdEfGhI_j'},
        {'url': 'https://www.youtube.com/watch?v=AbCdEfGhI_j'},
        {'url': 'https://example.com/shorts/AbCdEfGhI_j'},
    ])

    assert len(results) == 1
    assert results[0].url == 'https://www.youtube.com/shorts/AbCdEfGhI_j'
    assert results[0].author == 'Canal de História'
    assert results[0].description == 'Curiosidade histórica'


def test_youtube_search_uses_platform_label_when_the_card_has_no_channel():
    results = normalize_youtube_results([
        {'url': 'https://www.youtube.com/shorts/AbCdEfGhI_j', 'description': 'Título'},
    ])

    assert results[0].author == 'YouTube'
