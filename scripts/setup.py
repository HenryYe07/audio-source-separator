#!/usr/bin/env python3
"""Isolated, repeatable runtime bootstrap; never installs into the caller's Python."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import fcntl
import hashlib
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / '.venv'
PYTHON = ENV / 'bin/python'
PACKAGES = ['audio-separator[cpu]==0.48.0', 'torch==2.13.0']
REQUIREMENTS = ROOT / 'references/requirements-macos-arm64-py311.txt'

@contextmanager
def lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)

def ensure():
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise RuntimeError('此运行器需要 macOS Apple Silicon，不能在远程 Linux 容器执行本机 MPS。')
    with lock(ROOT / '.runtime.lock'):
        if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
            brew = shutil.which('brew')
            if not brew:
                raise RuntimeError('缺少 ffmpeg/ffprobe 且没有 Homebrew，无法自动安装；请安装 FFmpeg 后重试。')
            print('首次安装缺失的 FFmpeg（Homebrew）；不修改已有 Python 或 UVR5。', file=sys.stderr)
            env = dict(os.environ, HOMEBREW_NO_AUTO_UPDATE='1', HOMEBREW_NO_INSTALL_UPGRADE='1')
            subprocess.run([brew, 'install', 'ffmpeg'], check=True, env=env)
            if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
                raise RuntimeError('FFmpeg 安装后不在 PATH，请将 Homebrew bin 目录加入 PATH。')
        marker = ENV / 'audio-source-separator.json'
        expected = {'packages': PACKAGES, 'python': '3.11', 'root': str(ROOT),
                    'requirements_sha256': hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()}
        if marker.exists() and json.loads(marker.read_text()) == expected and PYTHON.exists():
            return PYTHON
        base = getattr(sys, '_base_executable', sys.executable) if sys.version_info[:2] == (3, 11) else shutil.which('python3.11')
        if not base or not Path(base).exists():
            raise RuntimeError('需要原生 arm64 Python 3.11。请安装后重试；不会修改系统 Python。')
        # A moved venv is not portable: recreate only this skill-owned environment.
        if ENV.exists():
            if not (ENV / 'pyvenv.cfg').exists():
                raise RuntimeError(f'{ENV} 不是虚拟环境，拒绝覆盖。')
            shutil.rmtree(ENV)
        subprocess.run([base, '-m', 'venv', str(ENV)], check=True)
        subprocess.run([str(PYTHON), '-m', 'pip', 'install', '--upgrade', 'pip'], check=True)
        subprocess.run([str(PYTHON), '-m', 'pip', 'install', '-r', str(REQUIREMENTS), *PACKAGES], check=True)
        subprocess.run([str(PYTHON), '-m', 'pip', 'check'], check=True)
        subprocess.run([str(PYTHON), '-c', 'import torch, soundfile; from audio_separator.separator import Separator'], check=True)
        marker.write_text(json.dumps(expected))
    return PYTHON

def bootstrap():
    python = ensure()
    if Path(sys.prefix).resolve() != ENV.resolve():
        os.execv(str(python), [str(python), *sys.argv])

def device_status():
    import torch
    built = torch.backends.mps.is_built()
    available = torch.backends.mps.is_available()
    probe_error = None
    if available:
        try:
            # Availability alone does not prove this process can submit a Metal operation.
            with torch.inference_mode():
                sample = torch.ones((8, 8), device='mps')
                product = sample @ sample
                torch.mps.synchronize()
                if product.device.type != 'mps' or product[0, 0].item() != 8:
                    raise RuntimeError('MPS 矩阵运算检查未通过')
                del sample, product
        except Exception as exc:
            available = False
            probe_error = str(exc)
    if available:
        reason = 'MPS GPU 矩阵运算实测通过'
    elif probe_error:
        reason = 'MPS 可检测但 GPU 运算失败：' + probe_error
    elif built:
        reason = ('PyTorch 含 MPS 支持，但当前进程无法访问 GPU；可能受执行沙箱、Metal 访问权限或系统环境限制。'
                  '请在本机终端或宿主允许访问 GPU 的执行环境中重新运行 setup.py；不要直接判定硬件不支持。')
    else:
        reason = '当前 PyTorch 未编译 MPS 支持；需要原生 arm64、支持 MPS 的 PyTorch。'
    return {'platform': platform.platform(), 'machine': platform.machine(), 'torch': torch.__version__,
            'mps_built': built, 'mps_available': available, 'mps_compute_verified': available,
            'device': 'mps' if available else 'cpu',
            'reason': reason}

if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    bootstrap()
    print(json.dumps(device_status(), ensure_ascii=False, indent=2))
