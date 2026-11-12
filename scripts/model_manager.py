#!/usr/bin/env python3
"""Allowlisted downloads, atomic writes, pinned upstream SHA-256, offline reuse."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import ssl
import urllib.request
from setup import ROOT, lock

MODELS = json.loads((ROOT / 'references/models.json').read_text())
CACHE = ROOT / 'models'

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def ensure_model(key, verify=False):
    model = MODELS[key]
    CACHE.mkdir(parents=True, exist_ok=True)
    with lock(CACHE / '.download.lock'):
        for filename, spec in model['files'].items():
            target = CACHE / filename
            receipt = CACHE / (filename + '.verified.json')
            stamp = None
            if target.exists():
                stat = target.stat()
                stamp = {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'sha256': spec['sha256']}
                try:
                    if not verify and json.loads(receipt.read_text()) == stamp:
                        continue
                except (OSError, ValueError):
                    pass
                if digest(target) == spec['sha256']:
                    receipt.write_text(json.dumps(stamp))
                    continue
                # Never silently replace a corrupt local checkpoint.
                raise RuntimeError(f'模型完整性校验失败：{target}。移走此文件后重试下载。')
            if verify:
                raise RuntimeError(f'本地文件缺失：{target}；--verify 不下载文件。')
            partial = target.with_suffix(target.suffix + '.part')
            errors = []
            for url in spec['urls']:
                try:
                    print(f'首次下载：{filename}', file=sys.stderr)
                    request = urllib.request.Request(url, headers={'User-Agent': 'audio-source-separator/1.0'})
                    context = ssl.create_default_context()
                    if ssl.get_default_verify_paths().cafile is None and Path('/etc/ssl/cert.pem').exists():
                        context.load_verify_locations('/etc/ssl/cert.pem')
                    with urllib.request.urlopen(request, timeout=90, context=context) as response, partial.open('wb') as out:
                        while block := response.read(1024 * 1024):
                            out.write(block)
                    if digest(partial) != spec['sha256']:
                        raise RuntimeError('SHA-256 与上游发布值不符')
                    partial.replace(target)
                    stat = target.stat()
                    receipt.write_text(json.dumps({'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'sha256': spec['sha256']}))
                    break
                except Exception as exc:
                    errors.append(f'{url}: {exc}')
                    partial.unlink(missing_ok=True)
            else:
                raise RuntimeError(f'{filename} 下载失败：' + '; '.join(errors))
    return model

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', choices=[*MODELS, 'both'], required=True)
    p.add_argument('--verify', action='store_true', help='重新计算本地 SHA-256，不访问网络')
    a = p.parse_args()
    try:
        for key in MODELS if a.model == 'both' else [a.model]:
            ensure_model(key, a.verify)
            print(json.dumps({'model': key, 'status': 'ready', 'directory': str(CACHE)}))
    except Exception as exc:
        p.exit(1, f'{exc}\n')
