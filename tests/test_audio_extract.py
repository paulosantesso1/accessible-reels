import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from audio_extract import (AudioExtractError, _audio_track, _boxes, _sample_table,
                           extract_m4a)


def box(kind, payload=b''):
    return struct.pack('>I4s', 8 + len(payload), kind) + payload


def track(handler, sizes, runs, offsets):
    """A minimal trak: handler type, sample sizes, sample-to-chunk runs and chunk offsets."""
    stsz = struct.pack('>IIII', 0, 0, len(sizes), 0)[:12] + struct.pack(f'>{len(sizes)}I', *sizes)
    stsc = struct.pack('>II', 0, len(runs)) + b''.join(struct.pack('>III', *run) for run in runs)
    stco = struct.pack('>II', 0, len(offsets)) + struct.pack(f'>{len(offsets)}I', *offsets)
    stbl = box(b'stbl', box(b'stsz', stsz) + box(b'stsc', stsc) + box(b'stco', stco))
    hdlr = box(b'hdlr', struct.pack('>II', 0, 0) + handler + bytes(12))
    return box(b'trak', box(b'tkhd', bytes(84)) + box(b'mdia', hdlr + box(b'minf', stbl)))


def synthetic_mp4(path, front=True):
    video = [bytes([1]) * 40, bytes([2]) * 30]                   # two video chunks
    audio = [bytes([10]) * 5 + bytes([11]) * 7, bytes([12]) * 9,  # audio chunk 1 has two samples
             bytes([13]) * 4 + bytes([14]) * 6]                   # chunk 3 has two samples
    mdat_payload = video[0] + audio[0] + video[1] + audio[1] + audio[2]

    def build(base):
        offsets = {'v0': base, 'a0': base + 40, 'v1': base + 52, 'a1': base + 52 + 30, 'a2': base + 52 + 30 + 9}
        video_trak = track(b'vide', [40, 30], [(1, 1, 1)], [offsets['v0'], offsets['v1']])
        audio_trak = track(b'soun', [5, 7, 9, 4, 6], [(1, 2, 1), (2, 1, 1), (3, 2, 1)],
                           [offsets['a0'], offsets['a1'], offsets['a2']])
        return box(b'moov', box(b'mvhd', bytes(100)) + video_trak + audio_trak)

    ftyp = box(b'ftyp', b'isom' + bytes(4) + b'isommp42')
    if front:
        moov = build(0)
        moov = build(len(ftyp) + len(moov) + 8)
        data = ftyp + moov + box(b'mdat', mdat_payload)
    else:
        base = len(ftyp) + 8
        data = ftyp + box(b'mdat', mdat_payload) + build(base)
    path.write_bytes(data)
    return b''.join(audio)


@pytest.mark.parametrize('front', [True, False])
def test_extracts_only_the_audio_samples_in_order(tmp_path, front):
    source, target = tmp_path / 'video.mp4', tmp_path / 'audio.m4a'
    expected = synthetic_mp4(source, front)
    assert extract_m4a(source, target) == target
    data = target.read_bytes()
    assert data[4:8] == b'ftyp' and b'M4A ' in data[:16]
    moov = next(bytes(data[payload:end]) for kind, _, payload, end in _boxes(data) if kind == b'moov')
    handlers = [kind for kind, *_ in _boxes(moov)]
    assert handlers.count(b'trak') == 1                      # the video track is gone
    audio = _audio_track(moov)
    offsets, lengths = _sample_table(moov, audio[1], audio[2])
    assert b''.join(data[offset:offset + length] for offset, length in zip(offsets, lengths)) == expected
    assert bytes([1]) * 10 not in data and bytes([2]) * 10 not in data  # no video payload copied
    assert not list(tmp_path.glob('*.part'))


def test_a_video_without_audio_is_rejected(tmp_path):
    source = tmp_path / 'silent.mp4'
    source.write_bytes(box(b'ftyp', b'isom' + bytes(4)) + box(b'moov', box(b'mvhd', bytes(100)) +
                           track(b'vide', [4], [(1, 1, 1)], [0])) + box(b'mdat', bytes(4)))
    with pytest.raises(AudioExtractError, match='faixa de áudio'):
        extract_m4a(source, tmp_path / 'silent.m4a')
    assert not (tmp_path / 'silent.m4a').exists()


def test_a_truncated_file_is_rejected_without_leaving_a_partial_result(tmp_path):
    source = tmp_path / 'video.mp4'
    synthetic_mp4(source)
    source.write_bytes(source.read_bytes()[:-20])
    with pytest.raises(AudioExtractError):
        extract_m4a(source, tmp_path / 'audio.m4a')
    assert list(tmp_path.glob('audio*')) == []


def test_unreadable_input_is_reported_as_an_extraction_error(tmp_path):
    with pytest.raises(AudioExtractError):
        extract_m4a(tmp_path / 'missing.mp4', tmp_path / 'audio.m4a')


FFMPEG = shutil.which('ffmpeg') or (r'C:\ffmpeg\bin\ffmpeg.exe' if Path(r'C:\ffmpeg\bin\ffmpeg.exe').exists() else None)


@pytest.mark.skipif(FFMPEG is None, reason='ffmpeg is only used to prove the result decodes')
@pytest.mark.parametrize('flags', [['-movflags', '+faststart'], []])
def test_real_mp4_audio_decodes_identically_to_ffmpegs_own_extraction(tmp_path, flags):
    source = tmp_path / 'real.mp4'
    run = lambda *args: subprocess.run([FFMPEG, '-y', '-v', 'error', *args], capture_output=True, text=True)
    made = run('-f', 'lavfi', '-i', 'testsrc=duration=3:size=160x120:rate=25', '-f', 'lavfi',
               '-i', 'sine=frequency=440:duration=3', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
               '-shortest', *flags, str(source))
    assert made.returncode == 0, made.stderr
    ours = extract_m4a(source, tmp_path / 'ours.m4a')
    reference = tmp_path / 'reference.m4a'
    assert run('-i', str(source), '-vn', '-c:a', 'copy', str(reference)).returncode == 0

    def decoded_hash(path):
        result = run('-i', str(path), '-f', 'md5', '-')
        assert result.stderr.strip() == ''
        return result.stdout.strip()

    assert decoded_hash(ours) == decoded_hash(reference)
