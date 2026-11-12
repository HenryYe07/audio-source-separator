"""Small offline regression suite. Run with this skill's .venv/bin/python -m unittest discover -s tests."""
import json
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import patch
import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import model_manager as mm
import separate as separation
from separate import select_models, reserve
from validate_audio import validate
from validate_audio import probe
from audio_format import output_spec, encode

class RuntimeTests(unittest.TestCase):
    def test_source_mp3_is_exported_and_checked_only_after_encoding(self):
        original_run = subprocess.run
        def run(command, **kwargs):
            if '--worker' not in command:
                return original_run(command, **kwargs)
            source, output = Path(command[-3]), Path(command[-2])
            audio, rate = sf.read(source, always_2d=True)
            for stem in ('instrumental', 'vocals'):
                sf.write(output / f'{stem}.wav', audio*.5, rate, subtype='FLOAT')
            (output / 'metrics.json').write_text('{}')
            return subprocess.CompletedProcess(command, 0)
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            raw = directory / 'input.wav'
            source = directory / 'input.mp3'
            sf.write(raw, np.zeros((24000, 2)), 48000, subtype='PCM_24')
            encode(raw, source, output_spec(raw, probe(raw), 'mp3'))
            with patch.object(separation, 'ensure_model'), \
                    patch.object(separation, 'device_status', return_value={'device': 'cpu'}), \
                    patch.object(separation.subprocess, 'run', side_effect=run), \
                    patch.object(separation, 'validate', wraps=validate) as check:
                report = separation.process(source, 'detail', directory / 'result', 'cpu')
            self.assertTrue(report['success'])
            self.assertEqual(report['output_format'], 'mp3')
            self.assertEqual(check.call_count, 2)
            for call in check.call_args_list:
                self.assertEqual(call.args[0].suffix, '.mp3')
            for filename in report['files'].values():
                self.assertTrue(Path(filename).is_file())
                self.assertEqual(Path(filename).suffix, '.mp3')
            self.assertEqual(report['validation']['instrumental']['channels'], 2)
            self.assertEqual(report['validation']['instrumental']['sample_rate'], 48000)

    def test_device_failure_retries_cpu_in_new_worker(self):
        original_run = subprocess.run
        devices = []
        def run(command, **kwargs):
            if '--worker' not in command:
                return original_run(command, **kwargs)
            device = command[-1]
            devices.append(device)
            if device == 'mps':
                kwargs['stderr'].write('MPS out of memory')
                kwargs['stderr'].flush()
                return subprocess.CompletedProcess(command, 1)
            source, output = Path(command[-3]), Path(command[-2])
            audio, rate = sf.read(source, always_2d=True)
            for stem in ('instrumental', 'vocals'):
                sf.write(output / f'{stem}.wav', audio*.5, rate, subtype='FLOAT')
            (output / 'metrics.json').write_text('{}')
            return subprocess.CompletedProcess(command, 0)
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / 'input.wav'
            t = np.arange(44100)/44100
            sf.write(source, .1*np.sin(2*np.pi*440*t), 44100)
            with patch.object(separation, 'ensure_model'), \
                    patch.object(separation, 'device_status', return_value={'device': 'mps', 'mps_available': True}), \
                    patch.object(separation.subprocess, 'run', side_effect=run):
                report = separation.process(source, 'detail', directory / 'result', 'auto')
            self.assertEqual(devices, ['mps', 'cpu'])
            self.assertTrue(report['success'])
            self.assertEqual(report['device'], 'cpu')
            self.assertTrue(any('回退 CPU' in notice for notice in report['notices']))
            self.assertEqual(report['validation']['vocals']['channels'], 1)

    def test_preference_required_and_explicit_model_wins(self):
        with self.assertRaises(ValueError):
            select_models()
        self.assertEqual(select_models(goal='clean'), ['clean'])
        self.assertEqual(select_models(model='detail', goal='clean'), ['detail'])
        self.assertEqual(select_models(model='both'), ['detail', 'clean'])
        with self.assertRaises(ValueError):
            select_models(model='piano')

    def test_output_collision_preserves_previous_result(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / 'song'
            a = reserve(base)
            (a / 'instrumental.wav').write_bytes(b'previous')
            b = reserve(base)
            self.assertNotEqual(a, b)
            self.assertEqual((a / 'instrumental.wav').read_bytes(), b'previous')

    def test_playability_only_accepts_silence_and_other_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'stem.wav'
            t = np.arange(44100) / 44100
            sf.write(path, .1*np.sin(2*np.pi*440*t), 44100, subtype='FLOAT')
            self.assertTrue(validate(path)['playable'])
            sf.write(path, np.zeros(44100), 44100, subtype='FLOAT')
            self.assertTrue(validate(path)['playable'])
            sf.write(path, np.zeros((24000, 2)), 48000, subtype='PCM_16')
            self.assertTrue(validate(path)['playable'])
            path.write_bytes(b'broken file')
            with self.assertRaises(ValueError):
                validate(path)

    def test_default_export_preserves_each_source_format_and_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            raw = directory / 'raw.wav'
            t = np.arange(24000)/48000
            audio = np.stack([.1*np.sin(2*np.pi*440*t), .1*np.sin(2*np.pi*330*t)], axis=1)
            sf.write(raw, audio, 48000, subtype='PCM_24')
            for kind in ('wav', 'flac', 'mp3', 'm4a', 'aiff'):
                with self.subTest(format=kind):
                    source = directory / f'source.{kind}'
                    encode(raw, source, output_spec(raw, probe(raw), kind))
                    original = probe(source)
                    spec = output_spec(source, original)
                    target = directory / f'final.{spec["extension"]}'
                    encode(raw, target, spec)
                    result = validate(target)
                    self.assertTrue(result['playable'])
                    self.assertEqual(target.suffix, source.suffix)
                    self.assertEqual(result['sample_rate'], original['sample_rate'])
                    self.assertEqual(result['channels'], original['channels'])
                    self.assertEqual(result['codec'], original['codec'])
                    if kind in ('wav', 'flac', 'aiff'):
                        self.assertEqual(result['bit_depth'], original['bit_depth'])
                    if kind == 'mp3':
                        self.assertEqual(result['bit_rate'], original['bit_rate'])
            alac = directory / 'alac.m4a'
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(raw), '-c:a', 'alac', str(alac)], check=True)
            target = directory / 'final-alac.m4a'
            encode(raw, target, output_spec(alac, probe(alac)))
            self.assertEqual(validate(target)['codec'], 'alac')
            sf.write(raw, audio, 48000, subtype='FLOAT')
            target = directory / 'final-float.wav'
            encode(raw, target, output_spec(raw, probe(raw)))
            self.assertEqual(probe(target)['codec'], 'pcm_f32le')

    def test_local_cache_and_verify_never_download(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            target = cache / 'fixture.ckpt'
            target.write_bytes(b'known-good-test-fixture')
            expected_hash = mm.digest(target)
            model = {'files': {target.name: {'sha256': expected_hash, 'urls': ['https://invalid.example/']}}}
            with patch.object(mm, 'CACHE', cache), patch.object(mm, 'MODELS', {'detail': model}), \
                    patch.object(mm.urllib.request, 'urlopen', side_effect=AssertionError('network forbidden')):
                mm.ensure_model('detail')
                # A valid receipt must skip even the full checksum on subsequent runs.
                with patch.object(mm, 'digest', side_effect=AssertionError('unnecessary rehash')):
                    mm.ensure_model('detail')
                target.write_bytes(b'damaged')
                with self.assertRaisesRegex(RuntimeError, '完整性'):
                    mm.ensure_model('detail')
                target.unlink()
                with self.assertRaisesRegex(RuntimeError, '缺失'):
                    mm.ensure_model('detail', verify=True)

if __name__ == '__main__':
    unittest.main()
