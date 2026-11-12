#!/usr/bin/env python3
"""Decode every sample, reject damaged/non-finite/blank stems, check audio geometry."""
import argparse
import json
import subprocess
from pathlib import Path

def probe(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a:0',
        '-show_entries', 'stream=sample_rate,channels,duration:format=duration', '-of', 'json', str(path)],
        check=True, capture_output=True, text=True)
    obj = json.loads(result.stdout)
    if not obj.get('streams'):
        raise ValueError(f'无音频流：{path}')
    stream = obj['streams'][0]
    duration = stream.get('duration', obj.get('format', {}).get('duration'))
    return {'sample_rate': int(stream['sample_rate']), 'channels': int(stream['channels']), 'duration': float(duration)}

def validate(path, expected=None, allow_silence=False):
    import numpy as np
    import soundfile as sf
    path = Path(path)
    if not path.is_file() or path.stat().st_size < 44:
        raise ValueError(f'输出缺失或过小：{path}')
    peak, energy, count = 0.0, 0.0, 0
    with sf.SoundFile(path) as audio:
        info = {'sample_rate': audio.samplerate, 'channels': audio.channels,
                'duration': len(audio) / audio.samplerate, 'frames': len(audio)}
        for block in audio.blocks(blocksize=65536, dtype='float32', always_2d=True):
            if not np.isfinite(block).all():
                raise ValueError(f'存在 NaN/Inf：{path}')
            peak = max(peak, float(np.max(np.abs(block))))
            energy += float(np.sum(block.astype('float64') ** 2))
            count += block.size
    if count == 0 or (peak < 1e-8 and not allow_silence):
        raise ValueError(f'空白音频：{path}；若原素材确无该音轨，请人工核对。')
    if expected:
        for field in ('sample_rate', 'channels'):
            if info[field] != expected[field]:
                raise ValueError(f'{field} 不符：{info[field]} != {expected[field]}')
        if abs(info['duration'] - expected['duration']) > max(0.1, 2 / info['sample_rate']):
            raise ValueError(f'时长不符：{info["duration"]} != {expected["duration"]}')
    if not 8000 <= info['sample_rate'] <= 384000:
        raise ValueError('采样率超出支持范围 8–384 kHz')
    return dict(info, peak=peak, rms=(energy / max(count, 1)) ** .5, valid=True)

if __name__ == '__main__':
    from setup import bootstrap
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('files', nargs='+')
    p.add_argument('--reference')
    args = p.parse_args()
    bootstrap()
    try:
        expected = probe(args.reference) if args.reference else None
        print(json.dumps({f: validate(f, expected) for f in args.files}, ensure_ascii=False, indent=2))
    except Exception as exc:
        p.exit(1, f'{exc}\n')
