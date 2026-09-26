"""Copy the audio track of a progressive MP4 into an M4A file, without ffmpeg.

TikTok and Instagram serve one MP4 holding video and audio. The AAC samples are moved as they
are (no re-encoding) into a new file that contains only that track.
"""
from __future__ import annotations

import struct
from pathlib import Path

CONTAINERS = {b'moov', b'trak', b'mdia', b'minf', b'stbl'}
COPY_BLOCK = 1024 * 1024


class AudioExtractError(Exception):
    pass


def _box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack('>I4s', 8 + len(payload), kind) + payload


def _boxes(data: bytes, start: int = 0, end: int | None = None):
    """Yield (type, box_start, payload_start, box_end) for the boxes in data[start:end]."""
    end = len(data) if end is None else end
    position = start
    while position + 8 <= end:
        size, kind = struct.unpack_from('>I4s', data, position)
        header = 8
        if size == 1:
            if position + 16 > end:
                raise AudioExtractError('Estrutura MP4 inválida.')
            size, header = struct.unpack_from('>Q', data, position + 8)[0], 16
        elif size == 0:
            size = end - position
        if size < header or position + size > end:
            raise AudioExtractError('Estrutura MP4 inválida.')
        yield kind, position, position + header, position + size
        position += size


def _top_level(source, file_size: int):
    position = 0
    while position + 8 <= file_size:
        source.seek(position)
        head = source.read(16)
        size, kind = struct.unpack('>I4s', head[:8])
        header = 8
        if size == 1 and len(head) == 16:
            size, header = struct.unpack('>Q', head[8:16])[0], 16
        elif size == 0:
            size = file_size - position
        if size < header or position + size > file_size:
            raise AudioExtractError('O arquivo de vídeo está incompleto.')
        yield kind, position, header, size
        position += size


def _find(data: bytes, start: int, end: int, kind: bytes):
    for found, box_start, payload, box_end in _boxes(data, start, end):
        if found == kind:
            return box_start, payload, box_end
    return None


def _audio_track(moov: bytes):
    """Return (trak_start, trak_end) of the first audio track in a moov payload."""
    for kind, start, payload, end in _boxes(moov):
        if kind != b'trak':
            continue
        media = _find(moov, payload, end, b'mdia')
        handler = _find(moov, media[1], media[2], b'hdlr') if media else None
        # hdlr payload: version/flags, pre_defined, handler_type
        if handler and moov[handler[1] + 8:handler[1] + 12] == b'soun':
            return start, payload, end
    return None


def _sample_table(moov: bytes, trak_payload: int, trak_end: int):
    media = _find(moov, trak_payload, trak_end, b'mdia')
    minf = _find(moov, media[1], media[2], b'minf') if media else None
    stbl = _find(moov, minf[1], minf[2], b'stbl') if minf else None
    if not stbl:
        raise AudioExtractError('O áudio do vídeo não tem tabela de amostras.')
    tables = {}
    for kind in (b'stsz', b'stsc', b'stco', b'co64'):
        box = _find(moov, stbl[1], stbl[2], kind)
        if box:
            tables[kind] = moov[box[1]:box[2]]
    if b'stsz' not in tables or b'stsc' not in tables or not (b'stco' in tables or b'co64' in tables):
        raise AudioExtractError('O áudio do vídeo não pode ser extraído deste arquivo.')

    _, sample_size, sample_count = struct.unpack_from('>III', tables[b'stsz'])
    if sample_size:
        sizes = [sample_size] * sample_count
    else:
        sizes = list(struct.unpack_from(f'>{sample_count}I', tables[b'stsz'], 12))
    entry_count = struct.unpack_from('>I', tables[b'stsc'], 4)[0]
    runs = [struct.unpack_from('>III', tables[b'stsc'], 8 + 12 * index) for index in range(entry_count)]
    if b'stco' in tables:
        count = struct.unpack_from('>I', tables[b'stco'], 4)[0]
        offsets = list(struct.unpack_from(f'>{count}I', tables[b'stco'], 8))
    else:
        count = struct.unpack_from('>I', tables[b'co64'], 4)[0]
        offsets = list(struct.unpack_from(f'>{count}Q', tables[b'co64'], 8))

    lengths, sample = [], 0
    for chunk in range(1, len(offsets) + 1):
        per_chunk = 0
        for first_chunk, samples, _ in runs:
            if first_chunk <= chunk:
                per_chunk = samples
        lengths.append(sum(sizes[sample:sample + per_chunk]))
        sample += per_chunk
    if sample != sample_count:
        raise AudioExtractError('A tabela de amostras do áudio é inconsistente.')
    return offsets, lengths


def _rewrite(data: bytes, kind: bytes, start: int, payload: int, end: int, offsets: list[int]) -> bytes:
    """Copy a box, replacing the chunk offsets and keeping everything else."""
    if kind == b'stco':
        return _box(kind, struct.pack('>II', 0, len(offsets)) + struct.pack(f'>{len(offsets)}I', *offsets))
    if kind == b'co64':
        return _box(kind, struct.pack('>II', 0, len(offsets)) + struct.pack(f'>{len(offsets)}Q', *offsets))
    if kind in CONTAINERS:
        children = b''.join(_rewrite(data, k, s, p, e, offsets) for k, s, p, e in _boxes(data, payload, end))
        return _box(kind, children)
    return bytes(data[start:end])


def _audio_moov(moov: bytes, offsets: list[int]) -> bytes:
    track = _audio_track(moov)
    header = _find(moov, 0, len(moov), b'mvhd')
    if not track or not header:
        raise AudioExtractError('Este vídeo não tem uma faixa de áudio.')
    trak_start, trak_payload, trak_end = track
    return _box(b'moov', bytes(moov[header[0]:header[2]]) +
                _rewrite(moov, b'trak', trak_start, trak_payload, trak_end, offsets))


def extract_m4a(source_path, target_path) -> Path:
    """Write the audio track of source_path to target_path as M4A and return the target."""
    source_path, target_path = Path(source_path), Path(target_path)
    temporary = target_path.with_name(target_path.name + '.part')
    try:
        with source_path.open('rb') as source:
            file_size = source_path.stat().st_size
            moov = None
            for kind, position, header, size in _top_level(source, file_size):
                if kind == b'moov':
                    source.seek(position + header)
                    moov = source.read(size - header)
            if moov is None:
                raise AudioExtractError('O arquivo de vídeo não pôde ser lido.')
            if _find(moov, 0, len(moov), b'mvex'):
                raise AudioExtractError('Este formato de vídeo (fragmentado) não permite extrair o áudio.')
            track = _audio_track(moov)
            if not track:
                raise AudioExtractError('Este vídeo não tem uma faixa de áudio.')
            old_offsets, lengths = _sample_table(moov, track[1], track[2])
            if any(offset + length > file_size for offset, length in zip(old_offsets, lengths)):
                raise AudioExtractError('O arquivo de vídeo está incompleto.')

            ftyp = _box(b'ftyp', b'M4A ' + struct.pack('>I', 0) + b'M4A mp42isom')
            # Offsets have a fixed width, so the moov size does not depend on their values.
            moov_size = len(_audio_moov(moov, [0] * len(old_offsets)))
            data_start = len(ftyp) + moov_size + 8
            new_offsets, cursor = [], data_start
            for length in lengths:
                new_offsets.append(cursor)
                cursor += length
            if cursor >= 2 ** 32 and b'stco' in moov:
                raise AudioExtractError('O áudio é grande demais para este formato.')
            new_moov = _audio_moov(moov, new_offsets)

            with temporary.open('wb') as target:
                target.write(ftyp)
                target.write(new_moov)
                target.write(struct.pack('>I4s', 8 + sum(lengths), b'mdat'))
                for offset, length in zip(old_offsets, lengths):
                    source.seek(offset)
                    remaining = length
                    while remaining:
                        block = source.read(min(remaining, COPY_BLOCK))
                        if not block:
                            raise AudioExtractError('O arquivo de vídeo está incompleto.')
                        target.write(block)
                        remaining -= len(block)
        temporary.replace(target_path)
        return target_path
    except (OSError, struct.error) as error:
        raise AudioExtractError('Não foi possível extrair o áudio deste vídeo.') from error
    finally:
        temporary.unlink(missing_ok=True)
