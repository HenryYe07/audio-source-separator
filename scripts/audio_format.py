"""Output encoding choices; source properties are the default, never stream-copy separated audio."""
from pathlib import Path
import subprocess

FORMATS = ('source', 'wav', 'flac', 'mp3', 'm4a', 'aiff')

def output_spec(source, info, requested='source'):
    suffix = Path(source).suffix.lower().lstrip('.')
    kind = ('aiff' if suffix == 'aif' else suffix) if requested == 'source' else requested
    if kind not in FORMATS[1:]:
        raise ValueError(f'不支持的输出格式：{kind}')
    extension = suffix if requested == 'source' else kind
    bits = info.get('bit_depth', 0) or 24
    source_codec = info.get('codec', '')
    notices = []
    options = []
    if kind in ('wav', 'aiff'):
        endian = 'le' if kind == 'wav' else 'be'
        supported = {f'pcm_{sample}{endian}' for sample in ('s16', 's24', 's32', 'f32', 'f64')}
        supported.add('pcm_u8' if kind == 'wav' else 'pcm_s8')
        depth = 16 if bits <= 16 else 24 if bits <= 24 else 32
        fallback = f'pcm_s{depth}{endian}'
        if source_codec.startswith(('pcm_f32', 'pcm_f64')):
            fallback = source_codec[:-2] + endian
        codec = source_codec if source_codec in supported else fallback
        options = ['-c:a', codec]
        if kind == 'wav':
            options += ['-rf64', 'auto']
    elif kind == 'flac':
        codec = 'flac'
        depth = 16 if bits <= 16 else 24
        options = ['-c:a', codec, '-sample_fmt', 's16' if depth == 16 else 's32',
                   '-bits_per_raw_sample', str(depth)]
        if bits > 24:
            notices.append('FLAC 输出采用 24-bit；原始超过 24-bit 的位深无法原样保留。')
    elif kind == 'm4a' and source_codec == 'alac':
        codec = 'alac'
        options = ['-c:a', codec, '-sample_fmt', 's16p' if bits <= 16 else 's32p']
    else:
        codec = 'libmp3lame' if kind == 'mp3' else 'aac'
        bitrate = info.get('bit_rate', 0) if source_codec in ('mp3', 'aac') else 0
        bitrate = bitrate or 192000
        if kind == 'mp3':
            rates = (8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 192, 224, 256, 320)
            bitrate = min(rates, key=lambda rate: abs(rate * 1000 - bitrate)) * 1000
        options = ['-c:a', codec, '-b:a', str(bitrate)]
        notices.append('输出为有损编码，按源文件可读取的音频平均码率尽量匹配；原 VBR 设置和编码器私有参数不能完全复刻。')
    return {'format': kind, 'extension': extension, 'sample_rate': info['sample_rate'],
            'channels': info['channels'], 'encoder': codec, 'options': options, 'notices': notices}

def encode(source, target, spec):
    result = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-y', '-i', str(source),
        '-map', '0:a:0', '-map_metadata', '-1', '-vn', '-ar', str(spec['sample_rate']),
        '-ac', str(spec['channels']), *spec['options'], str(target)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('无法按所选格式和源参数编码：' + result.stderr[-1500:])
