import array
import math
from pathlib import Path
import sys
import tempfile
import unittest
import wave
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from index_mpc_library import (classify_sound_type, classify_sample_format, extract_key,
                               measure_energy, render_catalog, CAMELOT_MAP)


class MetadataTests(unittest.TestCase):
    def test_instrument_name_outranks_folder_and_ambiguous_names_stay_unknown(self):
        cases = [('Open_Hat_01.wav','Kicks','HIHAT'),('Shaker01.wav','Hihats','PERCUSSION'),
                 ('BD01.wav','','KICK'),('Snare2.wav','Bass/DrumLoops','SNARE'),
                 ('Drum_Loop_120.wav','','DRUM_LOOP'),('Piano_Loop_90.wav','','MELODIC_LOOP'),
                 ('piano.wav','Kicks','KEYS_SYNTH'),('001.wav','Samples/Snares','SNARE'),
                 ('SwizzBeats0004.wav','05_DRUM_KITS_&_ONE_SHOTS','UNKNOWN'),
                 ('sample_001.wav','Samples/Drums/Kits','UNKNOWN'),('Snare_roll.wav','','ROLL_FILL')]
        for name, folder, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(classify_sound_type(name,folder),expected)
        self.assertEqual(classify_sample_format('Kick_Loop.wav','DRUM_LOOP'),'LOOP')
        self.assertEqual(classify_sample_format('Track_stem.wav','STEM'),'STEM')
        self.assertEqual(classify_sample_format('foo.wav','UNKNOWN'),'UNSPECIFIED')

    def test_camelot_requires_mode_not_a_bank_or_single_note(self):
        for name, expected in [('HS_Kit_A_01_Kick.wav',(None,None)),
                               ('Bass_C1.wav',('C (nota)',None)),
                               ('Key-F#.wav',('F# (nota)',None)),
                               ('Loop_Dmin_120.wav',('Dm','7A')),
                               ('Loop_Cmajor_90.wav',('C','8B')),
                               ('Loop_Abminor.wav',('Abm','1A')),
                               ('Loop_F#maj.wav',('F#','2B')),
                               ('Loop_Ambient.wav',(None,None))]:
            with self.subTest(name=name):
                self.assertEqual(extract_key(name),expected)
        self.assertEqual(set(CAMELOT_MAP.values()),{f'{i}{mode}' for i in range(1,13) for mode in 'AB'})

    def test_energy_uses_samples_not_names_and_handles_silence_and_bad_pcm(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'lofi_180bpm.wav'
            for width in (1,2,3,4):
                for amplitude, expected in [(0,'SILENT'),(.01,'CHILL'),(.12,'GROOVE'),(.8,'BANGER')]:
                    raw=bytearray()
                    for i in range(12000):
                        v=round(amplitude*(2**(width*8-1)-1)*math.sin(2*math.pi*i/50))
                        raw.extend(bytes([v+128]) if width==1 else v.to_bytes(width,'little',signed=True))
                    with wave.open(str(p),'wb') as w:
                        w.setparams((1,width,44100,0,'NONE','PCM'));w.writeframes(raw)
                    self.assertEqual(measure_energy(p),expected,(width,amplitude))
            p.write_bytes(b'broken');self.assertEqual(measure_energy(p),'UNMEASURED')
            self.assertEqual(measure_energy(Path(tmp)/'missing.wav'),'UNMEASURED')

    def test_stats_follow_real_records_even_when_empty(self):
        t=(Path(__file__).resolve().parents[1]/'templates/catalogo.html').read_text()
        html=render_catalog(t,[],{})
        self.assertNotIn('28,911',html)
        self.assertNotIn('__STAT_',html)
