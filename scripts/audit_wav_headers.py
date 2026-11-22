#!/usr/bin/env python3
"""Independent RIFF header audit. Does not rewrite media or assume native RIFF sizes are canonical."""
import argparse
from collections import Counter
import json
from pathlib import Path
import struct


def probe(p):
    length = p.stat().st_size
    result = {}
    with p.open('rb') as f:
        h = f.read(12)
        if len(h) != 12 or h[:4] != b'RIFF' or h[8:] != b'WAVE':
            raise ValueError('Non-RIFF/WAVE or truncated header')
        result['riff_size_delta'] = length - 8 - struct.unpack_from('<I', h, 4)[0]
        fmt = None; data = None; atem = None; slic = None; chunks = []
        while f.tell() + 8 <= length:
            k, n = struct.unpack('<4sI', f.read(8)); chunks.append(k.decode('ascii', 'replace'))
            if f.tell() + n > length:
                raise ValueError('Truncated chunk payload')
            if k == b'fmt ':
                fmt = struct.unpack('<HHIIHH', f.read(16)); f.seek(n-16, 1)
            elif k == b'data':
                data = n; f.seek(n, 1)
            elif k == b'atem' and n < 4_000_000:
                atem = json.loads(f.read(n).rstrip(b'\0'))['value0']
            elif k == b'slic' and n < 4_000_000:
                slic = f.read(n)
            else:
                f.seek(n, 1)
            f.seek(n & 1, 1)
    if fmt is None or data is None or not fmt[4] or data % fmt[4]:
        raise ValueError('Missing or inconsistent fmt/data chunk')
    result.update(format=fmt[0], channels=fmt[1], sample_rate=fmt[2], bits=fmt[5], frames=data//fmt[4], chunks=chunks)
    if atem:
        count = atem['Num slices']; result['atem_slices'] = count
        entries = [atem[f'Slice {i}'] for i in range(count)]
        result['pulse_all_zero'] = count > 1 and all(x['PulsePosition'] == 0 for x in entries)
        result['slice_bounds_bad'] = any(not 0 <= x['Start'] <= x['End'] <= result['frames'] for x in entries)
        if slic is not None:
            header = struct.unpack_from('<HHH', slic)
            result['slic_layout_matches'] = header[1] == count and len(slic) == 6 + 14 * count
            if result['slic_layout_matches']:
                result['slic_bounds_match'] = all(struct.unpack_from('<IIIH',slic,6+14*i)[:3] == (x['Start'],x['End'],x['LoopStart']) for i,x in enumerate(entries))
    return result


def main():
    a = argparse.ArgumentParser(description=__doc__); a.add_argument('--card', type=Path, required=True); a.add_argument('--report', type=Path, required=True); args=a.parse_args()
    root=args.card.resolve(); report=args.report.resolve()
    if root in report.parents: a.error('Report cannot be written to source card')
    stats=Counter(); findings=[]; packs={}
    for base in (root/'Expansions',root/'Custom_Kits',root/'MPC-Sample'):
        for p in base.rglob('*'):
            if p.suffix.lower() != '.wav' or p.name.startswith('.') or not p.is_file(): continue
            rel=str(p.relative_to(root)); group='/'.join(p.relative_to(root).parts[:2]); c=packs.setdefault(group, Counter()); stats['wav']+=1; c['wav']+=1
            try:
                r=probe(p); flags=[]
                if r['riff_size_delta']: flags.append('noncanonical_riff_size')
                if r.get('pulse_all_zero'): flags.append('multiple_slices_zero_pulse')
                if r.get('slice_bounds_bad'): flags.append('out_of_bounds_slice')
                if r.get('slic_layout_matches') is False: flags.append('slic_layout_difference')
                if r.get('slic_bounds_match') is False: flags.append('slic_bounds_difference')
                if flags:
                    findings.append({'path':rel,'flags':flags,'data':r})
                    for f in flags: stats[f]+=1; c[f]+=1
            except Exception as e:
                stats['parse_error']+=1; c['parse_error']+=1; findings.append({'path':rel,'error':str(e)})
    report.write_text(json.dumps({'counts':stats,'groups':packs,'findings':findings},ensure_ascii=False,indent=2))
    print(json.dumps(stats,indent=2))


if __name__=='__main__': main()
