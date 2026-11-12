#!/usr/bin/env python3
"""Check only that a completed audio file can be decoded for playback."""
import argparse
import json
import subprocess
from pathlib import Path

def probe(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a:0',
        '-show_entries', 'stream=sample_rate,channels,duration,codec_name,sample_fmt,bits_per_sample,bits_per_raw_sample,bit_rate:format=duration', '-of', 'json', str(path)],
        check=True, capture_output=True, text=True)
    obj = json.loads(result.stdout)
    if not obj.get('streams'):
        raise ValueError(f'无音频流：{path}')
    stream = obj['streams'][0]
    duration = stream.get('duration')
    if duration in (None, 'N/A'):
        duration = obj.get('format', {}).get('duration')
    def number(value):
        return int(value) if value not in (None, 'N/A', '') else 0
    return {'sample_rate': int(stream['sample_rate']), 'channels': int(stream['channels']),
            'duration': float(duration), 'codec': stream.get('codec_name'),
            'sample_format': stream.get('sample_fmt'),
            'bit_depth': number(stream.get('bits_per_raw_sample')) or number(stream.get('bits_per_sample')),
            'bit_rate': number(stream.get('bit_rate'))}

def validate(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f'输出缺失或为空文件：{path}')
    try:
        info = probe(path)
        if info['duration'] <= 0:
            raise ValueError('没有可播放的音频时长')
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', str(path),
            '-map', '0:a:0', '-vn', '-f', 'null', '-'], check=True, capture_output=True, text=True)
    except (subprocess.CalledProcessError, ValueError, KeyError, TypeError) as exc:
        detail = getattr(exc, 'stderr', None) or str(exc)
        raise ValueError(f'音频无法正常解码播放：{path}；{detail[-1000:]}') from exc
    return dict(info, playable=True, valid=True)

if __name__ == '__main__':
    from setup import bootstrap
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('files', nargs='+')
    args = p.parse_args()
    bootstrap()
    try:
        print(json.dumps({f: validate(f) for f in args.files}, ensure_ascii=False, indent=2))
    except Exception as exc:
        p.exit(1, f'{exc}\n')
