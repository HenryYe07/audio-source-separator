#!/usr/bin/env python3
"""Mac-only two-model vocal/instrumental separator. No preference is guessed."""
import argparse
import contextlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import resource
from setup import ROOT, bootstrap, device_status, lock
from model_manager import MODELS, CACHE, ensure_model
from validate_audio import probe, validate

EXTENSIONS = {'.wav', '.flac', '.mp3', '.m4a', '.aiff', '.aif'}

def select_models(model=None, goal=None):
    # Explicit model always wins, including comparison requests.
    choice = model or goal
    if not choice:
        raise ValueError('需要先确认目标：A 乐器更清晰、完整（适合扒谱）；B 伴奏更干净（适合翻唱）。')
    if choice == 'both':
        return list(MODELS)
    if choice not in MODELS:
        raise ValueError(f'不支持模型/目标：{choice}')
    return [choice]

def ffmpeg(source, target, rate, channels):
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-y', '-i', str(source),
        '-map', '0:a:0', '-vn', '-ar', str(rate), '-ac', str(channels),
        '-c:a', 'pcm_f32le', '-rf64', 'auto', str(target)], check=True, capture_output=True)

def load_separator(key, device, output):
    import torch
    from audio_separator.separator import Separator
    model = MODELS[key]
    os.environ.pop('AUDIO_SEPARATOR_MODEL_DIR', None)

    class LocalSeparator(Separator):
        def download_model_files(self, filename):
            if filename != model['checkpoint']:
                raise ValueError('拒绝加载白名单外模型')
            # Bypass the upstream online catalog and all implicit downloads.
            return filename, 'MDXC', model['name'], str(CACHE / filename), str(CACHE / model['config'])

    separator = LocalSeparator(model_file_dir=str(CACHE), output_dir=str(output),
        output_format='WAV', sample_rate=44100, log_level=logging.ERROR,
        use_soundfile=True, use_autocast=False, use_native_fp16=False,
        use_torch_compile=False, mdxc_params={'batch_size': 1, 'overlap': None,
            'override_model_segment_size': False, 'pitch_shift': 0})
    separator.torch_device = torch.device(device)
    separator.torch_device_cpu = torch.device('cpu')
    separator.torch_device_mps = torch.device('mps') if device == 'mps' else None
    separator.load_model(model['checkpoint'])
    return separator.model_instance

def worker(key, source, output, device):
    import gc
    import numpy as np
    import soundfile as sf
    import torch
    torch.set_num_threads(min(4, os.cpu_count() or 4))
    if device == 'mps':
        # Limit MPS allocations to 55% of recommended working set; CPU shares RAM.
        torch.mps.set_per_process_memory_fraction(.55)
    started = time.monotonic()
    instance = load_separator(key, device, output)
    max_mps_driver_bytes = 0
    cfg = instance.model_data_cfgdict
    rate = int(cfg.audio.get('sample_rate', 44100))
    if rate != 44100:
        raise RuntimeError(f'配置采样率发生变化：{rate}，需重新验证。')
    hop = int(cfg.model.get('stft_hop_length', cfg.audio.hop_length))
    window = hop * (int(cfg.inference.dim_t) - 1)
    # Retain complete trained inference windows; context keeps disk-block edges away from core audio.
    context = window * 2
    core = 30 * rate
    with sf.SoundFile(source) as inp, contextlib.ExitStack() as stack:
        outputs = {stem: stack.enter_context(sf.SoundFile(output / f'{stem}.wav', 'w', samplerate=rate,
            channels=2, subtype='FLOAT', format='WAV')) for stem in ('instrumental', 'vocals')}
        for start in range(0, len(inp), core):
            left = max(0, start - context)
            stop = min(len(inp), start + core)
            right = min(len(inp), stop + context)
            inp.seek(left)
            mix = inp.read(right-left, dtype='float32', always_2d=True).T.copy()
            actual = mix.shape[-1]
            if actual < window:
                mix = np.pad(mix, ((0, 0), (0, window - actual)))
            # demix bypasses the framework's peak normalization and output quantization.
            with torch.inference_mode():
                sources = {str(k).lower(): v for k, v in instance.demix(mix).items()}
            if device == 'mps':
                max_mps_driver_bytes = max(max_mps_driver_bytes, torch.mps.driver_allocated_memory())
            if 'other' in sources:
                sources['instrumental'] = sources.pop('other')
            if 'instrumental' not in sources and 'vocals' in sources:
                sources['instrumental'] = mix - sources['vocals']
            if 'vocals' not in sources and 'instrumental' in sources:
                sources['vocals'] = mix - sources['instrumental']
            for stem, out in outputs.items():
                result = sources[stem][:, start-left:stop-left].T
                if result.shape != (stop-start, 2) or not np.isfinite(result).all():
                    raise RuntimeError(f'{stem} 推理长度异常或出现 NaN/Inf')
                out.write(result)
            del sources, mix
            gc.collect()
            if device == 'mps':
                torch.mps.empty_cache()
    (output / 'metrics.json').write_text(json.dumps({'seconds': time.monotonic() - started,
        'max_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'mps_driver_bytes_observed_after_blocks': max_mps_driver_bytes}))

def reserve(base):
    base.parent.mkdir(parents=True, exist_ok=True)
    for index in range(1, 10000):
        candidate = base if index == 1 else base.with_name(f'{base.name}_{index}')
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError('无法分配无冲突的输出目录')

def process(source, key, base, requested_device):
    info = probe(source)
    if info['channels'] not in (1, 2):
        raise ValueError('当前模型仅可靠支持单声道和立体声；多声道输入需要另行确认转换。')
    if not 8000 <= info['sample_rate'] <= 384000 or info['duration'] <= 0:
        raise ValueError('输入采样率或时长异常')
    ensure_model(key)
    status = device_status()
    device = status['device'] if requested_device == 'auto' else requested_device
    if device == 'mps' and not status['mps_available']:
        raise RuntimeError(status['reason'])
    notices = []
    if requested_device == 'auto' and device == 'cpu':
        notices.append(status['reason'])
    if info['sample_rate'] != 44100:
        notices.append(f'模型固定使用 44100 Hz，内部重采样后恢复输出为 {info["sample_rate"]} Hz。')
    destination = reserve(base)
    try:
        with tempfile.TemporaryDirectory(prefix='.separating-', dir=destination.parent) as temp:
            temp = Path(temp)
            decoded = temp / 'input.wav'
            ffmpeg(source, decoded, 44100, 2)
            raw = temp / 'raw'
            raw.mkdir()
            log = temp / 'inference.log'
            with log.open('w') as stream:
                command = [sys.executable, str(Path(__file__).resolve()), '--worker', key,
                    str(decoded), str(raw), device]
                result = subprocess.run(command, stdout=stream, stderr=stream)
                if result.returncode and device == 'mps':
                    cause = log.read_text()[-2400:]
                    # Retry only device/memory failures; a damaged model is not a GPU error.
                    if any(t in cause.lower() for t in ('mps', 'metal', 'out of memory', 'not implemented')):
                        notices.append('MPS 推理失败，已在独立进程回退 CPU。原因：' + cause[-600:])
                        device = 'cpu'
                        command[-1] = device
                        result = subprocess.run(command, stdout=stream, stderr=stream)
                if result.returncode:
                    raise RuntimeError(f'模型加载或推理失败（退出码 {result.returncode}）：' + log.read_text()[-3000:])
            staged = temp / 'validated'
            staged.mkdir()
            checks = {}
            for stem in ('instrumental', 'vocals'):
                target = staged / f'{stem}.wav'
                ffmpeg(raw / f'{stem}.wav', target, info['sample_rate'], info['channels'])
                checks[stem] = validate(target, info)
            report = {'success': True, 'model': MODELS[key]['name'], 'device': device,
                'input': str(source), 'output': str(destination), 'notices': notices, 'validation': checks,
                'runtime': json.loads((raw / 'metrics.json').read_text())}
            (staged / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
            # Publish both stems only after both decode and pass validation.
            for file in staged.iterdir():
                file.replace(destination / file.name)
            return report
    except BaseException:
        # No partial stems are published on failure.
        for name in ('instrumental.wav', 'vocals.wav', 'result.json'):
            (destination / name).unlink(missing_ok=True)
        destination.rmdir()
        raise

def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--worker':
        _, _, key, source, output, device = sys.argv
        worker(key, Path(source), Path(output), device)
        return
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('inputs', nargs='+', help='音频文件或目录（目录只读取其直接子文件）')
    p.add_argument('--goal', choices=['detail', 'clean', 'both'])
    p.add_argument('--model', choices=['detail', 'clean', 'both'], help='明确指定模型，优先于 goal')
    p.add_argument('--output', type=Path, help='输出根目录')
    p.add_argument('--device', choices=['auto', 'mps', 'cpu'], default='auto')
    args = p.parse_args()
    try:
        keys = select_models(args.model, args.goal)
        files = []
        for entry in args.inputs:
            path = Path(entry).expanduser().resolve()
            candidates = sorted(path.iterdir()) if path.is_dir() else [path]
            for file in candidates:
                if file.is_file() and file.suffix.lower() in EXTENSIONS and file not in files:
                    files.append(file)
            if not path.exists() or (path.is_file() and path.suffix.lower() not in EXTENSIONS):
                raise ValueError(f'文件缺失或格式不支持：{path}')
        if not files:
            raise ValueError('没有找到支持的音频文件')
        bootstrap()
        os.environ.setdefault('PYTORCH_ENABLE_MPS_FALLBACK', '1')
        failures = 0
        # Serial jobs and child processes keep at most one large model resident.
        with lock(ROOT / '.inference.lock'):
            for file in files:
                for key in keys:
                    base = (args.output.expanduser().resolve() if args.output else file.parent / 'output') / file.stem
                    if len(keys) == 2:
                        base = base / key
                    try:
                        print(json.dumps(process(file, key, base, args.device), ensure_ascii=False), flush=True)
                    except Exception as exc:
                        failures += 1
                        print(json.dumps({'success': False, 'input': str(file), 'model': MODELS[key]['name'],
                            'error': str(exc)}, ensure_ascii=False), flush=True)
        if failures:
            raise SystemExit(1)
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        p.exit(1, f'{exc}\n')

if __name__ == '__main__':
    main()
