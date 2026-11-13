import gzip
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tempfile
import unittest
from hardware_kit_builder import default_mute_group, pad_mute_group, detect_sound_type, parse_xpj_project, export_mpc_program, export_mpc_project

class MuteGroups(unittest.TestCase):
    def test_defaults_and_overrides(self):
        for kind, group in [('KICK',1),('SNARE',1),('TOM',1),('HIHAT',2),('BASS_808',3),('CYMBAL',0),('CLAP',0),('FX',0)]:
            self.assertEqual(default_mute_group(kind), group)
            self.assertEqual(pad_mute_group({'sound_type':kind}), group)
            self.assertEqual(pad_mute_group({'sound_type':kind, 'mute_group':0}), 0)
            self.assertEqual(pad_mute_group({'soundType':kind, 'muteGroup':9}), 9)
        self.assertEqual(detect_sound_type('Crash_01.wav'), 'CYMBAL')
        self.assertEqual(detect_sound_type('ClosedHH_01.wav'), 'HIHAT')
        self.assertEqual(detect_sound_type('Floor_Tom_01.wav'), 'TOM')
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
            self.assertEqual([int(i.findtext('MuteGroup')) for i in instruments[:6]], [1,2,1,3,0,9])
            self.assertTrue(all(int(n.text or '0')==0 for i in instruments for n in i if n.tag.startswith('MuteTarget')))
            path=export_mpc_project('Groups',pads,Path(d)/'project')
            text=gzip.decompress(Path(path).read_bytes()).decode()
            data=json.loads(text[text.index('{'):])['data']
            instruments=data['tracks'][0]['program']['drum']['instruments']
            self.assertEqual([i['whichMuteGroup'] for i in instruments[:6]], [1,2,1,3,0,9])
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

    def test_mute_profiles_and_underground_styles(self):
        from hardware_kit_builder import mute_group_for_profile, detect_musical_style
        # Punch & Clean Master profile (default): Kick, Snare & Tom = 1, Hats = 2, 808 = 3, Clap = 0
        self.assertEqual(mute_group_for_profile('KICK', 'Kick_Sub.wav', 'punch_clean'), 1)
        self.assertEqual(mute_group_for_profile('PERCUSSION', 'Floor_Tom_01.wav', 'punch_clean'), 1)
        self.assertEqual(mute_group_for_profile('TOM', 'Rack_Tom_02.wav', 'punch_clean'), 1)
        self.assertEqual(mute_group_for_profile('SNARE', 'Snare_Main.wav', 'punch_clean'), 1)
        self.assertEqual(mute_group_for_profile('HIHAT', 'Open_Hat_909.wav', 'punch_clean'), 2)
        self.assertEqual(mute_group_for_profile('BASS_808', '808_Sub.wav', 'punch_clean'), 3)
        self.assertEqual(mute_group_for_profile('CLAP', 'Clap_Wide.wav', 'punch_clean'), 0)
        # Real drum kit logic: Kick & Tom = 1, Closed & Open Hats = 2, Snare = 3, Clap = 0
        self.assertEqual(mute_group_for_profile('KICK', 'Kick_Sub.wav', 'real_drums'), 1)
        self.assertEqual(mute_group_for_profile('PERCUSSION', 'Floor_Tom_01.wav', 'real_drums'), 1)
        self.assertEqual(mute_group_for_profile('HIHAT', 'Open_Hat_909.wav', 'real_drums'), 2)
        self.assertEqual(mute_group_for_profile('HIHAT', 'Closed_Hat_909.wav', 'real_drums'), 2)
        self.assertEqual(mute_group_for_profile('SNARE', 'Snare_Main.wav', 'real_drums'), 3)
        self.assertEqual(mute_group_for_profile('CLAP', 'Clap_Wide.wav', 'real_drums'), 0)
        # Club clean: 808 in Group 4, Toms in Group 5
        self.assertEqual(mute_group_for_profile('BASS_808', '808_Glide.wav', 'club_clean'), 4)
        self.assertEqual(mute_group_for_profile('PERCUSSION', 'Rack_Tom.wav', 'club_clean'), 5)
        # Jazz/Funk: Only Hi-Hats in Group 2
        self.assertEqual(mute_group_for_profile('KICK', 'Jazz_Kick.wav', 'jazz_funk'), 0)
        self.assertEqual(mute_group_for_profile('HIHAT', 'Jazz_OpenHat.wav', 'jazz_funk'), 2)
        # Underground style detection
        st_funk = detect_musical_style('Baile_Funk_Favela_Tamborzao', ['Atabaque_01.wav', 'Pontinho_02.wav'])
        self.assertEqual(st_funk['id'], 'baile_funk')
        self.assertEqual(st_funk['bpm'], 130.0)
        st_ukg = detect_musical_style('UK_Garage_2Step_Kit', ['Skippy_Hat.wav', 'Shuffle_Snare.wav'])
        self.assertEqual(st_ukg['id'], 'uk_garage')
        self.assertEqual(st_ukg['bpm'], 132.0)

    def test_legacy_mpc1000_and_mpc2000xl_binary_pgm_exports(self):
        import wave
        from hardware_kit_builder import export_mpc1000_pgm_kit, export_mpc2000xl_pgm_kit
        with tempfile.TemporaryDirectory() as d:
            wav_kick = Path(d) / 'Kick_Heavy_Long_Name.wav'
            wav_hat = Path(d) / 'Open_Hat_Long_Name.wav'
            for wf in (wav_kick, wav_hat):
                with wave.open(str(wf), 'wb') as w:
                    w.setparams((1, 2, 44100, 0, 'NONE', ''))
                    w.writeframes(b'\x10\x00' * 441)
            pads = {
                1: {'sample_name': 'Kick_Heavy_Long_Name', 'sound_type': 'KICK', 'abs_path': str(wav_kick), 'mute_group': 1},
                2: {'sample_name': 'Open_Hat_Long_Name', 'sound_type': 'HIHAT', 'abs_path': str(wav_hat), 'mute_group': 2},
            }
            pgm1000_path = export_mpc1000_pgm_kit('TestLegacyKit', pads, Path(d) / 'out1000')
            pgm1000 = Path(pgm1000_path).read_bytes()
            self.assertEqual(len(pgm1000), 10756)
            self.assertEqual(pgm1000[4:20], b'MPC1000 PGM 1.00')

            pgm2000_path = export_mpc2000xl_pgm_kit('TestLegacyKit', pads, Path(d) / 'out2000')
            pgm2000 = Path(pgm2000_path).read_bytes()
            self.assertEqual(len(pgm2000), 2291 + 17 * 2)
            self.assertEqual(pgm2000[0:2], b'\x07\x04')
            for wav_file in Path(pgm2000_path).parent.glob('*.WAV'):
                self.assertLessEqual(len(wav_file.stem), 8)

    def test_cerebro_pitch_phase_and_autochop(self):
        import math, struct, wave
        from hardware_kit_builder import detect_sample_pitch_and_key, detect_transient_phase_conflict, autochop_sample_to_16_pads
        sr = 44100
        with tempfile.TemporaryDirectory() as d:
            # 1. Synthetic 55 Hz (A1) 808 wave and inverted phase copy
            frames_a = [int(24000 * math.sin(2.0 * math.pi * 55.0 * i / sr)) for i in range(int(sr * 0.5))]
            frames_inv = [-x for x in frames_a]
            wav_pos = Path(d) / 'Bass_808_A.wav'
            wav_neg = Path(d) / 'Bass_808_Inv.wav'
            for wf_path, data_arr in ((wav_pos, frames_a), (wav_neg, frames_inv)):
                with wave.open(str(wf_path), 'wb') as w:
                    w.setparams((1, 2, sr, 0, 'NONE', ''))
                    w.writeframes(struct.pack(f'<{len(data_arr)}h', *data_arr))

            pinfo = detect_sample_pitch_and_key(wav_pos)
            self.assertEqual(pinfo['pitch_class'], 9)  # A = 9
            self.assertAlmostEqual(pinfo['f0_hz'], 55.0, delta=1.5)

            ph = detect_transient_phase_conflict(wav_pos, wav_neg)
            self.assertTrue(ph['phase_conflict'])
            self.assertLess(ph['correlation'], -0.9)

            # 2. Synthetic 1.6s breakbeat with 8 distinct transient hits
            loop_frames = []
            for hit in range(8):
                for i in range(int(sr * 0.2)):
                    env = math.exp(-i / (sr * 0.04))
                    val = int(26000 * env * math.sin(2.0 * math.pi * 110.0 * i / sr))
                    loop_frames.append(val)
            loop_wav = Path(d) / 'Breakbeat_Loop.wav'
            with wave.open(str(loop_wav), 'wb') as w:
                w.setparams((1, 2, sr, 0, 'NONE', ''))
                w.writeframes(struct.pack(f'<{len(loop_frames)}h', *loop_frames))

            chop_res = autochop_sample_to_16_pads(loop_wav, d, max_slices=8, kit_name='BreakTest')
            self.assertTrue(chop_res['success'])
            self.assertEqual(chop_res['slices_count'], 8)
            self.assertTrue(all(p['mute_group'] == 6 for p in chop_res['pads']))

    def test_multi_bank_exports_across_all_hardware_targets(self):
        import wave
        from hardware_kit_builder import create_kit
        with tempfile.TemporaryDirectory() as d:
            wav_a = Path(d) / 'Kick_BankA.wav'
            wav_b = Path(d) / 'Snare_BankB.wav'
            wav_d = Path(d) / 'Hat_BankD.wav'
            for wf in (wav_a, wav_b, wav_d):
                with wave.open(str(wf), 'wb') as w:
                    w.setparams((1, 2, 44100, 0, 'NONE', ''))
                    w.writeframes(b'\x18\x00' * 882)
            # Pad 1 (Bank A), Pad 17 (Bank B, Pad 1), Pad 50 (Bank D, Pad 2)
            pads = [
                {'pad': 1, 'rel_path': 'Kick_BankA.wav', 'sound_type': 'KICK', 'mute_group': 1},
                {'pad': 17, 'rel_path': 'Snare_BankB.wav', 'sound_type': 'SNARE', 'mute_group': 3},
                {'pad': 50, 'rel_path': 'Hat_BankD.wav', 'sound_type': 'HIHAT', 'mute_group': 2},
            ]
            res = create_kit('MultiBankTest', pads, target='universal', source_root=d)
            self.assertTrue(res['success'])
            self.assertEqual(res['samples_count'], 3)
            # Check SP-404MKII Bank B file exists
            sp404_dir = Path(res['targets']['sp404mk2']['import_folder'])
            self.assertTrue(any(f.name.startswith('BANK_B_PAD_01_') for f in sp404_dir.glob('*.wav')))
            # Check NI Maschine Group B & Group D folders exist
            maschine_dir = Path(res['targets']['maschine']['bundle_path'])
            self.assertTrue((maschine_dir / 'Samples' / 'Group_B').is_dir())
            self.assertTrue((maschine_dir / 'Samples' / 'Group_D').is_dir())
            # EP-133 has 48 destinations; unsupported universal source IDs are reported.
            ep_sounds = Path(res['targets']['ep133']['folder']) / 'Sounds'
            self.assertTrue(any(f.name.startswith('017_PAD17_') for f in ep_sounds.glob('*.wav')))
            self.assertFalse(any(f.name.startswith('050_PAD50_') for f in ep_sounds.glob('*.wav')))
            self.assertIn({'target': 'ep133', 'omitted_pads': [50]}, res['warnings'])

    def test_default_pad_volume_option_a(self):
        from hardware_kit_builder import default_pad_volume
        self.assertAlmostEqual(default_pad_volume("KICK"), 0.562341, places=5)
        self.assertAlmostEqual(default_pad_volume("SNARE"), 0.562341, places=5)
        self.assertAlmostEqual(default_pad_volume("TOM"), 0.501187, places=5)
        self.assertAlmostEqual(default_pad_volume("BASS_808"), 0.501187, places=5)
        self.assertAlmostEqual(default_pad_volume("HIHAT"), 0.421697, places=5)
        self.assertAlmostEqual(default_pad_volume("FX"), 0.398107, places=5)

    def test_calibrate_xpm_and_xpj(self):
        from hardware_kit_builder import calibrate_xpm, calibrate_xpj, export_mpc_program, export_mpc_project
        import xml.etree.ElementTree as ET
        with tempfile.TemporaryDirectory() as d:
            pads = {
                1: {"sample_name": "Kick_Hard.wav", "volume": 0.8},
                2: {"sample_name": "Snare_Trap.wav", "volume": 0.9},
                3: {"sample_name": "Open_Hat.wav", "volume": 0.7},
                4: {"sample_name": "808_Sub.wav", "volume": 1.0},
            }
            prog_path = Path(export_mpc_program("TestCalib", pads, Path(d) / "prog", copy_samples=False))
            proj_path = Path(export_mpc_project("TestCalib", pads, Path(d) / "proj"))

            mod_xpm = calibrate_xpm(prog_path, backup=True)
            self.assertGreater(mod_xpm, 0)
            self.assertTrue(prog_path.with_suffix(".xpm.bak-calib").exists())

            root = ET.parse(prog_path).getroot()
            insts = root.findall(".//Instruments/Instrument")
            # Pad 1 (Kick): -5 dB (0.562341), MuteGroup 1
            self.assertEqual(insts[0].findtext("Volume"), "0.562341")
            self.assertEqual(insts[0].findtext("MuteGroup"), "1")
            # Pad 2 (Snare): -5 dB (0.562341), MuteGroup 1
            self.assertEqual(insts[1].findtext("Volume"), "0.562341")
            self.assertEqual(insts[1].findtext("MuteGroup"), "1")
            # Pad 3 (Hat): -7.5 dB (0.421697), MuteGroup 2
            self.assertEqual(insts[2].findtext("Volume"), "0.421697")
            self.assertEqual(insts[2].findtext("MuteGroup"), "2")
            # Pad 4 (808): -6.0 dB (0.501187), MuteGroup 3
            self.assertEqual(insts[3].findtext("Volume"), "0.501187")
            self.assertEqual(insts[3].findtext("MuteGroup"), "3")

            mod_xpj = calibrate_xpj(Path(proj_path), backup=True)
            self.assertGreater(mod_xpj, 0)
            self.assertTrue(Path(proj_path).with_suffix(".xpj.bak-calib").exists())



