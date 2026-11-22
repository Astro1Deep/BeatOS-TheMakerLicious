#!/usr/bin/env python3
"""Read-only source audit; stage conservative ACVS repairs outside the source."""
import argparse
import copy
import gzip
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mpc_compat import normalize_key, restore_mixer_tracks, reconcile_generated_clips


def read_project(path):
    raw = gzip.decompress(path.read_bytes()).decode('utf-8')
    i = raw.index('{')
    return raw[:i], json.loads(raw[i:])


def stage_project(src, dest=None):
    header, payload = read_project(src)
    if header != 'ACVS\n1.3.0.12\nSerialisableProjectData\njson\nLinux\n':
        raise ValueError('Unsupported ACVS header; unchanged')
    before = copy.deepcopy(payload)
    d = payload['data']
    if not isinstance(d.get('tracks'), list) or not d['tracks']:
        raise ValueError('Invalid or empty project tracks')
    if len({x['name'] for x in d['tracks']}) != len(d['tracks']):
        raise ValueError('Duplicate track names; manual review')
    counts = {'before_samples': len(d.get('samples', [])), 'before_tracks': len(d['tracks'])}
    d['key'] = normalize_key(d.get('key'))
    for samples in [d.get('samples', [])] + [t.get('samples', []) for t in d['tracks']]:
        for sm in samples:
            m = sm.get('metadata', {})
            if 'key' in m:
                m['key'] = normalize_key(m['key'])
    restore_mixer_tracks(d)
    names = {t['name'] for t in d['tracks']}
    orphan = set(); missing = set()
    for s in d.get('sequences', []):
        for clips in s['value'].get('trackClipMaps', []):
            keys = {c['key'] for c in clips}
            orphan |= keys - names
            missing |= {t['name'] for t in d['tracks'] if t['program']['type'] not in (8,9)} - keys
    if orphan:
        split_safe = False
        if orphan == {'BeatOS_Template'} and missing and all(n.endswith((' Drums',' Hats & Perc',' Bass 808',' Melodic & FX')) for n in missing):
            _, ref_doc = read_project(Path(__file__).resolve().parents[1]/'templates/template_project.xpj')
            ref = next(c['value'] for m in ref_doc['data']['sequences'][0]['value']['trackClipMaps'] for c in m if c['key']=='BeatOS_Template')
            old = [c['value'] for s in d['sequences'] for m in s['value']['trackClipMaps'] for c in m if c['key']=='BeatOS_Template']
            split_safe = all(not c['eventList']['events'] and c.get('perClipParameterValues') == ref.get('perClipParameterValues') for c in old)
        if len(orphan) != 1 or (len(missing) != 1 and not split_safe):
            raise ValueError(f'Ambiguous clip names: {sorted(orphan)}; missing {sorted(missing)}')
        reconcile_generated_clips(d, next(iter(orphan)), sorted(missing))
    elif payload != before:
        reconcile_generated_clips(d)
    counts.update(after_samples=len(d.get('samples', [])), after_tracks=len(d['tracks']), changed=payload != before)
    if counts['changed'] and dest:
        if src.resolve() == dest.resolve():
            raise ValueError('Source overwrite prohibited')
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            raise FileExistsError(dest)
        dest.write_bytes(gzip.compress((header + json.dumps(payload, indent=0)).encode('utf-8'), mtime=0))
        counts['source_sha256'] = hashlib.sha256(src.read_bytes()).hexdigest()
        counts['staged_sha256'] = hashlib.sha256(dest.read_bytes()).hexdigest()
    return counts


def audit(card, output):
    counts = Counter(); rows = []
    for root in [card/'Expansions', card/'Custom_Kits', card/'MPC-Sample/Projects']:
        if not root.is_dir():
            continue
        for p in sorted(root.rglob('*.xpj')):
            if p.name.startswith('.'):
                continue
            rel = p.relative_to(card); counts['xpj'] += 1
            row = {'path': str(rel)}
            try:
                _, doc = read_project(p); d = doc['data']
                pdata = p.parent / (p.stem + '_[ProjectData]')
                refs = [s.get('path') for s in d.get('samples', []) if s.get('path')]
                unresolved = [ref for ref in refs if not any((base / ref).is_file() for base in (pdata, p.parent))]
                row['unresolved_local_refs'] = unresolved
                counts['unresolved_project_refs'] += len(unresolved)
                result = stage_project(p, None if unresolved else output/'staged'/rel)
                row.update(result)
                counts['repair_candidates'] += bool(result['changed'])
                counts['staged'] += 'staged_sha256' in result
            except Exception as e:
                row['review'] = str(e); counts['project_manual_review'] += 1
            rows.append(row)
        for p in sorted(root.rglob('*.xpm')):
            if p.name.startswith('.'):
                continue
            counts['xpm'] += 1
            try:
                t = ET.parse(p)
                if t.getroot().tag != 'MPCVObject':
                    raise ValueError('Unexpected XPM root')
                counts['xpm_xml_valid'] += 1
            except Exception as e:
                rows.append({'path': str(p.relative_to(card)), 'review': str(e)}); counts['xpm_parse_errors'] += 1
    (output/'audit.json').write_text(json.dumps({'counts': counts, 'files': rows}, indent=2, ensure_ascii=False))
    print(json.dumps(counts, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--card', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    a = parser.parse_args()
    card = a.card.resolve(); output = a.output.resolve()
    if output == card or card in output.parents or output in card.parents:
        parser.error('Output must be separate from card')
    if not card.is_dir() or not (card/'Expansions').is_dir():
        parser.error('Card not mounted or missing Expansions')
    output.mkdir(parents=True, exist_ok=False)
    audit(card, output)


if __name__ == '__main__':
    main()
