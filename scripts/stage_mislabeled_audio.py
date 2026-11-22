#!/usr/bin/env python3
"""Convert mislabeled AIFF to a genuine WAV container without resampling or quantizing."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import soundfile as sf


def convert(src,dst):
    if src.resolve()==dst.resolve() or dst.exists():raise ValueError('Refusing overwrite')
    info=sf.info(src)
    if info.format!='AIFF' or info.subtype not in ('PCM_16','FLOAT'):
        raise ValueError(f'Unsupported source format {info.format}/{info.subtype}')
    dtype='int16' if info.subtype=='PCM_16' else 'float32'
    a,sr=sf.read(src,dtype=dtype,always_2d=True)
    dst.parent.mkdir(parents=True,exist_ok=True)
    sf.write(dst,a,sr,format='WAV',subtype=info.subtype)
    b,sr2=sf.read(dst,dtype=dtype,always_2d=True)
    if sr!=sr2 or a.shape!=b.shape or a.tobytes()!=b.tobytes():
        dst.unlink();raise ValueError('Sample equivalence verification failed')
    return {'sample_rate':sr,'channels':info.channels,'frames':info.frames,'subtype':info.subtype,
            'audio_sha256':hashlib.sha256(a.tobytes()).hexdigest(),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),
            'staged_sha256':hashlib.sha256(dst.read_bytes()).hexdigest(),'hardware_pcm16':info.subtype=='PCM_16' and sr==44100}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--card',type=Path,required=True);p.add_argument('--audit',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    root=a.card.resolve();out=a.output.resolve();
    if out==root or root in out.parents or out in root.parents:p.error('Output must be separate from card')
    out.mkdir(parents=True,exist_ok=False);results=[]
    for r in json.loads(a.audit.read_text())['findings']:
        if not r.get('error','').startswith('Non-RIFF'):continue
        rel=Path(r['path']);src=root/rel
        with src.open('rb') as f: magic=f.read(12)
        if magic[:4]!=b'FORM' or magic[8:12] not in (b'AIFF',b'AIFC'):continue
        results.append({'path':str(rel),**convert(src,out/'staged'/rel)})
    (out/'conversion.json').write_text(json.dumps(results,indent=2,ensure_ascii=False));print('Converted and verified:',len(results))


if __name__=='__main__':main()
