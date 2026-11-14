import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import wave
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from index_mpc_library import render_catalog


class IndexerTests(unittest.TestCase):
    def test_checked_in_blank_catalog_uses_latest_bilingual_template(self):
        root = Path(__file__).resolve().parents[1]
        template = (root / 'templates/catalogo.html').read_text(encoding='utf-8')
        preview_path = root / 'BeatOS/data/catalogo.html'
        if not preview_path.is_file():
            self.skipTest('No checked-in blank catalog exists in this source/install layout')
        preview = preview_path.read_text(encoding='utf-8')
        self.assertEqual(preview, render_catalog(template, [], {}),
                         'Checked-in preview must match current ES/EN engine')

    def test_zip_installer_contains_the_same_bilingual_catalog_that_the_server_uses(self):
        import zipfile
        import build_release
        from beatos_paths import CATALOG_REL
        with tempfile.TemporaryDirectory(prefix='BeatOS archive i18n ') as tmp:
            archive = Path(tmp) / 'BeatOS.zip'
            build_release.build_release(archive)
            prefix = f'BeatOS-{build_release.VERSION}/'
            with zipfile.ZipFile(archive) as bundle:
                source = bundle.read(prefix + 'BeatOS/templates/catalogo.html').decode('utf-8')
                installed = bundle.read(prefix + CATALOG_REL).decode('utf-8')
            self.assertEqual(installed, render_catalog(source, [], {}),
                             'Shipped executable catalog must be generated from the bilingual source')
            self.assertIn('"🎛️ Editar Pads en Rack":"🎛️ Edit pads in rack"', installed)
            self.assertIn('"Reproductor y símbolos de Astro1Deep":"Player and Astro1Deep symbols"', installed)

    def test_user_supplied_project_and_expansion_titles_are_not_translated(self):
        root = Path(__file__).resolve().parents[1]
        template = (root / 'templates/catalogo.html').read_text(encoding='utf-8')
        result = render_catalog(template, [], {
            'projects': [{'name': 'Nombre', 'rel_path': 'Projects/demo.xpj'}],
            'expansions': [{'title': 'Archivo', 'path': 'Expansions/Archivo', 'mfg': 'Nombre'}]
        })
        self.assertIn('<h3 translate="no">Nombre</h3>', result)
        self.assertIn('<h3 translate="no">Archivo</h3>', result)
        self.assertIn('class="library-manufacturer" translate="no">Nombre</p>', result)

    def test_catalog_counts_and_cards_use_current_metadata(self):
        template = (Path(__file__).resolve().parents[1] / 'templates/catalogo.html').read_text()
        rendered = render_catalog(template, [], {'projects': [{'name': '<private & project>', 'rel_path':'Projects/session.xpj'}, {'name':'Kit', 'rel_path':'Samples/kit.xpj'}],
                                                  'expansions': [{'title': '<new expansion>'}]})
        self.assertIn('&lt;private &amp; project&gt;', rendered)
        self.assertIn('&lt;new expansion&gt;', rendered)
        self.assertIn('data-kind="sessions"', rendered)
        self.assertIn('data-kind="kits"', rendered)
        self.assertIn('viewExpansionSamples(this.dataset.path',rendered)
        self.assertNotIn('34,165', rendered)
        self.assertNotIn('__SAMPLE_COUNT__', rendered)
        self.assertNotIn('100% HEALTHY', rendered)

    def test_expansions_link_to_their_own_projects_including_nested_demos(self):
        template = (Path(__file__).resolve().parents[1] / 'templates/catalogo.html').read_text()
        projects = [{'name':name, 'rel_path':path} for name,path in [
            ('Demo', 'Expansions/Pack/Demos/Demo.xpj'),
            ('Kit', 'Expansions/Pack/Kit.xpj'),
            ('Elsewhere', 'Expansions/Pack 2/Other.xpj')]]
        rendered = render_catalog(template, [], {'projects':projects, 'expansions':[
            {'title':'Pack <one>', 'path':'Expansions/Pack', 'programs':4},
            {'title':'Empty', 'path':'Expansions/Empty', 'programs':0}]})
        self.assertIn('4 programas · 2 proyectos', rendered)
        self.assertIn('📁 Ver proyectos (2)', rendered)
        self.assertIn('📁 Ver proyectos (0)', rendered)
        self.assertIn('data-title="Pack &lt;one&gt;" onclick="viewExpansionProjects', rendered)
        self.assertIn('data-path="Expansions/Pack/Demos/Demo.xpj" data-search=', rendered)

    def test_reindex_is_repeatable_and_catalog_matches_database(self):
        script = Path(__file__).resolve().parents[1] / 'index_mpc_library.py'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with wave.open(str(root / 'Kick_demo.wav'), 'wb') as audio:
                audio.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
                audio.writeframes(b'\x00\x00' * 441)
            for _ in range(2):
                subprocess.run([sys.executable, '-B', str(script), '--path', str(root)],
                               check=True, capture_output=True, timeout=20)
                with sqlite3.connect(root / 'BeatOS/data/mpc_sample.db') as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM samples').fetchone()[0], 1)
                html = (root / 'BeatOS/data/catalogo.html').read_text()
                marker = re.search(r'const SAMPLES\s*=\s*', html)
                rows, _ = json.JSONDecoder().raw_decode(html[marker.end():])
                self.assertEqual(len(rows), 1)
                self.assertEqual(len(rows[0]), 12)
                self.assertEqual(rows[0][10], 'Kick_demo.wav')

    def test_reindex_refreshes_both_catalog_names_and_marks_bad_projects(self):
        script = Path(__file__).resolve().parents[1] / 'index_mpc_library.py'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'Broken.xpj').write_bytes(b'invalid project');(root/'_INDEX_MPC_SAMPLE').mkdir()
            (root/'catalogo_mpc_sample.html').write_text('<html>legacy</html>', encoding='utf-8')
            subprocess.run([sys.executable,str(script),'--path',str(root)],check=True,capture_output=True)
            html=(root/'BeatOS/data/catalogo.html').read_text()
            self.assertTrue('Revisar referencias' in html);self.assertIn('data-path="Broken.xpj"',html)
            for name in ['catalogo_beatos.html','catalogo_universal.html']:
                entry=(root/name).read_text()
                self.assertIn('BeatOS/data/catalogo.html',entry)
                self.assertNotIn('const SAMPLES',entry)
            self.assertFalse((root/'catalogo_mpc_sample.html').exists())
            self.assertFalse((root/'SQLITE_DATABASE').exists())
            self.assertFalse(any((root/'_INDEX_MPC_SAMPLE').iterdir()))

    def test_repeated_indexing_keeps_all_generated_state_in_application_folder(self):
        script=Path(__file__).resolve().parents[1]/'index_mpc_library.py'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'BeatOS/templates').mkdir(parents=True)
            (root/'BeatOS/templates/private.xpj').write_bytes(b'ignored')
            for attempt in range(2):
                subprocess.run([sys.executable,str(script),'--path',str(root)],check=True,capture_output=True)
                self.assertEqual({p.name for p in root.iterdir()},{'BeatOS','catalogo_beatos.html','catalogo_universal.html'})
                self.assertFalse(list(root.rglob('__pycache__')))
                with sqlite3.connect(root/'BeatOS/data/mpc_sample.db') as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM projects').fetchone()[0],0)

    def test_catalogo_universal_points_to_master_ecosystem_dashboard_when_present(self):
        from beatos_paths import write_catalog
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dash = root / 'BeatOS/docs/MASTER_ECOSISTEMA_DISCOS.html'
            dash.parent.mkdir(parents=True)
            dash.write_text('<html>Master Ecosystem</html>', encoding='utf-8')
            write_catalog(root, '<html>BeatOS</html>')
            self.assertIn('BeatOS/docs/MASTER_ECOSISTEMA_DISCOS.html', (root / 'catalogo_universal.html').read_text(encoding='utf-8'))
            self.assertIn('BeatOS/data/catalogo.html', (root / 'catalogo_beatos.html').read_text(encoding='utf-8'))

    def test_failed_catalog_replace_preserves_old_catalog_and_cleans_temporary(self):
        from beatos_paths import write_catalog
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/'BeatOS/data/catalogo.html';target.parent.mkdir(parents=True);target.write_text('old')
            with patch.object(Path,'replace',side_effect=OSError('replace failed')):
                with self.assertRaises(OSError):write_catalog(root,'new')
            self.assertEqual(target.read_text(),'old');self.assertFalse(list(root.rglob('*.new')))

    def _write_test_wav(self, wav_path: Path, freq_hz: float = 55.0):
        import math, struct
        sr = 44100
        n_frames = sr // 4
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(wav_path), 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            frames = bytearray()
            for i in range(n_frames):
                sample = int(18000 * math.sin(2.0 * math.pi * freq_hz * i / sr))
                frames.extend(struct.pack('<h', sample))
            wf.writeframes(bytes(frames))

    def test_extended_mpc_kit_multitrack_and_flat_projects(self):
        import gzip
        import xml.etree.ElementTree as ET
        import hardware_kit_builder as hkb
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bass_rel = 'Samples/808_A1.wav'
            kick_rel = 'Samples/Kick_01.wav'
            hat_rel = 'Samples/Hat_Closed.wav'
            synth_rel = 'Samples/Lead_C4.wav'
            self._write_test_wav(root / bass_rel, 55.0)
            self._write_test_wav(root / kick_rel, 65.0)
            self._write_test_wav(root / hat_rel, 4000.0)
            self._write_test_wav(root / synth_rel, 261.63)

            res = hkb.create_kit(
                kit_name='SampQOL_TestKit',
                source_root=str(root),
                target='mpc',
                tempo=132,
                pads=[
                    {
                        'pad': 1, 'rel_path': bass_rel, 'sound_type': 'BASS_808',
                        'mute_group': 4, 'volume': 0.9, 'pan': 0.5, 'tune': 0,
                        'fine_tune': -12, 'root_note': 'F#2', 'key_track': True,
                        'trigger_mode': 'noteon', 'monophonic': False, 'reverse': True,
                        'loop_mode': 1, 'tail_length': 0.35, 'sample_offset': 0.05,
                        'pad_link': 2, 'submix': 1
                    },
                    {'pad': 2, 'rel_path': kick_rel, 'sound_type': 'KICK', 'mute_group': 1},
                    {'pad': 3, 'rel_path': hat_rel, 'sound_type': 'HIHAT', 'mute_group': 2},
                    {'pad': 4, 'rel_path': synth_rel, 'sound_type': 'SYNTH', 'mute_group': 0},
                ],
                mpc_options={
                    'multitrack_mode': 'role_split_4',
                    'audio_route_mode': 'submix_split',
                    'install_to_mpc_projects': True,
                    'gain_profile': 'uniform_b',
                    'force_gain_profile': True,
                    'auto_tune_808': False,
                },
            )
            self.assertTrue(res.get('success'))
            mpc_info = res['targets']['mpc']
            xpm_path = Path(mpc_info['program_path_root'])
            xpj_path = Path(mpc_info['project_path'])
            self.assertTrue(xpm_path.is_file())
            self.assertTrue(xpj_path.is_file())

            # Flat /MPC-Sample/Projects/<kit>.xpj & <kit>_[ProjectData]
            flat_xpj = root / 'MPC-Sample/Projects/SampQOL_TestKit.xpj'
            flat_data = root / 'MPC-Sample/Projects/SampQOL_TestKit_[ProjectData]'
            self.assertTrue(flat_xpj.is_file())
            self.assertTrue(flat_data.is_dir())

            # Inspect XPM XML for Pad 1 extended attributes
            xpm_root = ET.fromstring(xpm_path.read_text(encoding='utf-8'))
            inst1 = xpm_root.find('.//Instrument[@number="1"]')
            self.assertIsNotNone(inst1)
            self.assertEqual(inst1.findtext('TuneFine'), '-12')
            self.assertEqual(inst1.findtext('OneShot'), 'False')
            self.assertEqual(inst1.findtext('Mono'), 'False')
            self.assertEqual(inst1.findtext('SimultTarget1'), '37')
            self.assertEqual(inst1.findtext('AudioRoute/AudioRoute'), '1')
            self.assertEqual(inst1.findtext('AudioRoute/AudioRouteSubIndex'), '0')
            layer1 = inst1.find('Layers/Layer')
            self.assertIsNotNone(layer1)
            self.assertEqual(layer1.findtext('RootNote'), '42')  # F#2
            self.assertEqual(layer1.findtext('KeyTrack'), 'True')
            self.assertEqual(layer1.findtext('Direction'), '1')
            self.assertEqual(layer1.findtext('Loop'), 'True')
            self.assertEqual(layer1.findtext('SliceLoop'), '1')

            # Inspect XPJ JSON for 4-track split + Pad 1 fields
            with gzip.open(str(xpj_path), 'rb') as gz:
                raw_xpj = gz.read().decode('utf-8')
            json_start = raw_xpj.find('{')
            self.assertGreater(json_start, 0)
            payload = json.loads(raw_xpj[json_start:])
            tracks = payload['data']['tracks']
            self.assertGreaterEqual(len(tracks), 4)
            bass_track = next(t for t in tracks if 'Bass 808' in t.get('name', ''))
            first_inst = bass_track['program']['drum']['instruments'][0]
            self.assertEqual(first_inst['fineTune'], -12)
            self.assertEqual(first_inst['triggerMode'], 2)
            self.assertEqual(first_inst['monophonic'], False)
            self.assertEqual(first_inst['simultPlayTargets']['value0'], 37)
            self.assertEqual(first_inst['layersv'][0]['rootNote'], 42)
            self.assertEqual(first_inst['layersv'][0]['keyTrackEnable'], True)
            self.assertEqual(first_inst['layersv'][0]['direction'], 1)

    def test_build_rack_scale_bank_clamped(self):
        import hardware_kit_builder as hkb
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rel = 'Samples/808_C2.wav'
            self._write_test_wav(root / rel, 65.41)  # C2
            res = hkb.build_rack_scale_bank(
                sample_path=root / rel,
                source_root=root,
                scale='minor',
                target_root_note='C3',
                start_octave=0,
                bank_index=0,
                monophonic=True,
                auto_detect_pitch=True,
            )
            self.assertTrue(res.get('success'))
            self.assertEqual(len(res['pads']), 16)
            for p in res['pads']:
                self.assertGreaterEqual(p['tune'], -24)
                self.assertLessEqual(p['tune'], 24)
                self.assertTrue(p['monophonic'])

    def test_read_and_update_mpcqol_conf(self):
        import hardware_kit_builder as hkb
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'autorun').mkdir()
            (root / 'autorun/mpcqol.so').write_bytes(b'ELF')
            (root / 'mpcqol.conf').write_text('zerosnap=0\nkilleq=0\n', encoding='utf-8')
            read1 = hkb.read_mpcqol_conf(str(root))
            self.assertTrue(read1['sampqol_detected'])
            self.assertTrue(read1['conf_exists'])
            self.assertEqual(read1['raw_values']['zerosnap'], '0')

            upd = hkb.update_mpcqol_conf(str(root), preset='beatos_master', updates={'killeq': 1})
            self.assertTrue(upd['success'])
            self.assertTrue((root / 'mpcqol.conf.bak-beatos').is_file())
            self.assertEqual(upd['raw_values']['zerosnap'], '1')
            self.assertEqual(upd['raw_values']['killeq'], '1')
