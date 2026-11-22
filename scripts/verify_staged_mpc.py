#!/usr/bin/env python3
"""Compare staged projects against source references, events, pads and SHA-256."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from audit_mpc_compat import read_project


def signature(d):
    events=Counter()
    for s in d.get('sequences', []):
        for m in s['value'].get('trackClipMaps', []):
            for c in m:
                for e in c['value'].get('eventList',{}).get('events',[]):
                    events[(s['key'],json.dumps(e,sort_keys=True))]+=1
    pads={t['name']: t.get('program',{}).get('drum') for t in d['tracks'] if t['program']['type'] not in (8,9)}
    refs=Counter((s.get('name'),s.get('path')) for s in d.get('samples',[]))
    return events,pads,refs


def verify(card, audit_dir):
    report=json.loads((audit_dir/'audit-final.json').read_text()); num=0; issues=[]
    for row in report['files']:
        if 'staged_sha256' not in row:continue
        s=card/row['path']; t=audit_dir/'staged'/row['path']
        try:
            assert hashlib.sha256(s.read_bytes()).hexdigest()==row['source_sha256'],'source changed'
            assert hashlib.sha256(t.read_bytes()).hexdigest()==row['staged_sha256'],'staged changed'
            sd=read_project(s)[1]['data']; td=read_project(t)[1]['data']
            assert signature(sd)==signature(td),'MIDI events, pad assignments or sample refs changed'
            assert 9 in {x['program']['type'] for x in td['tracks']},'missing output'
            assert 8 in {x['program']['type'] for x in td['tracks']},'missing submix'
            names={x['name'] for x in td['tracks']}
            for entry in td['sequences']:
                for clips in entry['value']['trackClipMaps']:
                    assert {x['key'] for x in clips}==names,'clip map mismatch'
            num+=1
        except Exception as e:issues.append({'path':row['path'],'issue':str(e)})
    result={'verified':num,'issues':issues}; (audit_dir/'verification.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)); print(json.dumps(result,indent=2));return not issues


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--card',type=Path,required=True);p.add_argument('--audit',type=Path,required=True);a=p.parse_args();raise SystemExit(0 if verify(a.card,a.audit) else 1)
