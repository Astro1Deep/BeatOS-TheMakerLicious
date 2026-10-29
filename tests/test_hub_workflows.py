import gzip,json,struct,tempfile,unittest,wave,shutil
from pathlib import Path
from unittest.mock import patch
import hardware_kit_builder as kits

class HubWorkflows(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.audio=self.root/'stereo.wav'
        with wave.open(str(self.audio),'wb') as wav:
            wav.setparams((2,2,44100,0,'NONE',''));wav.writeframes(struct.pack('<hh',10000,-2000)*4410)
    def tearDown(self):self.tmp.cleanup()
    def pad(self,**values):return {'source_path':str(self.audio),'sample_name':'stereo',**values}
    def test_ep_preserves_stereo_and_only_used_slots(self):
        folder,archive=kits.export_ep133_ko2_kit('Stereo',{3:self.pad(pan=.2,tune=4,mute_group=0)},self.root/'ep')
        meta=json.loads((Path(folder)/'meta.json').read_text());self.assertEqual(meta['sample_count'],1)
        item=meta['sounds'][0];self.assertEqual((item['slot'],item['pan'],item['tune'],item['choke_group']),(3,.2,4,0))
        with wave.open(str(Path(folder)/item['filename'])) as wav:
            self.assertEqual(wav.getnchannels(),2);self.assertEqual(wav.readframes(1),struct.pack('<hh',10000,-2000))
    def test_po_budget_gaps_fade_and_pad_order(self):
        long=self.root/'long.wav'
        with wave.open(str(long),'wb') as wav:
            wav.setparams((1,2,44100,0,'NONE',''));wav.writeframes(struct.pack('<h',10000)*88200)
        path,duration,slices=kits.export_po33_drum_reel('Short',{2:{'source_path':str(long)},16:{'source_path':str(long)}},self.root/'po',gap_ms=200,max_total_sec=1)
        self.assertLessEqual(duration,1);self.assertEqual([s['source_pad'] for s in slices],[2,16]);self.assertEqual([s['slice_number'] for s in slices],[1,2])
        with wave.open(path) as wav:
            pcm=struct.unpack('<'+'h'*wav.getnframes(),wav.readframes(wav.getnframes()))
        self.assertEqual(pcm[slices[0]['end_frame']-1],0)
        self.assertTrue(all(x==0 for x in pcm[slices[0]['end_frame']:slices[1]['start_frame']]))
        with self.assertRaises(ValueError):kits.export_po33_drum_reel('Bad',{i:self.pad() for i in range(1,17)},self.root/'bad',gap_ms=500,max_total_sec=1)
    def test_audio_header_is_never_payload_verification(self):
        candidate=self.root/'candidate.wav'
        with wave.open(str(candidate),'wb') as wav:
            wav.setparams((2,2,100,0,'NONE',''));wav.writeframes(struct.pack('<hh',1000,1000)*2000)
        info=kits.inspect_po33_backup(candidate);self.assertTrue(info['audio_compatible']);self.assertFalse(info['valid']);self.assertFalse(info['payload_verified'])
    def test_resolver_prefers_nested_path_and_rejects_ambiguity(self):
        for directory in ['a','b']:
            (self.root/directory).mkdir();shutil.copy2(self.audio,self.root/directory/'sound.wav')
        found,rel=kits._resolve_sample_file('b/sound.wav',[self.root],self.root)
        self.assertEqual(rel,'b/sound.wav')
        self.assertEqual(kits._resolve_sample_file('sound.wav',[self.root],self.root),(None,''))
    def test_project_tracks_and_bank_h_are_available(self):
        def instrument(group):return {'whichMuteGroup':group,'layersv':[{'sampleFile':'stereo.wav','active':True}]}
        tracks=[{'name':'Uno','program':{'drum':{'instruments':[instrument(0)]}}},{'name':'Dos','program':{'drum':{'instruments':[{}]*127+[instrument(7)]}}}]
        project=self.root/'banks.xpj';project.write_bytes(gzip.compress(('ACVS\n'+json.dumps({'data':{'tracks':tracks}})).encode()))
        result=kits.parse_xpj_project(project,self.root,track_index=1)
        self.assertEqual(result['selected_track'],1);self.assertEqual(list(result['pads']),[128]);self.assertFalse(result['pads'][128]['missing']);self.assertEqual(result['pads'][128]['mute_group'],7)
        with self.assertRaises(ValueError):kits.parse_xpj_project(project,self.root,99)
    def test_failed_export_rolls_back_and_rejects_missing_unknown_or_nan(self):
        for pads,target in [([{'pad':1,'rel_path':'absent.wav'}],'mpc'),([{'pad':1,'rel_path':'stereo.wav','volume':float('nan')}],'mpc'),([{'pad':1,'rel_path':'stereo.wav'}],'bogus')]:
            with self.assertRaises(ValueError):kits.create_kit('Fail',pads,target,source_root=self.root)
            self.assertFalse((self.root/'Custom_Kits/Fail').exists())
        with patch.object(kits,'export_ep133_ko2_kit',side_effect=ValueError('decode error')):
            with self.assertRaises(ValueError):kits.create_kit('Fail',[{'pad':1,'rel_path':'stereo.wav'}],'ep133',source_root=self.root)
        self.assertFalse((self.root/'Custom_Kits/Fail').exists())
    def test_pcm_conversion_requires_decoder_instead_of_renaming_bad_audio(self):
        bad=self.root/'bad.mp3';bad.write_bytes(b'not audio')
        with patch.object(kits.shutil,'which',return_value=None):
            with self.assertRaises(ValueError):kits.export_ep133_ko2_kit('Bad',{1:{'source_path':str(bad)}},self.root/'bad_ep')
    def test_same_filename_different_folders_stays_distinct_in_mpc(self):
        other=self.root/'other';other.mkdir();second=other/self.audio.name
        with wave.open(str(second),'wb') as wav:
            wav.setparams((1,2,44100,0,'NONE',''));wav.writeframes(struct.pack('<h',1234)*4410)
        result=kits.create_kit('Two',[{'pad':1,'rel_path':'stereo.wav'},{'pad':2,'rel_path':'other/stereo.wav'}],'mpc',source_root=self.root)
        program=kits.parse_xpm_program(result['targets']['mpc']['program_path_root'],self.root)
        project=kits.parse_xpj_project(result['targets']['mpc']['project_path'],self.root)
        for imported in (program,project):
            paths=[Path(imported['pads'][i]['full_path']) for i in (1,2)]
            self.assertNotEqual(paths[0],paths[1]);self.assertNotEqual(paths[0].read_bytes(),paths[1].read_bytes())
    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg no instalado')
    def test_truncated_wav_header_is_decoded_to_consistent_pcm(self):
        broken=self.root/'truncated.wav';raw=bytearray(self.audio.read_bytes());raw[40:44]=struct.pack('<I',len(raw)*2);broken.write_bytes(raw)
        fixed=self.root/'fixed.wav';kits._convert_audio(broken,fixed,mono=False)
        with wave.open(str(fixed)) as wav:
            self.assertEqual(len(wav.readframes(wav.getnframes())),wav.getnframes()*wav.getnchannels()*2)
            self.assertGreater(wav.getnframes(),0)
    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg no instalado')
    def test_roland_exports_real_target_rates(self):
        for exporter,rate,filename in [(kits.export_sp404mk2_kit,48000,'PAD_01_stereo.wav'),(kits.export_sp404a_kit,44100,'A01.wav')]:
            folder=exporter('Rate',{1:self.pad()},self.root/str(rate))
            with wave.open(str(Path(folder)/filename)) as wav:
                self.assertEqual(wav.getframerate(),rate);self.assertEqual(wav.getsampwidth(),2);self.assertEqual(wav.getnchannels(),2)
    def test_ep_zip_excludes_appledouble_sidecars(self):
        directory=self.root/'ep_sidecar/Kit/sounds';directory.mkdir(parents=True);(directory/'._fake.wav').write_bytes(b'AppleDouble metadata')
        _,archive=kits.export_ep133_ko2_kit('Kit',{1:self.pad()},self.root/'ep_sidecar')
        with __import__('zipfile').ZipFile(archive) as z:
            self.assertFalse(any(Path(n).name.startswith('.') for n in z.namelist()))

    def test_sample_owner_directory_precedes_library_root(self):
        directory=self.root/'program';directory.mkdir();local=directory/'stereo.wav';shutil.copyfile(self.audio,local)
        found,relative=kits._resolve_sample_file('stereo.wav',[directory],self.root)
        self.assertEqual(found,local.resolve());self.assertEqual(relative,'program/stereo.wav')
