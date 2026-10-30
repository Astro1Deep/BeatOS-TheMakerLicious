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
        preview = (root / 'BeatOS/data/catalogo.html').read_text(encoding='utf-8')
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
            subprocess.run([sys.executable,str(script),'--path',str(root)],check=True,capture_output=True)
            html=(root/'BeatOS/data/catalogo.html').read_text()
            self.assertTrue('Revisar referencias' in html);self.assertIn('data-path="Broken.xpj"',html)
            for name in ['catalogo_universal.html','catalogo_mpc_sample.html']:
                entry=(root/name).read_text()
                self.assertIn('BeatOS/data/catalogo.html',entry)
                self.assertNotIn('const SAMPLES',entry)
            self.assertFalse((root/'SQLITE_DATABASE').exists())
            self.assertFalse(any((root/'_INDEX_MPC_SAMPLE').iterdir()))

    def test_repeated_indexing_keeps_all_generated_state_in_application_folder(self):
        script=Path(__file__).resolve().parents[1]/'index_mpc_library.py'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'BeatOS/templates').mkdir(parents=True)
            (root/'BeatOS/templates/private.xpj').write_bytes(b'ignored')
            for attempt in range(2):
                subprocess.run([sys.executable,str(script),'--path',str(root)],check=True,capture_output=True)
                self.assertEqual({p.name for p in root.iterdir()},{'BeatOS','catalogo_universal.html','catalogo_mpc_sample.html'})
                self.assertFalse(list(root.rglob('__pycache__')))
                with sqlite3.connect(root/'BeatOS/data/mpc_sample.db') as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM projects').fetchone()[0],0)

    def test_failed_catalog_replace_preserves_old_catalog_and_cleans_temporary(self):
        from beatos_paths import write_catalog
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=root/'BeatOS/data/catalogo.html';target.parent.mkdir(parents=True);target.write_text('old')
            with patch.object(Path,'replace',side_effect=OSError('replace failed')):
                with self.assertRaises(OSError):write_catalog(root,'new')
            self.assertEqual(target.read_text(),'old');self.assertFalse(list(root.rglob('*.new')))
