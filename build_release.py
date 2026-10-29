"""Build a source-only BeatOS distribution from an explicit allowlist."""
import argparse
import hashlib
import gzip
import json
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET
from index_mpc_library import render_catalog


FILES = ('serve_mpc.py', 'hardware_kit_builder.py', 'index_mpc_library.py',
         'installer.py', 'install.sh', 'schema.sql', 'LICENSE', 'LICENSE.md',
         'README.md', 'GUIA_INSTALACION.md', 'build_release.py',
         'templates/catalogo.html', 'templates/template_drum.xpm',
         'templates/template_project.xpj', 'tests/test_hardware_kit_builder.py',
         'tests/test_serve_mpc.py', 'tests/test_indexer.py', 'tests/test_metadata.py', 'tests/test_installer.py', 'tests/test_mute_groups.py',
         'tests/test_pad_audio.cjs', 'tests/test_library_ui.cjs', 'tests/test_creator_identity.cjs', '00_ABRIR_BEATOS/ABRIR_BEATOS.command', '00_ABRIR_BEATOS/LEEME.txt', 'tests/test_hub_workflows.py', 'docs/assets/hardware/sources.json')
VERSION = '3.6.5-layout.20261029'


def blank_templates(payload):
    root = ET.fromstring(payload['templates/template_drum.xpm'])
    for element in root.iter():
        if element.tag in {'SampleName', 'SampleFile'}:
            element.text = ''
        elif element.tag == 'MuteGroup' or element.tag.startswith('MuteTarget'):
            element.text = '0'
        elif element.tag == 'Active':
            element.text = 'False'
        elif element.tag == 'ProgramName':
            element.text = 'BeatOS_Template'
    payload['templates/template_drum.xpm'] = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    raw = gzip.decompress(payload['templates/template_project.xpj']).decode('utf-8')
    start = raw.index('{')
    project = json.loads(raw[start:])

    def clean(value):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if key in {'samples', 'events', 'songs'} and isinstance(item, list):
                    result[key] = []
                elif key == 'whichMuteGroup':
                    result[key] = 0
                elif key == 'muteTargets' and isinstance(item, dict):
                    result[key] = {k: 0 for k in item}
                elif key in {'sampleName', 'sampleFile'}:
                    result[key] = ''
                elif key == 'active' and ('sampleName' in value or 'sampleFile' in value):
                    result[key] = False
                else:
                    result[key] = clean(item)
            return result
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, str):
            if value.startswith(('/Users/', '/Volumes/')) or value.lower().endswith(('.wav', '.aif', '.aiff', '.mp3')):
                return ''
            return value.replace('Astro1Deep_Kit_01', 'BeatOS_Template')
        return value

    project = clean(project)
    project['data']['tracks'] = project['data'].get('tracks', [])[:1]
    text = raw[:start] + json.dumps(project, ensure_ascii=False)
    assert not project['data'].get('samples') and '/Users/' not in text and '/Volumes/' not in text
    payload['templates/template_project.xpj'] = gzip.compress(text.encode(), mtime=0)


def build_release(destination):
    source = Path(__file__).resolve().parent
    payload = {name: (source / name).read_bytes() for name in FILES}
    for path in (source / 'docs').rglob('*'):
        if path.is_file() and not path.name.startswith('.') and not path.is_symlink() and path.suffix.lower() in {'.md', '.svg', '.jpg', '.png', '.webp'}:
            payload[path.relative_to(source).as_posix()] = path.read_bytes()
    payload['catalogo_universal.html'] = render_catalog(payload['templates/catalogo.html'].decode(), [], {}).encode()
    payload['VERSION'] = (VERSION + '\n').encode()
    blank_templates(payload)
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(payload.items())}
    payload['MANIFEST.sha256.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.zip.new')
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(payload.items()):
            info = zipfile.ZipInfo(f'BeatOS-{VERSION}/{name}')
            info.external_attr = (0o100755 if name.endswith(('.sh', '.command')) else 0o100644) << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(temporary) as archive:
        assert archive.testzip() is None
        assert all(hashlib.sha256(archive.read(f'BeatOS-{VERSION}/{name}')).hexdigest() == digest
                   for name, digest in manifest.items())
    temporary.replace(destination)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    print(build_release(parser.parse_args().destination))
