#!/usr/bin/env python3
"""Prepare load-test alternatives; preserve audio bytes, never edit the input."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import wave
from reorganize_samples_and_bolero_templates import embed_mpc_atem_slic, read_mpc_atem_slic


def prepare(src, output, meter=4, beat_unit=4):
    output.mkdir(parents=True, exist_ok=False)
    original=output/'A_ORIGINAL.wav'; clean=output/'B_PCM_ONLY.wav'; changed=output/'C_PULSE_REPAIRED.wav'
    shutil.copyfile(src, original)
    with wave.open(str(original),'rb') as w:
        params=w.getparams(); data=w.readframes(w.getnframes())
    with wave.open(str(clean),'wb') as w:
        w.setparams(params); w.writeframes(data)
    shutil.copyfile(clean, changed)
    a=read_mpc_atem_slic(original)['atem']; v=a['value0']; n=v['Num slices']
    embed_mpc_atem_slic(changed, [(v[f'Slice {i}']['Start'],v[f'Slice {i}']['End']) for i in range(n)],
        num_bars=v['numBars'], beats_per_bar=meter, beat_unit=beat_unit, note_sharp=a['value1']['note'], scale_name=a['value1']['scale'])
    for p in (original,clean,changed):
        with wave.open(str(p),'rb') as w:
            assert w.getparams()==params and w.readframes(w.getnframes())==data
    (output/'PCM_VERIFICATION.json').write_text(json.dumps({'source':src.name,'frames':params.nframes,'sample_rate':params.framerate,'pcm_sha256':hashlib.sha256(data).hexdigest(),'identical_pcm':True},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('output',type=Path);p.add_argument('--meter',type=int,default=4);p.add_argument('--beat-unit',type=int,default=4);a=p.parse_args();prepare(a.source,a.output,a.meter,a.beat_unit)
