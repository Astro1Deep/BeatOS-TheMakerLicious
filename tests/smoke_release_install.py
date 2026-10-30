"""Exercise a released ZIP with the real installer, server and MPC round trip."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
import zipfile


def request(base, endpoint, payload=None, headers=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request_headers = {'Origin': base, **(headers or {})}
    if data is not None:
        request_headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(base + endpoint, data=data, headers=request_headers)
    with urllib.request.urlopen(req, timeout=15) as response:
        return response.status, response.read()


def validate(archive, expected_sha256, require_windows=False):
    if require_windows and platform.system() != 'Windows':
        raise RuntimeError('This proof requires a native Windows Python process')
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != expected_sha256:
        raise RuntimeError('Release archive SHA-256 mismatch')
    with tempfile.TemporaryDirectory(prefix='BeatOS instalación ') as temporary:
        root = Path(temporary).resolve()
        with zipfile.ZipFile(archive) as bundle:
            assert bundle.testzip() is None
            names = bundle.namelist()
            for name in names:
                parts = PurePosixPath(name)
                assert not parts.is_absolute() and '..' not in parts.parts
            prefix = names[0].split('/')[0]
            manifest = json.loads(bundle.read(prefix + '/BeatOS/MANIFEST.sha256.json'))
            for name, expected in manifest.items():
                assert hashlib.sha256(bundle.read(prefix + '/' + name)).hexdigest() == expected
            bundle.extractall(root)
        code = root / prefix / 'BeatOS'
        library = root / 'Biblioteca Productor á'
        samples = library / 'Samples'
        samples.mkdir(parents=True)
        for name, frequency in [('Kick prueba á.wav', 80), ('HiHat prueba.wav', 4000)]:
            with wave.open(str(samples / name), 'wb') as audio:
                audio.setparams((1, 2, 44100, 0, 'NONE', 'PCM'))
                audio.writeframes(b''.join(struct.pack('<h', int(4000 * math.sin(2 * math.pi * frequency * n / 44100))) for n in range(4410)))
        installed = subprocess.run([sys.executable, '-B', str(code / 'installer.py')],
                                   input=f'1\n{library}\nn\n', text=True,
                                   encoding='utf-8', errors='replace', capture_output=True,
                                   cwd=code.parent, timeout=60,
                                   env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
        assert installed.returncode == 0, installed.stdout + installed.stderr
        assert {p.name for p in library.iterdir()} == {'Samples', 'BeatOS', 'catalogo_universal.html', 'catalogo_mpc_sample.html'}
        database = library / 'BeatOS/data/mpc_sample.db'
        connection = sqlite3.connect(database)
        try:
            assert connection.execute('SELECT COUNT(*) FROM samples').fetchone()[0] == 2
        finally:
            connection.close()
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        with (root / 'server.log').open('w', encoding='utf-8') as log:
            server = subprocess.Popen([sys.executable, '-B', '-u', str(code / 'serve_mpc.py'),
                                       str(library), '--port', str(port), '--no-browser'],
                                      stdout=log, stderr=subprocess.STDOUT,
                                      env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
            try:
                deadline = time.monotonic() + 20
                while True:
                    try:
                        _, raw = request(base, '/api/status')
                        status = json.loads(raw)
                        assert Path(status['root_dir']).resolve() == library.resolve(), status
                        assert status['sample_count'] == 2, status
                        break
                    except (OSError, ValueError):
                        if server.poll() is not None or time.monotonic() >= deadline:
                            raise RuntimeError((root / 'server.log').read_text(encoding='utf-8'))
                        time.sleep(.1)
                _, html = request(base, '/')
                assert 'Kick prueba á.wav' in html.decode('utf-8')
                route = '/Samples/' + urllib.parse.quote('Kick prueba á.wav', safe='')
                status_code, audio = request(base, route, headers={'Range': 'bytes=0-43'})
                assert status_code == 206 and len(audio) == 44 and audio.startswith(b'RIFF')
                _, image = request(base, '/BeatOS/docs/assets/branding/creator/label-rocket.png')
                assert image.startswith(b'\x89PNG')
                payload = {'name': 'Validacion_MPC', 'target': 'mpc', 'tempo': 93, 'pads': [
                    {'pad': 1, 'rel_path': 'Samples/Kick prueba á.wav', 'mute_group': 1, 'volume': 1, 'pan': .5, 'tune': 0},
                    {'pad': 2, 'rel_path': 'Samples/HiHat prueba.wav', 'mute_group': 2, 'volume': 1, 'pan': .5, 'tune': 0}]}
                _, raw = request(base, '/api/create_kit', payload)
                exported = json.loads(raw)
                assert exported['success'], exported
                target = exported['targets']['mpc']
                for key in ['project_path', 'program_path_root']:
                    path = Path(target[key])
                    assert path.is_file() and path.is_relative_to(library), target
                relative = Path(target['project_path']).relative_to(library).as_posix()
                _, raw = request(base, '/api/load_project', {'rel_path': relative})
                loaded = json.loads(raw)
                assert loaded['success'], loaded
                pads = loaded['project']['pads']
                assert pads['1']['mute_group'] == 1 and pads['2']['mute_group'] == 2
                assert not any(p.get('missing') for p in pads.values())
                assert loaded['project']['tempo'] == 93
                po33_roundtrip = False
                if (code / 'docs/assets/po33-capture-worklet.js').is_file():
                    import io
                    buffer = io.BytesIO()
                    with wave.open(buffer, 'wb') as wav:
                        wav.setparams((2, 2, 48000, 0, 'NONE', ''))
                        wav.writeframes(struct.pack('<hh', 1234, -6789) * 4800)
                    original = buffer.getvalue()
                    req = urllib.request.Request(base + '/api/po33_backups?name=PO33_prueba.WAV', data=original,
                                                 headers={'Origin': base, 'Content-Type': 'audio/wav'})
                    with urllib.request.urlopen(req, timeout=15) as response:
                        backup = json.load(response)['backup']
                    assert backup['sha256'] == hashlib.sha256(original).hexdigest()
                    assert backup['audio_compatible'] and not backup['payload_verified']
                    _, restored = request(base, '/api/po33_backup_audio?file=' + urllib.parse.quote(backup['path']))
                    assert restored == original
                    _, worklet = request(base, '/docs/assets/po33-capture-worklet.js')
                    assert b"registerProcessor('po33-capture'" in worklet
                    po33_roundtrip = True
                for private in ['/BeatOS/data/mpc_sample.db', '/BeatOS/config/theme_config.json']:
                    try:
                        request(base, private)
                    except urllib.error.HTTPError as error:
                        assert error.code == 403
                    else:
                        raise AssertionError('Private application state was served over HTTP')
            finally:
                server.terminate()
                server.wait(timeout=10)
        assert not list(library.rglob('__pycache__'))
        return {'os': platform.system(), 'version': platform.version(), 'machine': platform.machine(),
                'python': platform.python_version(), 'release_sha256': digest, 'archive_name': archive.name,
                'installer_cli': True, 'unicode_and_spaces': True, 'indexed_samples': 2,
                'http_audio_range': True, 'mpc_export_and_reimport': True,
                'po33_backup_roundtrip': po33_roundtrip,
                'private_files_blocked': True, 'personal_data_used': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--require-windows', action='store_true')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = validate(args.archive, args.sha256, args.require_windows)
    args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('BEATOS_INSTALL_REPORT=' + json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
