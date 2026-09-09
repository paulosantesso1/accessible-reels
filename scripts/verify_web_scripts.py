"""Fail a release build when its embedded WebView scripts differ from source."""
from __future__ import annotations

import argparse
from pathlib import Path


def verify_web_scripts(source: Path, packaged: Path) -> None:
    expected = [path for path in source.rglob('*') if path.is_file()]
    if not expected:
        raise RuntimeError(f'Nenhum script WebView foi encontrado em {source}.')

    errors = []
    for source_file in expected:
        relative = source_file.relative_to(source)
        packaged_file = packaged / relative
        if not packaged_file.is_file():
            errors.append(f'ausente: {relative}')
        elif packaged_file.read_bytes() != source_file.read_bytes():
            errors.append(f'divergente: {relative}')
    if errors:
        raise RuntimeError('Scripts WebView inválidos no pacote: ' + '; '.join(errors))


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=root / 'ui' / 'web_scripts')
    parser.add_argument('--packaged', type=Path,
                        default=root / 'dist' / 'Accessible Reels' / '_internal' / 'ui' / 'web_scripts')
    arguments = parser.parse_args()
    verify_web_scripts(arguments.source, arguments.packaged)


if __name__ == '__main__':
    main()
