import gzip
import json
from pathlib import Path
import tempfile
import unittest
from hardware_kit_builder import default_mute_group, pad_mute_group, detect_sound_type, parse_xpj_project, export_mpc_program, export_mpc_project

class MuteGroups(unittest.TestCase):
    def test_defaults_and_overrides(self):
        for kind, group in [('KICK',1),('SNARE',3),('HIHAT',2),('BASS_808',0),('CYMBAL',0),('CLAP',0),('FX',0)]:
            self.assertEqual(default_mute_group(kind), group)
            self.assertEqual(pad_mute_group({'sound_type':kind}), group)
            self.assertEqual(pad_mute_group({'sound_type':kind, 'mute_group':0}), 0)
            self.assertEqual(pad_mute_group({'soundType':kind, 'muteGroup':9}), 9)
        self.assertEqual(detect_sound_type('Crash_01.wav'), 'CYMBAL')
        self.assertEqual(detect_sound_type('ClosedHH_01.wav'), 'HIHAT')
        for group in [-1,33]:
            with self.assertRaises(ValueError): pad_mute_group({'mute_group':group})

    def test_xpj_keeps_pad_positions_duplicates_and_zero(self):
        def inst(name, group):
            return {'whichMuteGroup':group, 'coarseTune':2, 'mixable':{'pan':0.3,'volume':0.4}, 'layersv':[{'active':True,'sampleName':name}]}
        payload={'data':{'masterTempo':91,'key':'D Minor','samples':[{'name':'Hat','path':'Hat.wav'},{'name':'Kick','path':'Kick.wav'}], 'tracks':[{'program':{'drum':{'instruments':[inst('Kick',0),{},inst('Hat',2),inst('Kick',1)]}}}]}}
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'test.xpj';path.write_bytes(gzip.compress(('ACVS\n'+json.dumps(payload)).encode()))
            result=parse_xpj_project(path, d)
        self.assertEqual(list(result['pads']), [1,3,4])
        self.assertEqual(result['pads'][1]['mute_group'], 0)
        self.assertEqual(result['pads'][3]['mute_group'], 2)
        self.assertEqual(result['pads'][1]['sample_file'], 'Kick.wav')
        self.assertEqual(result['tempo'],91)

    def test_native_exports_defaults_and_explicit_free(self):
        import xml.etree.ElementTree as ET
        pads={1:{'sample_name':'Kick'},2:{'sample_name':'Hat'},3:{'sample_name':'Snare'},
              4:{'sample_name':'Bass808'},5:{'sample_name':'Kick_free','mute_group':0},
              6:{'sample_name':'FX','mute_group':9}}
        with tempfile.TemporaryDirectory() as d:
            xpm=ET.parse(export_mpc_program('Groups',pads,Path(d)/'program',copy_samples=False))
            instruments=xpm.getroot().findall('.//Instruments/Instrument')
            self.assertEqual([int(i.findtext('MuteGroup')) for i in instruments[:6]], [1,2,3,0,0,9])
            self.assertTrue(all(int(n.text or '0')==0 for i in instruments for n in i if n.tag.startswith('MuteTarget')))
            path=export_mpc_project('Groups',pads,Path(d)/'project')
            text=gzip.decompress(Path(path).read_bytes()).decode()
            data=json.loads(text[text.index('{'):])['data']
            instruments=data['tracks'][0]['program']['drum']['instruments']
            self.assertEqual([i['whichMuteGroup'] for i in instruments[:6]], [1,2,3,0,0,9])
            self.assertTrue(all(not any(i.get('muteTargets',{}).values()) for i in instruments))

    def test_offline_create_command_actually_generates_kit(self):
        import base64, subprocess, sys
        import xml.etree.ElementTree as ET
        with tempfile.TemporaryDirectory() as d:
            import wave
            with wave.open(str(Path(d)/'Kick.wav'),'wb') as w:
                w.setparams((1,2,44100,0,'NONE','')); w.writeframes(b'\0\0'*441)
            pads=[{'pad':1,'sound_type':'KICK','sample_name':'Kick','rel_path':'Kick.wav','mute_group':0}]
            encoded=base64.b64encode(json.dumps(pads).encode()).decode()
            result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'hardware_kit_builder.py'),'create','--name','Offline','--target','mpc','--b64',encoded,'--root',d],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            info=json.loads(result.stdout);path=Path(info['targets']['mpc']['program_path_root']);self.assertTrue(path.is_file())
            self.assertEqual(ET.parse(path).findtext('.//Instrument/MuteGroup'),'0')

    def test_create_never_overwrites_existing_kit(self):
        from hardware_kit_builder import create_kit
        with tempfile.TemporaryDirectory() as d:
            existing=Path(d)/'Custom_Kits'/'Keep';existing.mkdir(parents=True);original=existing/'user.txt';original.write_text('original')
            with self.assertRaises(FileExistsError):create_kit('Keep',[],target='mpc',source_root=d)
            self.assertEqual(original.read_text(),'original')
