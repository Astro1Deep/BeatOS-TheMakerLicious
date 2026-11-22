import contextlib
import io
import json
import struct
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import wave
from http.server import HTTPServer
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import serve_mpc


class ServerSecurityTests(unittest.TestCase):

    def test_acoustic_features_use_audible_stereo_channel(self):
        import math
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with wave.open(str(root / 'stereo.wav'), 'wb') as audio:
                audio.setparams((2, 2, 8000, 0, 'NONE', 'not compressed'))
                audio.writeframes(b''.join(struct.pack('<hh', 0, int(12000 * math.sin(2 * math.pi * 100 * i / 8000)))
                                           for i in range(8000)))
            report = serve_mpc.analyze_rack_with_cerebro(str(root), {
                'pads': [{'pad': 1, 'rel_path': 'stereo.wav', 'sound_type': 'PERCUSSION'}]
            })['pads'][0]
            self.assertGreater(report['zcr_hz'], 90)
            self.assertGreater(report['low_energy_ratio'], 0.5)

    @contextlib.contextmanager
    def server(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            root = parent / 'library'
            root.mkdir()
            (parent / 'outside.txt').write_text('private outside marker')
            (root / 'inside.txt').write_text('library file')
            (root / 'escape.txt').symlink_to(parent / 'outside.txt')
            server = serve_mpc.HTTPServer(('127.0.0.1', 0), serve_mpc.MPCAudioRequestHandler)
            server.root_dir = str(root)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                yield f'http://127.0.0.1:{server.server_port}', parent
            finally:
                server.shutdown()
                thread.join()
                server.server_close()

    def request(self, url, **kwargs):
        timeout = kwargs.pop('timeout', 10)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, **kwargs), timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def test_serves_library_and_range(self):
        with self.server() as (url, _):
            self.assertEqual(self.request(url + '/inside.txt'), (200, b'library file'))
            self.assertEqual(self.request(url + '/inside.txt', headers={'Range': 'bytes=0-2'}), (206, b'lib'))

    def test_http_root_serves_the_generated_bilingual_catalog_not_a_stale_entry(self):
        from index_mpc_library import render_catalog
        source = (Path(__file__).resolve().parents[1] / 'templates/catalogo.html').read_text(encoding='utf-8')
        expected = render_catalog(source, [], {})
        with self.server() as (url, parent):
            root = parent / 'library'
            deployed = root / 'BeatOS/data/catalogo.html'
            deployed.parent.mkdir(parents=True)
            deployed.write_text(expected, encoding='utf-8')
            (root / 'catalogo_universal.html').write_text('<html>OUTDATED UI</html>', encoding='utf-8')
            (root / 'catalogo_beatos.html').write_text('<html>OUTDATED UI</html>', encoding='utf-8')
            for endpoint in ('/', '/catalogo', '/catalogo.html', '/BeatOS/data/catalogo.html'):
                with self.subTest(endpoint=endpoint):
                    status, payload = self.request(url + endpoint)
                    self.assertEqual(status, 200)
                    self.assertEqual(payload.decode('utf-8'), expected)
            self.assertIn('const BEATOS_UI_EN = ', expected)
            self.assertIn('"⚡ Generar Kit EP-133":"⚡ Generate EP-133 kit"', expected)

    def test_kit_download_streams_large_files_and_preserves_utf8_filename(self):
        from unittest.mock import patch
        from urllib.parse import quote
        with self.server() as (url, parent):
            folder = parent / 'library' / 'Custom_Kits'
            folder.mkdir()
            name = 'Percusión_Kit_á.zip'
            file = folder / name
            payload = b'BEATOS_KIT_' * 1024 * 128
            file.write_bytes(payload)
            # A download must stream rather than load an entire music pack into RAM.
            with patch.object(Path, 'read_bytes', side_effect=AssertionError('eager read_bytes prohibited')):
                req = urllib.request.Request(url + '/api/download_file?path=' + quote('Custom_Kits/' + name))
                with urllib.request.urlopen(req, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(int(response.headers['Content-Length']), len(payload))
                    disposition = response.headers['Content-Disposition']
                    self.assertIn("filename*=UTF-8''", disposition)
                    self.assertIn(quote(name, safe=''), disposition)
                    self.assertEqual(response.read(), payload)

    def test_download_io_failure_reports_http_500_instead_of_disconnect(self):
        from unittest.mock import patch
        with self.server() as (url, parent):
            folder = parent / 'library' / 'Custom_Kits'
            folder.mkdir()
            (folder / 'locked.zip').write_bytes(b'zip bytes')
            with patch.object(Path, 'open', side_effect=PermissionError('simulated denied access')):
                status, body = self.request(url + '/api/download_file?path=Custom_Kits/locked.zip')
            self.assertEqual(status, 500)
            self.assertNotIn(b'zip bytes', body)

    def test_rejects_traversal_symlinks_and_absolute_downloads(self):
        with self.server() as (url, parent):
            for path in ('/%2e%2e/outside.txt', '/escape.txt',
                         '/api/download_file?path=' + str(parent / 'outside.txt')):
                with self.subTest(path=path):
                    status, body = self.request(url + path)
                    self.assertIn(status, (403, 404))
                    self.assertNotIn(b'private outside marker', body)

    def test_rejects_foreign_origin_and_host(self):
        with self.server() as (url, _):
            for headers in ({'Origin': 'https://untrusted.example'}, {'Host': 'untrusted.example'}):
                self.assertEqual(self.request(url + '/inside.txt', headers=headers)[0], 403)
            self.assertEqual(self.request(url + '/inside.txt', headers={'Origin': url})[0], 200)
            self.assertEqual(self.request(url + '/api/po33_backups', headers={'Sec-Fetch-Site':'cross-site'})[0],403)

    def test_opaque_web_origins_cannot_read_or_preflight_local_api(self):
        with self.server() as (url, _):
            for site in ('cross-site', 'none'):
                headers = {'Origin': 'null', 'Sec-Fetch-Site': site}
                self.assertEqual(self.request(url + '/api/status', headers=headers)[0], 403)
                preflight_headers = {**headers, 'Access-Control-Request-Method': 'POST'}
                self.assertEqual(self.request(url + '/api/theme', method='OPTIONS', headers=preflight_headers)[0], 403)

    def test_rejects_oversized_or_negative_request_lengths(self):
        with self.server() as (url, _):
            for length in ('-1', '2097152'):
                self.assertIn(self.request(url + '/api/create_kit', data=b'',
                                          headers={'Content-Length': length})[0], (400, 413))

    def test_po_backup_import_inventory_and_download_are_byte_exact(self):
        import io,json,struct,wave,hashlib,urllib.parse
        buffer=io.BytesIO()
        with wave.open(buffer,'wb') as wav:
            wav.setparams((2,2,48000,0,'NONE',''));wav.writeframes(struct.pack('<hh',1234,-6789)*4800)
        raw=buffer.getvalue()
        with self.server() as (url,parent):
            status,body=self.request(url+'/api/po33_backups?name=Mi%20PO.WAV',data=raw,headers={'Content-Type':'audio/wav','Origin':url})
            self.assertEqual(status,200,body);info=json.loads(body)['backup']
            self.assertEqual(info['sha256'],hashlib.sha256(raw).hexdigest());self.assertFalse(info['payload_verified'])
            self.assertTrue(Path(info['path']).is_relative_to(parent.resolve()/'library/BeatOS/data/po33_backups'))
            self.assertEqual(self.request(url+'/api/po33_backup_audio?file='+urllib.parse.quote(info['path'])),(200,raw))
            inventory=json.loads(self.request(url+'/api/po33_backups')[1])
            self.assertIn(info['path'],[b['path'] for b in inventory['backups']])
            self.assertEqual(self.request(url+'/api/po33_backup_audio?file='+str(parent/'outside.txt'))[0],404)
            self.assertEqual(self.request(url+'/docs/assets/po33-capture-worklet.js')[0],200)

    def test_po_model_profiles_classified_import_and_read_only_verify(self):
        import io, json, wave, struct, urllib.parse
        buffer=io.BytesIO()
        with wave.open(buffer,'wb') as wav:
            wav.setparams((2,2,48000,0,'NONE',''))
            wav.writeframes(struct.pack('<hh',1234,-2345)*480)
        raw=buffer.getvalue()
        with self.server() as (url,parent):
            status,profiles=self.request(url+'/api/po_backup_profiles')
            self.assertEqual(status,200)
            profiles=json.loads(profiles)
            self.assertEqual(set(profiles['backup_models']),{'PO-32','PO-33','PO-35','PO-133','PO-137'})
            self.assertIn('PO-20',profiles['audio_only_models'])
            endpoint=url+'/api/po33_backups?name=demo.wav&model=PO-35&project=Beat%20Test'
            status,body=self.request(endpoint,data=raw,headers={'Content-Type':'audio/wav'})
            self.assertEqual(status,200,body)
            backup=json.loads(body)['backup']
            self.assertEqual(backup['model'],'PO-35')
            self.assertEqual(backup['project'],'Beat Test')
            self.assertFalse(backup['payload_verified'])
            self.assertEqual(self.request(url+'/api/po33_backup_audio?file='+
                urllib.parse.quote(backup['path']))[1],raw)
            status,verify=self.request(url+'/api/po_backup_verify',
                data=json.dumps({'file':backup['path']}).encode(),
                headers={'Content-Type':'application/json'})
            self.assertEqual(status,200,verify)
            result=json.loads(verify)['verification']
            self.assertEqual(result['model'],'PO-35')
            self.assertFalse(result['payload_verified'])
            self.assertFalse(result['device_restore_verified'])
            inventory=json.loads(self.request(url+'/api/po33_backups')[1])['backups']
            self.assertEqual(inventory[0]['project'],'Beat Test')
            self.assertEqual(self.request(url+'/api/po_backup_verify',
                data=json.dumps({'file':str(parent/'outside.txt')}).encode(),
                headers={'Content-Type':'application/json'})[0],400)
            self.assertEqual(self.request(url+'/api/po33_backups?model=PO-20&name=bad.wav',
                data=raw,headers={'Content-Type':'audio/wav'})[0],400)

    def test_legacy_backup_can_be_classified_explicitly_without_changing_audio(self):
        import io, json, wave, struct, hashlib
        buffer=io.BytesIO()
        with wave.open(buffer,'wb') as audio:
            audio.setparams((2,2,44100,0,'NONE',''))
            audio.writeframes(struct.pack('<hh',5432,-3145)*1200)
        original=buffer.getvalue()
        with self.server() as (url, parent):
            status,raw=self.request(url+'/api/po33_backups?name=Old_Beat.wav',
                data=original,headers={'Content-Type':'audio/wav'})
            self.assertEqual(status,200,raw)
            first=json.loads(raw)['backup']
            inventory=json.loads(self.request(url+'/api/po33_backups')[1])['backups']
            self.assertEqual(inventory[0]['model'],'UNSPECIFIED')
            oldhash=hashlib.sha256(original).hexdigest()
            def classify(model,project,file=first['path']):
                return self.request(url+'/api/po_backup_classify',
                    data=json.dumps({'file':file,'model':model,'project':project}).encode(),
                    headers={'Content-Type':'application/json'})
            status,body=classify('PO-33','Mi beat antiguo')
            self.assertEqual(status,200,body)
            info=json.loads(body)['backup']
            self.assertEqual(info['model'],'PO-33')
            self.assertEqual(info['project'],'Mi beat antiguo')
            self.assertEqual(Path(first['path']).read_bytes(),original)
            self.assertEqual(hashlib.sha256(Path(first['path']).read_bytes()).hexdigest(),oldhash)
            self.assertEqual(classify('PO-33','Mi beat antiguo')[0],200)
            self.assertEqual(classify('PO-32','Otro beat')[0],400)
            self.assertEqual(classify('PO-20','No data')[0],400)
            self.assertEqual(classify('PO-33','No data',file=str(parent/'outside.txt'))[0],400)
            refreshed=json.loads(self.request(url+'/api/po33_backups')[1])['backups']
            self.assertEqual(refreshed[0]['model'],'PO-33')
            self.assertEqual(refreshed[0]['project'],'Mi beat antiguo')

    def test_po_backup_import_rejects_bad_audio_foreign_origin_and_oversize(self):
        with self.server() as (url,parent):
            self.assertEqual(self.request(url+'/api/po33_backups',data=b'bad'*20,headers={'Content-Type':'audio/wav'})[0],400)
            self.assertEqual(self.request(url+'/api/po33_backups',data=b'bad',headers={'Content-Type':'text/plain'})[0],400)
            self.assertEqual(self.request(url+'/api/po33_backups',data=b'bad',headers={'Content-Type':'audio/wav','Origin':'https://evil.example'})[0],403)
            self.assertEqual(self.request(url+'/api/po33_backups',data=b'',headers={'Content-Length':str(128*1024*1024+1)})[0],413)
            self.assertFalse((parent/'library/BeatOS/data/po33_backups').exists())

    def test_busy_port_does_not_reuse_a_different_library(self):
        from unittest.mock import patch,MagicMock
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();server=MagicMock();server.serve_forever.side_effect=KeyboardInterrupt
            with patch.object(serve_mpc,'find_available_port',return_value=8889), patch.object(serve_mpc,'existing_library_root',return_value=root/'other'), patch.object(serve_mpc,'HTTPServer',return_value=server) as factory:
                serve_mpc.run_server(str(root),port=8888,auto_open=False)
                factory.assert_called_once();self.assertEqual(server.root_dir,str(root));server.server_close.assert_called_once()
            with patch.object(serve_mpc,'find_available_port',return_value=8889), patch.object(serve_mpc,'existing_library_root',return_value=root), patch.object(serve_mpc,'HTTPServer') as factory:
                serve_mpc.run_server(str(root),port=8888,auto_open=False);factory.assert_not_called()

    def test_separate_library_uses_installed_assets_without_exposing_other_code(self):
        with self.server() as (url, _):
            status, body = self.request(url + '/docs/assets/branding/blueprint_bone_sin_marcas.png')
            self.assertEqual(status,200)
            self.assertTrue(body.startswith(b'\x89PNG'))
            for path in ['/docs/assets/%2e%2e/%2e%2e/installer.py','/docs/assets/%2e%2e/%2e%2e/%2e%2e/outside.txt']:
                self.assertIn(self.request(url+path)[0],(403,404))

    def test_native_file_browser_uses_platform_command(self):
        import json
        from unittest.mock import patch
        with self.server() as (url, parent):
            for platform in ['darwin','win32','linux']:
                with self.subTest(platform=platform),patch('serve_mpc.sys.platform',platform),patch('serve_mpc.subprocess.run') as run,patch('serve_mpc.os.startfile',create=True) as startfile:
                    status,body=self.request(url+'/api/reveal_in_finder',data=json.dumps({'path':'inside.txt'}).encode(),method='POST',headers={'Origin':url,'Content-Type':'application/json'})
                    self.assertEqual(status,200,body)
                    if platform=='win32': startfile.assert_called_once_with(str((parent/'library').resolve()))
                    else: self.assertEqual(run.call_args.args[0][0],'open' if platform=='darwin' else 'xdg-open')

    @unittest.skipIf(sys.platform == 'win32','Unix TIME_WAIT reuse')
    def test_recently_closed_http_port_is_reusable(self):
        import socket
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            listener.bind(('127.0.0.1',0));port=listener.getsockname()[1];listener.listen(1)
            with socket.create_connection(('127.0.0.1',port)) as client:
                connection,_=listener.accept()
                connection.sendall(b'x');connection.close()
                self.assertEqual(client.recv(2),b'x');self.assertEqual(client.recv(2),b'')
        self.assertEqual(serve_mpc.find_available_port(port,2),port)

    def test_organized_catalog_is_served_and_internal_state_is_private(self):
        with self.server() as (url,parent):
            app=parent/'library/BeatOS';(app/'data').mkdir(parents=True)
            (app/'data/catalogo.html').write_text('<html>organized catalog</html>')
            (app/'data/mpc_sample.db').write_text('private database')
            for endpoint in ['/','/BeatOS/data/catalogo.html','/_INDEX_MPC_SAMPLE/catalogo_universal.html']:
                status,body=self.request(url+endpoint);self.assertEqual(status,200);self.assertIn(b'organized catalog',body)
            for endpoint in ['/BeatOS/data/mpc_sample.db','/api/download_file?path=BeatOS/data/mpc_sample.db','/BeatOS/config/theme_config.json']:
                self.assertIn(self.request(url+endpoint)[0],(403,404))
            status,body=self.request(url+'/BeatOS/docs/assets/branding/blueprint_bone_sin_marcas.png')
            self.assertEqual(status,200);self.assertTrue(body.startswith(b'\x89PNG'))
            (app/'docs').mkdir(parents=True,exist_ok=True)
            (app/'docs/MASTER_ECOSISTEMA_DISCOS.html').write_text('<html>master ecosystem dashboard</html>',encoding='utf-8')
            for endpoint in ['/catalogo_universal.html','/BeatOS/docs/MASTER_ECOSISTEMA_DISCOS.html']:
                status,body=self.request(url+endpoint);self.assertEqual(status,200);self.assertIn(b'master ecosystem dashboard',body)

    def test_cross_site_top_level_navigation_probe_clean_metadata_and_expansion_kit_load(self):
        import json
        with self.server() as (url, parent):
            app = parent / 'library/BeatOS'
            (app / 'data').mkdir(parents=True, exist_ok=True)
            (app / 'data/catalogo.html').write_text('<html>beatos catalog</html>', encoding='utf-8')
            exp_root = parent / 'library/Expansions/DemoPack'
            proj_data = exp_root / 'Demo Kit_[ProjectData]'
            proj_data.mkdir(parents=True, exist_ok=True)
            (proj_data / 'Kick.wav').write_bytes(b'RIFFdemo')
            (proj_data / '._Kick.wav').write_bytes(b'AppleDouble')
            (exp_root / 'Demo Kit.xpm').write_text(
                '<MPCVObject><Program type="Drum"><Instruments>'
                '<Instrument number="1"><Layers><Layer number="1"><SampleName>Kick</SampleName><SampleFile>Kick.wav</SampleFile></Layer></Layers></Instrument>'
                '</Instruments></Program></MPCVObject>',
                encoding='utf-8',
            )

            status, body = self.request(url + '/', headers={'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'document'})
            self.assertEqual(status, 200)
            self.assertIn(b'beatos catalog', body)

            status, body = self.request(url + '/beatos-online.js')
            self.assertEqual(status, 200)
            self.assertIn(b'window.__BEATOS_LOCAL_SERVER_ONLINE', body)
            self.assertEqual(self.request(url + '/beatos-online.js', headers={'Origin': 'https://evil.example'})[0], 403)

            status, body = self.request(url + '/api/clean_metadata', method='POST', data=b'', headers={'Origin': url})
            self.assertEqual(status, 200, body)
            self.assertTrue(json.loads(body)['success'])
            self.assertFalse((proj_data / '._Kick.wav').exists())

            status, body = self.request(
                url + '/api/list_expansion_programs',
                method='POST',
                data=json.dumps({'expansion_name': 'OtroAlias', 'expansion_path': 'Expansions/DemoPack'}).encode(),
                headers={'Origin': url, 'Content-Type': 'application/json'},
            )
            self.assertEqual(status, 200, body)
            programs = json.loads(body)['programs']
            self.assertEqual(len(programs), 1)
            self.assertEqual(programs[0]['rel_path'], 'Expansions/DemoPack/Demo Kit.xpm')

            status, body = self.request(
                url + '/api/load_xpm_program',
                method='POST',
                data=json.dumps({'rel_path': programs[0]['rel_path']}).encode(),
                headers={'Origin': url, 'Content-Type': 'application/json'},
            )
            self.assertEqual(status, 200, body)
            pad1 = json.loads(body)['program']['pads']['1']
            self.assertFalse(pad1['missing'])
            self.assertEqual(pad1['rel_path'], 'Expansions/DemoPack/Demo Kit_[ProjectData]/Kick.wav')

    def test_dashboard_refresh_and_sync_discover_external_volumes_without_cerebro(self):
        import json
        import sqlite3
        from unittest.mock import patch
        with self.server() as (url, parent):
            root = parent / "library"
            external = parent / "Producer's USB ñ"
            index = external / "_INDEX_AUDIO" / "arbitrary-name.db"
            index.parent.mkdir(parents=True)
            with contextlib.closing(sqlite3.connect(index)) as connection:
                connection.execute("CREATE TABLE tracks (title TEXT, relative_path TEXT)")
                connection.execute("INSERT INTO tracks VALUES (?, ?)", ("Break", "Break.wav"))
                connection.commit()
            before = index.read_bytes()
            with patch.object(serve_mpc, "mounted_volume_paths", return_value=[external]), \
                 patch.dict("os.environ", {"BEATOS_FORCE_HIDE_CEREBRO": "1"}):
                for endpoint in ("/ecosystem", "/BeatOS/docs/MASTER_ECOSISTEMA_DISCOS.html"):
                    status, html = self.request(url + endpoint)
                    self.assertEqual(status, 200)
                    self.assertIn(b"Master Ecosystem", html)
                self.assertEqual(self.request(url + "/BeatOS/docs/assets/beatos-maintenance.js")[0], 200)
                status, raw = self.request(url + "/api/ecosystem")
                self.assertEqual(status, 200, raw)
                inventory = json.loads(raw)["inventory"]
                self.assertEqual(len(inventory["volumes"]), 2)
                self.assertEqual(inventory["libraries"][0]["sample_count"], 1)
                self.assertEqual(inventory["libraries"][0]["mount_path"], str(external.resolve()))
                status, raw = self.request(url + "/api/sync_dashboard", data=b"", method="POST", headers={"Origin": url})
                self.assertEqual(status, 200, raw)
                snapshot = root / "BeatOS/config/ecosystem_inventory.json"
                self.assertFalse(json.loads(snapshot.read_text())["cerebro_installed"])
                self.assertEqual(self.request(url + "/BeatOS/config/ecosystem_inventory.json")[0], 403)
                self.assertFalse((external / "MASTER_ECOSISTEMA_DISCOS.html").exists())
                self.assertEqual(before, index.read_bytes())

    def test_reindex_updates_catalog_and_reports_completion(self):
        import json
        import sqlite3
        import time
        with self.server() as (url, parent):
            root = parent / "library"
            with wave.open(str(root / "Kick prueba.wav"), "wb") as audio:
                audio.setparams((1, 2, 44100, 0, "NONE", "not compressed"))
                audio.writeframes(struct.pack("<h", 1000) * 1024)
            status, raw = self.request(url + "/api/reindex", data=b"", method="POST", headers={"Origin": url})
            self.assertEqual(status, 200, raw)
            self.assertTrue(json.loads(raw)["success"])
            deadline = time.monotonic() + 15
            while True:
                _, raw = self.request(url + "/api/task_status")
                task = json.loads(raw)
                if not task["running"]:
                    break
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.04)
            self.assertTrue(task["success"], task["logs"])
            self.assertIn(b"Kick prueba.wav", self.request(url + "/")[1])
            with contextlib.closing(sqlite3.connect(root / "BeatOS/data/mpc_sample.db")) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM samples").fetchone()[0], 1)

    def test_catalog_names_persist_without_renaming_expansion_files(self):
        import gzip
        import json
        with self.server() as (url, parent):
            root = parent / "library"
            expansion = root / "Expansions/Demo"
            expansion.mkdir(parents=True)
            manifest = expansion / "Expansion.xml"
            project = expansion / "Original.xpj"
            program = expansion / "Original.xpm"
            manifest.write_text("<Expansion><title>Demo</title></Expansion>", encoding="utf-8")
            project.write_bytes(gzip.compress(b'ACVS\n{"data":{"tracks":[]}}'))
            program.write_text('<MPCVObject><Program type="Drum"><ProgramName>Original</ProgramName></Program></MPCVObject>',
                               encoding="utf-8")
            originals = {item: item.read_bytes() for item in (manifest, project, program)}
            endpoint = url + "/api/library_names"
            headers = {"Origin": url, "Content-Type": "application/json"}

            def rename(path, title):
                return self.request(endpoint, data=json.dumps({"path": str(path), "name": title}).encode(),
                                    headers=headers)

            self.assertEqual(rename(expansion, "Colección de prueba")[0], 200)
            self.assertEqual(rename(project, "01 · Boom Bap 90")[0], 200)
            self.assertEqual(rename(program, "02 · Snares")[0], 200)
            self.assertEqual(rename("escape.txt", "Other")[0], 400)
            self.assertEqual(rename(program, "Invalid\nTitle")[0], 400)
            state = json.loads(self.request(endpoint)[1])["names"]
            self.assertEqual(state["Expansions/Demo/Original.xpj"], "01 · Boom Bap 90")
            self.assertEqual(state["Expansions/Demo/Original.xpm"], "02 · Snares")
            self.assertEqual(state["Expansions/Demo"], "Colección de prueba")
            _, raw = self.request(url + "/api/list_expansion_programs",
                                  data=b'{"expansion_name":"Demo"}', headers=headers)
            self.assertEqual(json.loads(raw)["programs"][0]["name"], "02 · Snares")
            _, raw = self.request(url + "/api/load_project",
                                  data=b'{"rel_path":"Expansions/Demo/Original.xpj"}', headers=headers)
            self.assertEqual(json.loads(raw)["project"]["project_name"], "01 · Boom Bap 90")
            self.assertEqual(rename(program, "")[0], 200)
            self.assertNotIn("Expansions/Demo/Original.xpm", json.loads(self.request(endpoint)[1])["names"])
            for item, original in originals.items():
                self.assertEqual(item.read_bytes(), original)
            self.assertEqual(self.request(url + "/BeatOS/config/library_names.json")[0], 403)

    def test_master_produce_keeps_pad_numbers_and_returns_internal_submixes(self):
        import json
        with self.server() as (url, parent):
            root = parent / "library"
            for name in ("Kick.wav", "Hat.wav", "Vocal.wav"):
                with wave.open(str(root / name), "wb") as audio:
                    audio.setparams((1, 2, 44100, 0, "NONE", "not compressed"))
                    audio.writeframes(struct.pack("<h", 500) * 4096)
            payload = {"gain_profile": "manual", "pads": [
                {"pad": 1, "rel_path": "Kick.wav", "sound_type": "KICK", "mute_group": 0, "volume": 0.7},
                {"pad": 4, "rel_path": "Hat.wav", "sound_type": "HIHAT"},
                {"pad": 16, "rel_path": "Vocal.wav", "sound_type": "VOCAL"},
            ]}
            endpoint = url + "/api/cerebro_master_produce"
            headers = {"Origin": url, "Content-Type": "application/json"}
            code, body = self.request(endpoint, data=json.dumps(payload).encode(), headers=headers)
            self.assertEqual(code, 200, body)
            result = json.loads(body)
            pads = result["calibration"]["pads"]
            self.assertEqual([(p["pad"], p["submix"]) for p in pads], [(1, 0), (4, 2), (16, 3)])
            self.assertEqual((pads[0]["volume"], pads[0]["mute_group"]), (0.7, 0))
            self.assertEqual(self.request(endpoint, data=b"{}", headers=headers)[0], 400)
            self.assertFalse((root / "Custom_Kits").exists())

    def test_primary_melody_beats_single_percussion_label_and_keeps_source_tempo(self):
        import math
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files = [(5, "Short Ocean Drill Hat.wav", "HIHAT"),
                     (13, "Lo-Fi_Piano_Bmaj_90BPM001.wav", "KEYS_SYNTH")]
            pads = []
            for pad, name, sound_type in files:
                with wave.open(str(root / name), "wb") as audio:
                    audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
                    count = 16000 if pad == 13 else 640
                    audio.writeframes(b"".join(struct.pack("<h", int(1000 * math.sin(frame / 10)))
                                               for frame in range(count)))
                pads.append({"pad": pad, "rel_path": name, "sound_type": sound_type})
            data = serve_mpc.analyze_rack_with_cerebro(str(root), {"tempo": 120, "pads": pads})
            self.assertEqual(data["style_id"], "lofi")
            self.assertEqual(data["style"]["basis"], "sample_label")
            self.assertNotIn("confidence", data["style"])
            self.assertEqual(data["style_reference"]["pad"], 13)
            self.assertEqual(data["style_reference"]["tagged_bpm"], 90)
            self.assertEqual(data["rhythm_analysis"]["source_bpm"], 90)
            self.assertEqual(data["rack_bpm"], 120)
            self.assertEqual(data["drum_style_hints"], [{"label": "UK / NY Drill", "pads": [5]}])

    def test_cerebro_analyze_long_paths_and_create_expansion_syncs_catalog(self):
        import base64
        import json
        import struct
        import wave
        import zlib

        def write_wav(path):
            path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(path), 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(44100)
                wf.writeframes(b'\x00\x00' * 441)

        def make_large_png_data_url(width=640, height=640):
            def chunk(tag, data):
                return (
                    struct.pack('!I', len(data))
                    + tag
                    + data
                    + struct.pack('!I', zlib.crc32(tag + data) & 0xFFFFFFFF)
                )

            ihdr = struct.pack('!IIBBBBB', width, height, 8, 2, 0, 0, 0)
            raw_scanlines = (b'\x00' + (b'\x10\x20\x30' * width)) * height
            idat = zlib.compress(raw_scanlines, 0)
            png_bytes = (
                b'\x89PNG\r\n\x1a\n'
                + chunk(b'IHDR', ihdr)
                + chunk(b'IDAT', idat)
                + chunk(b'IEND', b'')
            )
            return 'data:image/png;base64,' + base64.b64encode(png_bytes).decode('ascii')

        with self.server() as (url, parent):
            root = parent / 'library'
            long_sample_dir = (
                root
                / 'Samples'
                / ('LongPackFolder_' + ('X' * 60))
                / ('SubFolder_' + ('Y' * 60))
            )
            long_sample_rel_list = []
            pads = []
            for pad_num in range(1, 18):
                name = f'SuperLongSampleName_{pad_num:02d}_124BPM_' + ('K' * 40) + '.wav'
                wav_path = long_sample_dir / name
                write_wav(wav_path)
                rel = wav_path.relative_to(root).as_posix()
                long_sample_rel_list.append(rel)
                pads.append({
                    'pad': pad_num,
                    'sample_name': name,
                    'rel_path': rel,
                    'sound_type': 'Kick' if pad_num == 1 else 'Snare',
                })

            exp_dir = root / 'Expansions' / 'DemoPack'
            write_wav(exp_dir / 'Demo Kit_[ProjectData]' / 'Kick.wav')
            (exp_dir / 'Demo Kit.xpm').write_text(
                '<MPCVObject><Program type="Drum"><Instruments>'
                '<Instrument number="1"><Layers><Layer number="1">'
                '<SampleName>Kick</SampleName>'
                '</Layer></Layers></Instrument>'
                '</Instruments></Program></MPCVObject>',
                encoding='utf-8',
            )

            import io
            from unittest.mock import patch
            import index_mpc_library

            with patch.object(sys, 'argv', ['index_mpc_library.py', '--path', str(root), '--lang', 'en']):
                with contextlib.redirect_stdout(io.StringIO()):
                    index_mpc_library.main()

            status, body = self.request(
                url + '/api/cerebro_analyze',
                method='POST',
                data=json.dumps({'kit_name': 'Long Path Rack 124BPM', 'pads': pads}).encode('utf-8'),
                headers={'Origin': url, 'Content-Type': 'application/json'},
            )
            self.assertEqual(status, 200, body)
            analyze_data = json.loads(body)
            self.assertTrue(analyze_data.get('success'), analyze_data)

            cover_data_url = make_large_png_data_url()
            self.assertGreater(len(cover_data_url), 1_200_000)
            payload = {
                'title': 'My Custom Expansion',
                'manufacturer': 'BeatOS',
                'artist_subfolder': '',
                'description': 'Regression test custom expansion',
                'cover_data_url': cover_data_url,
                'source_kits': ['Expansions/DemoPack/Demo Kit.xpm'],
                'rack_pads': [pads[0], pads[16]],
                'rack_kit_name': 'Custom Rack Kit',
                'rack_tempo': 124,
            }
            status, body = self.request(
                url + '/api/create_expansion',
                method='POST',
                data=json.dumps(payload).encode('utf-8'),
                headers={'Origin': url, 'Content-Type': 'application/json'},
                timeout=30,
            )
            self.assertEqual(status, 200, body)
            exp_data = json.loads(body)
            self.assertTrue(exp_data.get('success'), exp_data)
            self.assertTrue(exp_data.get('expansion_rel_path'))
            self.assertTrue(exp_data.get('zip_rel_path'))
            self.assertGreaterEqual(exp_data.get('kit_count', 0), 1)
            self.assertGreaterEqual(exp_data.get('sample_count', 0), 1)
            self.assertIn('My Custom Expansion', exp_data.get('card_html', ''))

            catalog_html = (root / 'BeatOS' / 'data' / 'catalogo.html').read_text(encoding='utf-8')
            self.assertIn('My Custom Expansion', catalog_html)

            status, body = self.request(
                url + '/api/list_expansion_programs',
                method='POST',
                data=json.dumps({
                    'expansion_name': 'My Custom Expansion',
                    'expansion_path': exp_data['expansion_rel_path'],
                }).encode('utf-8'),
                headers={'Origin': url, 'Content-Type': 'application/json'},
            )
            self.assertEqual(status, 200, body)
            programs = json.loads(body).get('programs', [])
            self.assertGreaterEqual(len(programs), 2, programs)
            self.assertTrue(
                any(
                    exp_data['expansion_rel_path'].rstrip('/') in p.get('rel_path', '')
                    for p in programs
                ),
                programs,
            )

    def test_mpc_wav_streaming_repairs_riff_atem_and_float32_24bit(self):
        with self.server() as (url, parent):
            root = parent / 'library'
            samples_dir = root / 'Samples'
            samples_dir.mkdir(parents=True, exist_ok=True)

            # 1) Standard 16-bit PCM WAV should pass through without normalization
            std_path = samples_dir / 'standard_16bit.wav'
            with wave.open(str(std_path), 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(44100)
                wf.writeframes(struct.pack('<4h', 0, 12000, -12000, 4000))
            self.assertIsNone(serve_mpc.get_browser_playable_wav_bytes(str(std_path)))

            # 2) Akai MPC 16-bit WAV with proprietary atem/smpl chunks & truncated riff_sz
            pcm16 = struct.pack('<4h', 1000, -2000, 16000, -16000)
            fmt_chunk = b'fmt ' + struct.pack('<IHHIIHH', 16, 1, 1, 44100, 88200, 2, 16)
            atem_payload = b'\x01' * 496
            atem_chunk = b'atem' + struct.pack('<I', len(atem_payload)) + atem_payload
            smpl_payload = b'\x00' * 94
            smpl_chunk = b'smpl' + struct.pack('<I', len(smpl_payload)) + smpl_payload
            data_chunk = b'data' + struct.pack('<I', len(pcm16)) + pcm16
            body_chunks = fmt_chunk + atem_chunk + smpl_chunk + data_chunk
            broken_riff_sz = 4 + len(body_chunks) - (8 + len(atem_payload))
            akai_bytes = b'RIFF' + struct.pack('<I', broken_riff_sz) + b'WAVE' + body_chunks
            akai_path = samples_dir / 'akai_atem_broken_riff.wav'
            akai_path.write_bytes(akai_bytes)

            status, served_200 = self.request(url + '/Samples/akai_atem_broken_riff.wav')
            self.assertEqual(status, 200)
            self.assertEqual(struct.unpack_from('<I', served_200, 4)[0] + 8, len(served_200))
            with wave.open(io.BytesIO(served_200), 'rb') as wf:
                self.assertEqual((wf.getnchannels(), wf.getsampwidth(), wf.getframerate()), (1, 2, 44100))
                self.assertEqual(wf.readframes(4), pcm16)
            # Disk file preserved for Akai hardware
            self.assertEqual(akai_path.read_bytes(), akai_bytes)

            # Range request 206 must use normalized WAV length
            status_r, part = self.request(url + '/Samples/akai_atem_broken_riff.wav', headers={'Range': 'bytes=0-43'})
            self.assertEqual(status_r, 206)
            self.assertEqual(part, served_200[:44])

            # 3) 32-bit IEEE float WAV (afmt=3, bps=32) + atem chunk
            f32_pcm = struct.pack('<4f', 0.0, 0.5, -0.5, 1.0)
            f32_fmt = b'fmt ' + struct.pack('<IHHIIHH', 16, 3, 2, 44100, 352800, 8, 32)
            f32_data = b'data' + struct.pack('<I', len(f32_pcm)) + f32_pcm
            f32_body = f32_fmt + atem_chunk + f32_data
            f32_path = samples_dir / 'chop_float32.wav'
            f32_path.write_bytes(b'RIFF' + struct.pack('<I', 4 + len(f32_body) - 504) + b'WAVE' + f32_body)

            status_f, served_f = self.request(url + '/Samples/chop_float32.wav')
            self.assertEqual(status_f, 200)
            with wave.open(io.BytesIO(served_f), 'rb') as wf:
                self.assertEqual((wf.getnchannels(), wf.getsampwidth(), wf.getframerate()), (2, 2, 44100))
                decoded_samples = struct.unpack('<4h', wf.readframes(2))
                self.assertEqual(decoded_samples[0], 0)
                self.assertGreater(decoded_samples[1], 15000)
                self.assertLess(decoded_samples[2], -15000)
                self.assertGreater(decoded_samples[3], 30000)

            # 4) 24-bit PCM WAV (afmt=1, bps=24)
            p24_bytes = b''.join([
                b'\x00\x00\x40',   # +0.5 (~ +16384 in int16)
                b'\x00\x00\xc0',   # -0.5 (~ -16384 in int16)
            ])
            p24_fmt = b'fmt ' + struct.pack('<IHHIIHH', 16, 1, 1, 44100, 132300, 3, 24)
            p24_data = b'data' + struct.pack('<I', len(p24_bytes)) + p24_bytes
            p24_path = samples_dir / 'sample_24bit.wav'
            p24_body = p24_fmt + p24_data
            p24_path.write_bytes(b'RIFF' + struct.pack('<I', 4 + len(p24_body)) + b'WAVE' + p24_body)

            status_24, served_24 = self.request(url + '/Samples/sample_24bit.wav')
            self.assertEqual(status_24, 200)
            with wave.open(io.BytesIO(served_24), 'rb') as wf:
                self.assertEqual((wf.getnchannels(), wf.getsampwidth(), wf.getframerate()), (1, 2, 44100))
                self.assertEqual(struct.unpack('<2h', wf.readframes(2)), (16384, -16384))

    def test_cerebro_bolero_soul_jazz_rhythm_and_hiphop_adaptation(self):
        import json
        import math
        import hardware_kit_builder as hkb

        # 1. Style classification rules (preserving existing Boom Bap & Trap Soul rules)
        st_bolero = hkb.detect_musical_style('Bolero a Lo-Fi 84')
        self.assertEqual(st_bolero['id'], 'bolero')
        self.assertEqual(st_bolero['mute_profile'], 'jazz_funk')

        st_soul = hkb.detect_musical_style('Vintage_Motown_Soul_Rhodes')
        self.assertEqual(st_soul['id'], 'soul_vintage')

        st_jazz = hkb.detect_musical_style('Blue_Note_Jazz_Bossa_Trio')
        self.assertEqual(st_jazz['id'], 'jazz_hop')

        self.assertEqual(hkb.detect_musical_style('Cookin_Soul_BoomBap')['id'], 'boombap')
        self.assertEqual(hkb.detect_musical_style('Trap_Soul_Kit')['id'], 'rnb_soul')
        self.assertEqual(hkb.detect_musical_style('Bossa_Nova_Guitar_Loop')['id'], 'bossa_samba')
        self.assertEqual(hkb.detect_musical_style('Cumbia_Son_Cubano_Montuno')['id'], 'cumbia_son')
        self.assertEqual(hkb.detect_musical_style('Tango_Bandoneon_Vals')['id'], 'tango_vals')
        self.assertEqual(hkb.detect_musical_style('Drumless_Alchemist_Soul_Cut')['id'], 'drumless')
        self.assertEqual(hkb.detect_musical_style('Psych_Library_Score_KPM')['id'], 'psych_library')
        self.assertEqual(hkb.detect_musical_style('Lowrider_Oldies_Doo_Wop_12_8')['id'], 'oldies')
        self.assertEqual(hkb.detect_musical_style('Sweet_Soul_Oldies_50s')['id'], 'oldies')
        self.assertEqual(hkb.infer_kit_bpm('Bossa_Nova_Guitar_Loop'), 84.0)
        self.assertEqual(hkb.infer_kit_bpm('Cumbia_Son_Cubano_Montuno'), 88.0)
        self.assertEqual(hkb.infer_kit_bpm('Tango_Bandoneon_Vals'), 82.0)
        self.assertEqual(hkb.infer_kit_bpm('Drumless_Alchemist_Soul_Cut'), 78.0)
        self.assertEqual(hkb.infer_kit_bpm('Psych_Library_Score_KPM'), 86.0)
        self.assertEqual(hkb.infer_kit_bpm('Lowrider_Oldies_Doo_Wop_12_8'), 84.0)

        sr = 44100

        def _synth_pulse_wav(path: Path, beat_sec: float, pattern: list[float], freq_hz: float = 220.0, offbeat_pos: float = 0.5):
            # Render repeating bar pattern with exponential decay plucks
            total_beats = len(pattern) * 4
            frames = [0] * int(sr * beat_sec * total_beats)
            for bar_idx in range(4):
                for idx_in_bar, amp in enumerate(pattern):
                    if amp <= 0.0:
                        continue
                    beat_idx = bar_idx * len(pattern) + idx_in_bar
                    start = int(round(beat_idx * beat_sec * sr))
                    hit_len = min(int(sr * 0.18), len(frames) - start)
                    for i in range(hit_len):
                        env = math.exp(-i / (sr * 0.035))
                        frames[start + i] = int(max(-32000, min(32000, 26000 * amp * env * math.sin(2.0 * math.pi * freq_hz * i / sr))))
                    if offbeat_pos > 0.0 and len(pattern) in (3, 4):
                        sub_start = int(round((beat_idx + offbeat_pos) * beat_sec * sr))
                        if sub_start < len(frames):
                            sub_len = min(int(sr * 0.10), len(frames) - sub_start)
                            for i in range(sub_len):
                                env = math.exp(-i / (sr * 0.025))
                                frames[sub_start + i] = int(max(-32000, min(32000, 12000 * amp * env * math.sin(2.0 * math.pi * freq_hz * 1.5 * i / sr))))
            with wave.open(str(path), 'wb') as wf:
                wf.setparams((1, 2, sr, 0, 'NONE', ''))
                wf.writeframes(struct.pack(f'<{len(frames)}h', *frames))

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            samples_dir = root / 'Samples'
            samples_dir.mkdir(parents=True, exist_ok=True)
            (root / 'BeatOS' / 'data').mkdir(parents=True, exist_ok=True)

            # 2. Synthetic 3/4 Bolero-Vals at 90 BPM -> adapt to Lo-Fi 84 BPM
            bolero_waltz = samples_dir / 'Requinto_Bolero_Melodia.wav'
            _synth_pulse_wav(bolero_waltz, beat_sec=60.0 / 90.0, pattern=[1.0, 0.42, 0.42], freq_hz=261.63, offbeat_pos=0.0)
            rhy_bol = hkb.analyze_rhythmic_pattern_and_hiphop_adaptation(bolero_waltz, style_hint='Bolero a Lo-Fi 84')
            self.assertEqual(rhy_bol['rhythm_analysis']['time_signature'], '3/4')
            self.assertAlmostEqual(rhy_bol['rhythm_analysis']['source_bpm'], 90.0, delta=4.0)
            self.assertEqual(rhy_bol['hiphop_adaptation']['target_bpm'], 84.0)
            self.assertLess(rhy_bol['hiphop_adaptation']['repitch_semitones'], 0)
            self.assertIn('3/4', rhy_bol['hiphop_adaptation']['meter_bridge_note'])
            self.assertIn('clave_pattern', rhy_bol['rhythm_analysis'])
            self.assertIn('timbre_label', rhy_bol['rhythm_analysis'])
            self.assertEqual(rhy_bol['hiphop_adaptation']['recommended_chop_mode'], 'phrase_3_4_to_4_4')
            self.assertGreaterEqual(len(rhy_bol['hiphop_adaptation']['adaptation_profiles']), 3)
            self.assertIn('kick_steps', rhy_bol['hiphop_adaptation']['sequencer_guide'])
            self.assertTrue(rhy_bol['hiphop_adaptation']['harmonic_info'].get('original_note'))
            self.assertTrue(rhy_bol['hiphop_adaptation']['harmonic_info'].get('transposed_note'))

            # 2b. Generic filename 3/4 warm cut infers acoustic style automatically
            generic_cut = samples_dir / 'Sample_Cut_01.wav'
            _synth_pulse_wav(generic_cut, beat_sec=60.0 / 88.0, pattern=[1.0, 0.38, 0.38], freq_hz=261.63, offbeat_pos=0.0)
            rhy_gen = hkb.analyze_rhythmic_pattern_and_hiphop_adaptation(generic_cut)
            self.assertEqual(rhy_gen['rhythm_analysis']['time_signature'], '3/4')
            self.assertNotEqual(rhy_gen['rhythm_analysis']['acoustic_style_id'], 'standard')

            # 3. Synthetic 6/8 Slow Soul Ballad at 68 BPM
            soul_68 = samples_dir / 'Vintage_Soul_Ballad_6_8.wav'
            _synth_pulse_wav(soul_68, beat_sec=60.0 / 68.0, pattern=[1.0, 0.35, 0.35], freq_hz=196.0, offbeat_pos=0.0)
            rhy_soul = hkb.analyze_rhythmic_pattern_and_hiphop_adaptation(soul_68, style_hint='Soul Boom Bap 86')
            self.assertEqual(rhy_soul['rhythm_analysis']['time_signature'], '6/8')
            self.assertEqual(rhy_soul['hiphop_adaptation']['target_bpm'], 86.0)

            # 4. Synthetic 4/4 Swing Jazz Loop at 96 BPM (swing offbeats at 0.65)
            jazz_swing = samples_dir / 'Cool_Jazz_Piano_Chord_Loop.wav'
            _synth_pulse_wav(jazz_swing, beat_sec=60.0 / 96.0, pattern=[1.0, 0.55, 0.78, 0.55], freq_hz=293.66, offbeat_pos=0.65)
            rhy_jazz = hkb.analyze_rhythmic_pattern_and_hiphop_adaptation(jazz_swing, style_hint='Jazz Hop 88')
            self.assertEqual(rhy_jazz['rhythm_analysis']['time_signature'], '4/4')
            self.assertGreaterEqual(rhy_jazz['rhythm_analysis']['swing_pct'], 57.0)
            self.assertEqual(rhy_jazz['hiphop_adaptation']['target_bpm'], 88.0)

            # 4b. Synthetic 12/8 Oldies Doo-Wop / Lowrider Sweet Soul Loop at 72 BPM -> adapt to Lo-Fi 84 BPM
            oldies_12_8 = samples_dir / 'Lowrider_Oldies_Doo_Wop_12_8.wav'
            _synth_pulse_wav(oldies_12_8, beat_sec=60.0 / 72.0, pattern=[1.0, 0.45, 0.72, 0.45], freq_hz=440.0, offbeat_pos=0.667)
            rhy_oldies = hkb.analyze_rhythmic_pattern_and_hiphop_adaptation(oldies_12_8, style_hint='Oldies Lowrider 84')
            self.assertEqual(rhy_oldies['rhythm_analysis']['time_signature'], '12/8')
            self.assertEqual(rhy_oldies['rhythm_analysis']['timbre_profile'], 'vintage_oldies')
            self.assertIn('12/8', rhy_oldies['rhythm_analysis']['clave_pattern'])
            self.assertEqual(rhy_oldies['hiphop_adaptation']['recommended_chop_mode'], 'phrase_3_4_to_4_4')
            self.assertEqual(rhy_oldies['hiphop_adaptation']['target_bpm'], 84.0)
            self.assertIn('12/8', rhy_oldies['hiphop_adaptation']['meter_bridge_note'])
            oldies_chop = hkb.autochop_sample_to_16_pads(oldies_12_8, output_root=root, max_slices=16, kit_name='Oldies_Chops')
            self.assertGreaterEqual(oldies_chop['slices_count'], 8)
            self.assertEqual(oldies_chop['applied_chop_mode'], 'phrase_3_4_to_4_4')
            self.assertEqual(oldies_chop['pads'][0]['sound_type'], 'MELODIC_LOOP')

            # 5. Test live endpoints /api/cerebro_analyze and /api/cerebro_autochop
        with self.server() as (url, parent):
            srv_root = parent / 'library'
            srv_samples = srv_root / 'Samples'
            srv_samples.mkdir(parents=True, exist_ok=True)
            bol_srv = srv_samples / 'Requinto_Bolero_Melodia.wav'
            _synth_pulse_wav(bol_srv, beat_sec=60.0 / 90.0, pattern=[1.0, 0.42, 0.42], freq_hz=261.63, offbeat_pos=0.0)

            status_a, raw_a = self.request(
                url + '/api/cerebro_analyze',
                method='POST',
                headers={'Origin': url, 'Content-Type': 'application/json'},
                data=json.dumps({
                    'kit_name': 'Bolero_LoFi_Session',
                    'pads': [{'pad': 1, 'sample_name': 'Requinto_Bolero_Melodia', 'rel_path': 'Samples/Requinto_Bolero_Melodia.wav', 'sound_type': 'MELODIC_LOOP'}],
                }).encode('utf-8'),
            )
            self.assertEqual(status_a, 200, raw_a)
            data_a = json.loads(raw_a.decode('utf-8'))
            self.assertEqual(data_a['style_id'], 'bolero')
            self.assertIsNotNone(data_a.get('rhythm_analysis'))
            self.assertIsNotNone(data_a.get('hiphop_adaptation'))
            self.assertEqual(data_a['rhythm_analysis']['time_signature'], '3/4')

            status_c, raw_c = self.request(
                url + '/api/cerebro_autochop',
                method='POST',
                headers={'Origin': url, 'Content-Type': 'application/json'},
                data=json.dumps({
                    'rel_path': 'Samples/Requinto_Bolero_Melodia.wav',
                    'max_slices': 16,
                    'kit_name': 'Bolero_Chops',
                    'style_hint': 'Bolero a Lo-Fi 84',
                }).encode('utf-8'),
            )
            self.assertEqual(status_c, 200, raw_c)
            data_c = json.loads(raw_c.decode('utf-8'))
            self.assertTrue(data_c['success'])
            self.assertGreaterEqual(data_c['slices_count'], 8)
            self.assertEqual(data_c['recommended_bpm'], 84.0)
            self.assertEqual(data_c['rhythm_analysis']['time_signature'], '3/4')
            self.assertEqual(data_c['hiphop_adaptation']['target_bpm'], 84.0)
            self.assertTrue(all(p['mute_group'] == 6 for p in data_c['pads']))
            self.assertTrue(all(p['sound_type'] == 'MELODIC_LOOP' for p in data_c['pads']))
            self.assertTrue(all(p.get('slice_role') for p in data_c['pads']))

            # 6. Explicit phrase_3_4_to_4_4 chop_mode + boombap_classic adapt_mode
            status_c2, raw_c2 = self.request(
                url + '/api/cerebro_autochop',
                method='POST',
                headers={'Origin': url, 'Content-Type': 'application/json'},
                data=json.dumps({
                    'rel_path': 'Samples/Requinto_Bolero_Melodia.wav',
                    'max_slices': 12,
                    'kit_name': 'Bolero_BoomBap_Bridge',
                    'chop_mode': 'phrase_3_4_to_4_4',
                    'adapt_mode': 'boombap_classic',
                }).encode('utf-8'),
            )
            self.assertEqual(status_c2, 200, raw_c2)
            data_c2 = json.loads(raw_c2.decode('utf-8'))
            self.assertTrue(data_c2['success'])
            self.assertEqual(data_c2['applied_chop_mode'], 'phrase_3_4_to_4_4')
            self.assertEqual(data_c2['recommended_bpm'], 90.0)
            self.assertEqual(data_c2['hiphop_adaptation']['target_bpm'], 90.0)
            self.assertTrue(all(p.get('slice_role') for p in data_c2['pads']))

            # 7. Oldies 12/8 endpoint fallback & rack analysis check
            status_o, raw_o = self.request(
                url + '/api/cerebro_analyze',
                method='POST',
                headers={'Origin': url, 'Content-Type': 'application/json'},
                data=json.dumps({
                    'kit_name': 'Lowrider_Oldies_Doo_Wop_12_8',
                    'prompt': 'Oldies 12/8 Doo-Wop a Lo-Fi',
                    'pads': [{'pad': 1, 'sample_name': 'Sweet_Soul_Oldies_50s', 'sound_type': 'MELODIC_LOOP'}],
                }).encode('utf-8'),
            )
            self.assertEqual(status_o, 200, raw_o)
            data_o = json.loads(raw_o.decode('utf-8'))
            self.assertEqual(data_o['style_id'], 'oldies')
            self.assertIsNotNone(data_o.get('rhythm_analysis'))
            self.assertEqual(data_o['rhythm_analysis']['time_signature'], '12/8')
            self.assertEqual(data_o['hiphop_adaptation']['target_bpm'], 84.0)
            self.assertEqual(data_o['hiphop_adaptation']['recommended_chop_mode'], 'phrase_3_4_to_4_4')

            # 8. Melodee v0.4.0 GET/POST /api/melodee_config
            (srv_root / 'autorun').mkdir(exist_ok=True)
            (srv_root / 'autorun' / 'mpcqol.so').write_bytes(b'QOL')
            (srv_root / 'Melodee').mkdir(exist_ok=True)
            (srv_root / 'Melodee' / 'settings').write_text('start=/media/sd/Melodee/Projects/Demo.mldp\nfeatures=1\n', encoding='utf-8')
            status_m_get, raw_m_get = self.request(url + '/api/melodee_config', headers={'Origin': url})
            self.assertEqual(status_m_get, 200, raw_m_get)
            data_m_get = json.loads(raw_m_get.decode('utf-8'))
            self.assertTrue(data_m_get['success'])
            self.assertEqual(data_m_get['active_boot'], 'sampqol')
            self.assertTrue(data_m_get['sampqol_detected'])
            self.assertFalse(data_m_get['melodee_detected'])
            self.assertEqual(data_m_get['start_project'], '/media/sd/Melodee/Projects/Demo.mldp')

            status_m_post, raw_m_post = self.request(
                url + '/api/melodee_config',
                method='POST',
                headers={'Origin': url, 'Content-Type': 'application/json'},
                data=json.dumps({'settings': {'audio_rate': 48000, 'stems_best': 0, 'slice_play': 2}}).encode('utf-8'),
            )
            self.assertEqual(status_m_post, 200, raw_m_post)
            data_m_post = json.loads(raw_m_post.decode('utf-8'))
            self.assertEqual(data_m_post['raw_values']['audio_rate'], 48000)
            self.assertEqual(data_m_post['raw_values']['stems_best'], 0)
            self.assertEqual(data_m_post['raw_values']['slice_play'], 2)
            self.assertTrue((srv_root / 'Melodee' / 'settings.bak-beatos').is_file())
            self.assertIn('start=/media/sd/Melodee/Projects/Demo.mldp', (srv_root / 'Melodee' / 'settings').read_text(encoding='utf-8'))

            st_act, rw_act = self.request(
                url + '/api/melodee_config',
                method='POST',
                headers={'Origin': url, 'Content-Type': 'application/json'},
                data=json.dumps({'action': 'init_melodee_tree', 'start_project': '/media/sd/Melodee/Projects/New.mldp'}).encode('utf-8'),
            )
            self.assertEqual(st_act, 200, rw_act)
            st_sp, rw_sp = self.request(
                url + '/api/melodee_config',
                method='POST',
                headers={'Origin': url, 'Content-Type': 'application/json'},
                data=json.dumps({'start_project': '/media/sd/Melodee/Projects/New.mldp'}).encode('utf-8'),
            )
            self.assertEqual(st_sp, 200, rw_sp)
            self.assertEqual(json.loads(rw_sp.decode('utf-8'))['start_project'], '/media/sd/Melodee/Projects/New.mldp')

            status_m_bad, raw_m_bad = self.request(
                url + '/api/melodee_config',
                method='POST',
                headers={'Origin': url, 'Content-Type': 'application/json', 'X-BeatOS-Language': 'en'},
                data=json.dumps({'preset': 'unknown_preset'}).encode('utf-8'),
            )
            self.assertEqual(status_m_bad, 400, raw_m_bad)
            data_m_bad = json.loads(raw_m_bad.decode('utf-8'))
            self.assertIn('Unknown Melodee preset', data_m_bad['error'])

            for bad_payload, expected_err in (
                ([], 'Expected a JSON object'),
                ({'settings': 'bad'}, "The 'settings' parameter must be a JSON object"),
                ({'settings': {'features': True}}, 'Invalid value'),
            ):
                st_b, rw_b = self.request(
                    url + '/api/melodee_config',
                    method='POST',
                    headers={'Origin': url, 'Content-Type': 'application/json', 'X-BeatOS-Language': 'en'},
                    data=json.dumps(bad_payload).encode('utf-8'),
                )
                self.assertEqual(st_b, 400, rw_b)
                self.assertIn(expected_err, json.loads(rw_b.decode('utf-8'))['error'])

            # 9. Jerarquía de análisis rack: batería seca no devuelve C falso, loop melódico manda y 808 confirma
            import math
            sr_t = 22050
            h_dir = srv_root / 'Hierarchical_Test'
            h_dir.mkdir(exist_ok=True)

            def _mk_wav(fp: Path, vals):
                with wave.open(str(fp), 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sr_t)
                    cl = [max(-32767, min(32767, int(v))) for v in vals]
                    wf.writeframes(struct.pack(f'<{len(cl)}h', *cl))

            _mk_wav(
                h_dir / 'Kick_Dry_Punch.wav',
                [15000.0 * math.exp(-i / 650.0) * math.sin(2.0 * math.pi * (145.0 * math.exp(-i / 500.0) + 45.0) * i / sr_t) for i in range(int(sr_t * 0.14))],
            )
            _mk_wav(
                h_dir / 'Melodic_Phrase.wav',
                [
                    15000.0 * math.exp(-((i / float(sr_t)) % (60.0 / 90.0)) * 5.0)
                    * (math.sin(2.0 * math.pi * 220.0 * i / sr_t) + math.sin(2.0 * math.pi * 261.63 * i / sr_t) + math.sin(2.0 * math.pi * 329.63 * i / sr_t)) / 3.0
                    for i in range(int(sr_t * 3.0))
                ],
            )
            _mk_wav(
                h_dir / 'Bass_808_A.wav',
                [17000.0 * math.exp(-i / 14000.0) * math.sin(2.0 * math.pi * 55.0 * i / sr_t) for i in range(int(sr_t * 0.8))],
            )

            st_dry, rw_dry = self.request(
                url + '/api/cerebro_analyze',
                method='POST',
                timeout=30,
                headers={'Origin': url, 'Content-Type': 'application/json'},
                data=json.dumps({
                    'kit_name': 'BoomBap Dry Drum Kit',
                    'tempo': 120.0,
                    'pads': [{'pad': 1, 'sample_name': 'Kick_Dry_Punch', 'rel_path': 'Hierarchical_Test/Kick_Dry_Punch.wav'}],
                }).encode('utf-8'),
            )
            self.assertEqual(st_dry, 200, rw_dry)
            d_dry = json.loads(rw_dry.decode('utf-8'))
            self.assertIn(d_dry['anchor_key'], ('Percusión / Atonal', 'Percussion'))
            self.assertEqual(d_dry['key_source'], 'atonal_drums')
            self.assertEqual(d_dry['recommended_bpm'], 90.0)

            st_mel, rw_mel = self.request(
                url + '/api/cerebro_analyze',
                method='POST',
                timeout=30,
                headers={'Origin': url, 'Content-Type': 'application/json'},
                data=json.dumps({
                    'kit_name': 'Mixed Melodic Kit',
                    'tempo': 120.0,
                    'pads': [
                        {'pad': 1, 'sample_name': 'Kick_Dry_Punch', 'rel_path': 'Hierarchical_Test/Kick_Dry_Punch.wav'},
                        {'pad': 2, 'sample_name': 'Bass_808_A', 'rel_path': 'Hierarchical_Test/Bass_808_A.wav'},
                        {'pad': 3, 'sample_name': 'Melodic_Phrase', 'rel_path': 'Hierarchical_Test/Melodic_Phrase.wav'},
                    ],
                }).encode('utf-8'),
            )
            self.assertEqual(st_mel, 200, rw_mel)
            d_mel = json.loads(rw_mel.decode('utf-8'))
            self.assertEqual(d_mel['key_source'], 'melodic_loop')
            self.assertEqual(d_mel['anchor_key'], 'A Min')
            self.assertTrue(d_mel['confirmed_by_drums'])
            self.assertLessEqual(abs(float(d_mel['recommended_bpm']) - 90.0), 2.0)

            # 10. POST /api/update_expansion: editar título, descripción y portada defectuosa en vivo
            import base64
            exp_u = srv_root / 'Expansions' / 'Broken_Cover_Pack'
            exp_u.mkdir(parents=True, exist_ok=True)
            (exp_u / 'Artwork.png').write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 62)
            (exp_u / 'Expansion.xml').write_text(
                '<?xml version="1.0" encoding="utf-8"?><expansion version="2.0.0.1"><title>Broken Pack</title><manufacturer>Old</manufacturer><img>Artwork.png</img></expansion>',
                encoding='utf-8',
            )
            st_upd, rw_upd = self.request(
                url + '/api/update_expansion',
                method='POST',
                headers={'Origin': url, 'Content-Type': 'application/json'},
                data=json.dumps({
                    'expansion_path': 'Expansions/Broken_Cover_Pack',
                    'title': 'Fixed Bolero Pack',
                    'manufacturer': 'Astro1Deep',
                    'description': 'Nueva portada',
                    'regenerate_cover': True,
                }).encode('utf-8'),
            )
            self.assertEqual(st_upd, 200, rw_upd)
            d_upd = json.loads(rw_upd.decode('utf-8'))
            self.assertTrue(d_upd['success'])
            self.assertEqual(d_upd['title'], 'Fixed Bolero Pack')
            self.assertGreater((exp_u / 'Artwork.png').stat().st_size, 2000)

            st_bad_img, _ = self.request(
                url + '/api/update_expansion',
                method='POST',
                headers={'Origin': url, 'Content-Type': 'application/json'},
                data=json.dumps({
                    'expansion_path': 'Expansions/Broken_Cover_Pack',
                    'title': 'Still Valid',
                    'cover_data_url': 'data:image/png;base64,' + base64.b64encode(b'BAD_IMAGE').decode('ascii'),
                }).encode('utf-8'),
            )
            self.assertEqual(st_bad_img, 400)

    def test_cerebro_harmonic_clashes_acoustic_similarity_and_mlx_copilot_resilience(self):
        import io
        import json
        import math
        import os
        import sqlite3
        import unittest.mock as mock
        import urllib.request

        with self.server() as (url, parent):
            srv_root = parent / 'library'
            samples_dir = srv_root / 'Samples'
            samples_dir.mkdir(parents=True, exist_ok=True)
            db_dir = srv_root / 'BeatOS' / 'data'
            db_dir.mkdir(parents=True, exist_ok=True)
            sr = 22050

            def _tone_wav(path: Path, freq_hz: float, dur_s: float = 0.6):
                n = int(sr * dur_s)
                pcm = [int(22000 * math.exp(-i / (sr * 0.25)) * math.sin(2.0 * math.pi * freq_hz * i / sr)) for i in range(n)]
                with wave.open(str(path), 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sr)
                    wf.writeframes(struct.pack(f'<{len(pcm)}h', *pcm))

            # Loop en C Min (Cm chord / phrase >= 2s) + 808 chocante en F#2 (~92.5 Hz)
            loop_cm = samples_dir / 'Bolero_Guitar_Cm_84BPM.wav'
            n_loop = int(sr * 2.2)
            loop_pcm = [
                int(16000 * (0.5 * math.sin(2.0 * math.pi * 261.63 * i / sr) + 0.35 * math.sin(2.0 * math.pi * 311.13 * i / sr) + 0.3 * math.sin(2.0 * math.pi * 392.0 * i / sr)))
                for i in range(n_loop)
            ]
            with wave.open(str(loop_cm), 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                wf.writeframes(struct.pack(f'<{len(loop_pcm)}h', *loop_pcm))

            bass_fs = samples_dir / '808_Sub_F#.wav'
            _tone_wav(bass_fs, 92.50, dur_s=0.9)

            old_dis = os.environ.get('BEATOS_DISABLE_MLX_LLM')
            os.environ['BEATOS_DISABLE_MLX_LLM'] = '1'
            try:
                st_a, rw_a = self.request(
                    url + '/api/cerebro_analyze',
                    method='POST',
                    headers={'Origin': url, 'Content-Type': 'application/json'},
                    data=json.dumps({
                        'kit_name': 'Bolero_Harmonic_Test',
                        'pads': [
                            {'pad': 1, 'sample_name': 'Bolero_Guitar_Cm_84BPM', 'rel_path': 'Samples/Bolero_Guitar_Cm_84BPM.wav', 'sound_type': 'MELODIC_LOOP'},
                            {'pad': 2, 'sample_name': '808_Sub_F#', 'rel_path': 'Samples/808_Sub_F#.wav', 'sound_type': 'BASS_808'},
                        ],
                    }).encode('utf-8'),
                )
            finally:
                if old_dis is None:
                    os.environ.pop('BEATOS_DISABLE_MLX_LLM', None)
                else:
                    os.environ['BEATOS_DISABLE_MLX_LLM'] = old_dis

            self.assertEqual(st_a, 200, rw_a)
            d_a = json.loads(rw_a.decode('utf-8'))
            self.assertEqual(d_a['anchor_camelot'], '5A')
            self.assertTrue(len(d_a.get('harmonic_clashes', [])) >= 1)
            self.assertFalse(d_a['mlx_copilot']['used_llm'])
            self.assertIn('chop_plan', d_a['mlx_copilot']['plan'])

            # Test similitud acústica PCM real sobre kicks de idéntico tamaño en bytes
            kick_sub_a = samples_dir / 'Kick_Target_Sub.wav'
            kick_sub_b = samples_dir / 'Kick_Twin_Sub.wav'
            kick_click_c = samples_dir / 'Kick_Click_3kHz.wav'
            _tone_wav(kick_sub_a, 55.0, dur_s=0.4)
            _tone_wav(kick_sub_b, 58.0, dur_s=0.4)
            _tone_wav(kick_click_c, 3400.0, dur_s=0.4)

            conn = sqlite3.connect(str(db_dir / 'mpc_sample.db'))
            conn.execute('''CREATE TABLE IF NOT EXISTS samples (
                filename TEXT, rel_path TEXT, sound_type TEXT, sample_format TEXT,
                sub_pack TEXT, bpm REAL, musical_key TEXT, energy_level TEXT, size_mb REAL
            )''')
            rows = [
                ('Kick_Target_Sub.wav', 'Samples/Kick_Target_Sub.wav', 'KICK', 'ONE_SHOT', 'Test', 0.0, '', 'SUB', 0.02),
                ('Kick_Twin_Sub.wav', 'Samples/Kick_Twin_Sub.wav', 'KICK', 'ONE_SHOT', 'Test', 0.0, '', 'SUB', 0.02),
                ('Kick_Click_3kHz.wav', 'Samples/Kick_Click_3kHz.wav', 'KICK', 'ONE_SHOT', 'Test', 0.0, '', 'SUB', 0.02),
            ]
            conn.executemany('INSERT INTO samples VALUES (?,?,?,?,?,?,?,?,?)', rows)
            conn.commit()
            conn.close()

            st_sim, rw_sim = self.request(
                url + '/api/cerebro_similar_samples',
                method='POST',
                headers={'Origin': url, 'Content-Type': 'application/json'},
                data=json.dumps({'rel_path': 'Samples/Kick_Target_Sub.wav', 'sound_type': 'KICK', 'limit': 4}).encode('utf-8'),
            )
            self.assertEqual(st_sim, 200, rw_sim)
            d_sim = json.loads(rw_sim.decode('utf-8'))
            self.assertTrue(d_sim.get('acoustic_fingerprinting'))
            self.assertEqual(d_sim['results'][0]['filename'], 'Kick_Twin_Sub.wav')
            self.assertGreater(d_sim['results'][0]['similarity'], d_sim['results'][1]['similarity'])

            # Test MLX Copilot parsing con servidor MLX mockeado y sin fuga ante JSON inválido
            import serve_mpc as sm

            class _FakeResp:
                def __init__(self, body_bytes):
                    self._buf = io.BytesIO(body_bytes)
                def read(self):
                    return self._buf.read()
                def __enter__(self):
                    return self
                def __exit__(self, *a):
                    return False

            def _fake_urlopen(req, timeout=2.0):
                u = req.full_url if hasattr(req, 'full_url') else str(req)
                if u.endswith('/v1/models'):
                    return _FakeResp(json.dumps({'data': [{'id': 'lukey03/Qwen3.5-9B-abliterated-MLX-4bit'}]}).encode('utf-8'))
                return _FakeResp(json.dumps({
                    'choices': [{'message': {'content': '{"chop_plan":"Corta en negras M6","mix_plan":"HPF 110Hz","sequencer_tip":"Swing 58%","creative_flip":"Usa 3/4 puente"}'}}]
                }).encode('utf-8'))

            with mock.patch.object(sm, '_probe_local_port', return_value=True), \
                 mock.patch.object(urllib.request, 'urlopen', side_effect=_fake_urlopen):
                cop = sm.query_cerebro_mlx_advisor(d_a, allow_llm=True)
                self.assertTrue(cop['used_llm'])
                self.assertIn('Qwen3.5', cop['model'])
                self.assertEqual(cop['plan']['chop_plan'], 'Corta en negras M6')

            with mock.patch.object(sm, '_probe_local_port', return_value=True), \
                 mock.patch.object(urllib.request, 'urlopen', return_value=_FakeResp(b'NOT_JSON')):
                cop_fb = sm.query_cerebro_mlx_advisor(d_a, allow_llm=True)
                self.assertFalse(cop_fb['used_llm'])
                self.assertTrue(bool(cop_fb['plan']['chop_plan']))

            # Test reglas de audio/MIR: formant_risk (>±4.5 st) y contexto enriquecido MLX
            captured_bodies = []

            def _capture_urlopen(req, timeout=2.0):
                u = req.full_url if hasattr(req, 'full_url') else str(req)
                if u.endswith('/v1/models'):
                    return _FakeResp(json.dumps({'data': [{'id': 'lukey03/Qwen3.5-9B-abliterated-MLX-4bit'}]}).encode('utf-8'))
                captured_bodies.append(json.loads(req.data.decode('utf-8')))
                return _FakeResp(json.dumps({
                    'choices': [{'message': {'content': '{"chop_plan":"Cruces +-5ms","mix_plan":"HPF 110Hz -0.8dBFS","sequencer_tip":"Swing 56%","creative_flip":"Warp 0 st por formantes"}'}}]
                }).encode('utf-8'))

            tele_formant = {
                'detected_style': 'Bolero Vintage',
                'recommended_bpm': 84.0,
                'anchor_key': 'Am (8A)',
                'harmonic_clashes': [{'sample_name': 'Bass_G', 'semitone_fix': -2}],
                'mix_advice': [],
                'pad_count': 16,
                'rhythm_analysis': {
                    'time_signature': '3/4',
                    'source_bpm': 115.0,
                    'swing_pct': 56,
                    'is_rubato': False,
                    'is_drumless': True,
                    'sub_energy_ratio': 0.08,
                    'mid_warmth_ratio': 0.62,
                    'high_air_ratio': 0.14,
                },
                'hiphop_adaptation': {
                    'target_bpm': 84.0,
                    'repitch_semitones': -5.4,
                    'recommended_chop_mode': 'phrase_3_4_to_4_4',
                    'sequencer_guide': {'highpass_hz_cut': 110, 'chop_trigger_steps': [1, 5, 9, 13]},
                },
            }
            cop_det_formant = sm.query_cerebro_mlx_advisor(tele_formant, allow_llm=False)
            self.assertFalse(cop_det_formant['used_llm'])
            self.assertIn('Warp', cop_det_formant['plan']['creative_flip'])
            self.assertIn('formant', cop_det_formant['plan']['creative_flip'].lower())
            self.assertIn('220', cop_det_formant['plan']['mix_plan'])

            with mock.patch.object(sm, '_probe_local_port', return_value=True), \
                 mock.patch.object(urllib.request, 'urlopen', side_effect=_capture_urlopen):
                cop_mlx = sm.query_cerebro_mlx_advisor(tele_formant, allow_llm=True)
                self.assertTrue(cop_mlx['used_llm'])
                self.assertTrue(len(captured_bodies) == 1)
                sys_msg = captured_bodies[0]['messages'][0]['content']
                usr_ctx = json.loads(captured_bodies[0]['messages'][1]['content'])
                self.assertTrue(usr_ctx['formant_risk'])
                self.assertEqual(usr_ctx['clash_fix_st'], -2)
                self.assertIn('formant_risk', sys_msg)
                self.assertIn('-0.80 dBFS', sys_msg)

    def test_cerebro_audio_knowledge_808_and_headroom_audit(self):
        import json
        import math
        import struct
        import wave

        with self.server() as (url, parent):
            srv_root = parent / 'library'
            samples_dir = srv_root / 'Samples'
            samples_dir.mkdir(parents=True, exist_ok=True)
            sr = 44100

            # Loop anclado explícitamente en F Maj con pico casi en 0 dBFS (-0.1 dBFS -> dispara headroom_audit warning)
            loop_wav = samples_dir / 'Soul_Keys_F_Maj.wav'
            amp_hot = int(32767.0 * (10.0 ** (-0.1 / 20.0)))
            pcm_loop = [int(amp_hot * math.sin(2.0 * math.pi * 349.228 * (i / sr))) for i in range(int(sr * 2.2))]
            with wave.open(str(loop_wav), 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                wf.writeframes(struct.pack(f'<{len(pcm_loop)}h', *pcm_loop))

            # 808 en B1 real (~61.74 Hz) -> frente a ancla F (pc=5) B (pc=11) dista exactamente ±6 st (NO +5 st)
            bass_wav = samples_dir / 'Bass_808_Test.wav'
            pcm_bass = [int(18000.0 * math.sin(2.0 * math.pi * 61.7354 * (i / sr))) for i in range(int(sr * 1.1))]
            with wave.open(str(bass_wav), 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                wf.writeframes(struct.pack(f'<{len(pcm_bass)}h', *pcm_bass))

            status_a, raw_a = self.request(
                url + '/api/cerebro_analyze',
                method='POST',
                headers={'Origin': url, 'Content-Type': 'application/json'},
                data=json.dumps({
                    'kit_name': 'Headroom_And_808_Audit',
                    'use_llm': False,
                    'pads': [
                        {'pad': 1, 'sample_name': 'Soul_Keys_F_Maj', 'rel_path': 'Samples/Soul_Keys_F_Maj.wav', 'sound_type': 'MELODIC_LOOP'},
                        {'pad': 13, 'sample_name': 'Bass_808_Test', 'rel_path': 'Samples/Bass_808_Test.wav', 'sound_type': 'BASS_808'},
                    ],
                }).encode('utf-8'),
            )
            self.assertEqual(status_a, 200, raw_a)
            res_a = json.loads(raw_a.decode('utf-8'))
            self.assertEqual(res_a['headroom_audit']['status'], 'warning')
            self.assertGreaterEqual(len(res_a['headroom_audit']['clipping_pads']), 1)
            self.assertGreaterEqual(len(res_a['tuning_adjustments']), 1)
            adj808 = res_a['tuning_adjustments'][0]
            self.assertEqual(adj808['detected_note'], 'B1')
            self.assertEqual(abs(adj808['recommended_tune']), 6)
            self.assertIsInstance(res_a.get('audio_knowledge_hits'), list)
            self.assertIn('rag_rules_used', res_a['mlx_copilot'])

            # Endpoint /api/cerebro_audio_knowledge (GET y POST)
            st_k_get, raw_k_get = self.request(
                url + '/api/cerebro_audio_knowledge?topic=anticlipping&semantic=0',
                headers={'Origin': url},
            )
            self.assertEqual(st_k_get, 200, raw_k_get)
            d_k_get = json.loads(raw_k_get.decode('utf-8'))
            self.assertTrue(d_k_get['success'])
            self.assertEqual(d_k_get['matched_cards'][0]['id'], 'anticlipping')

            st_k_post, raw_k_post = self.request(
                url + '/api/cerebro_audio_knowledge',
                method='POST',
                headers={'Origin': url, 'Content-Type': 'application/json'},
                data=json.dumps({'query': 'formantes warp repitch 3/4', 'semantic': False, 'context': res_a}).encode('utf-8'),
            )
            self.assertEqual(st_k_post, 200, raw_k_post)
            d_k_post = json.loads(raw_k_post.decode('utf-8'))
            self.assertTrue(d_k_post['success'])
            self.assertGreaterEqual(len(d_k_post['cards']), 6)

    def test_po_backup_external_library_management_and_full_dsp_inspection(self):
        import io
        import json
        import math
        import shutil
        import struct
        import wave
        import urllib.parse
        from hardware_kit_builder import inspect_po33_backup

        def make_stereo_wav(frames_list, fs=44100):
            buf = io.BytesIO()
            with wave.open(buf, 'wb') as w:
                w.setparams((2, 2, fs, 0, 'NONE', ''))
                raw = b''.join(struct.pack('<hh', l, r) for l, r in frames_list)
                w.writeframes(raw)
            return buf.getvalue()

        with self.server() as (url, parent):
            # 1. DSP inspection complete beyond 4s: silent, dual-mono, and delayed stereo signal (>7s)
            silent_wav = parent / 'silent.wav'
            silent_wav.write_bytes(make_stereo_wav([(0, 0)] * 44100 * 6))
            s_info = inspect_po33_backup(silent_wav)
            self.assertTrue(s_info['is_silent'])
            self.assertFalse(s_info['signal_usable'])
            self.assertEqual(s_info['status'], 'WARNING_SILENT_RECORDING')

            mono_frames = [(int(9000 * math.sin(2 * math.pi * 1000 * i / 44100)),
                            int(9000 * math.sin(2 * math.pi * 1000 * i / 44100))) for i in range(44100 * 2)]
            mono_wav = parent / 'dualmono.wav'
            mono_wav.write_bytes(make_stereo_wav(mono_frames))
            m_info = inspect_po33_backup(mono_wav)
            self.assertTrue(m_info['is_dual_mono'])
            self.assertFalse(m_info['signal_usable'])
            self.assertEqual(m_info['status'], 'WARNING_MONO_DUPLICATED')

            delayed_frames = [(0, 0)] * (44100 * 7) + [
                (int(11000 * math.sin(2 * math.pi * 440 * i / 44100)),
                 int(11000 * math.cos(2 * math.pi * 660 * i / 44100))) for i in range(44100 * 2)
            ]
            delayed_wav = parent / 'delayed_stereo.wav'
            delayed_wav.write_bytes(make_stereo_wav(delayed_frames))
            d_info = inspect_po33_backup(delayed_wav)
            self.assertFalse(d_info['is_silent'])
            self.assertFalse(d_info['is_dual_mono'])
            self.assertTrue(d_info['signal_usable'])
            self.assertGreaterEqual(d_info['signal_start_sec'], 6.9)
            self.assertGreater(d_info['peak_dbfs'], -20.0)

            # 2. Configure external library folder + verify config endpoint & private file HTTP 403
            st_cfg, raw_cfg = self.request(url + '/api/po_backup_config', headers={'Origin': url})
            self.assertEqual(st_cfg, 200)
            self.assertEqual(json.loads(raw_cfg)['config']['storage_mode'], 'default')

            ext_dir = parent / 'external_po_lib'
            st_save, raw_save = self.request(
                url + '/api/po_backup_config',
                method='POST',
                headers={'Content-Type': 'application/json', 'Origin': url},
                data=json.dumps({
                    'storage_mode': 'external',
                    'external_dir': str(ext_dir),
                    'create_if_missing': True,
                    'include_default_in_scan': True,
                    'include_legacy_dirs': False,
                }).encode('utf-8'),
            )
            self.assertEqual(st_save, 200, raw_save)
            saved_cfg = json.loads(raw_save)['config']
            self.assertEqual(saved_cfg['storage_mode'], 'external')
            self.assertTrue(saved_cfg['external_available'])
            self.assertEqual(self.request(url + '/BeatOS/config/po_backup_config.json')[0], 403)

            # 3. Upload directly to external storage, edit metadata/notes, copy to default, then delete default copy
            good_wav_bytes = make_stereo_wav([(1600, -1600), (-1600, 1600)] * 22050)
            st_up, raw_up = self.request(
                url + '/api/po33_backups?name=Ext_Take.wav&model=PO-33&project=External%20Beat&storage=external',
                data=good_wav_bytes,
                headers={'Content-Type': 'audio/wav', 'Origin': url},
            )
            self.assertEqual(st_up, 200, raw_up)
            ext_backup = json.loads(raw_up)['backup']
            self.assertEqual(ext_backup['storage_location'], 'external')
            self.assertTrue(Path(ext_backup['path']).is_relative_to(ext_dir.resolve()))

            st_upd, raw_upd = self.request(
                url + '/api/po_backup_update',
                method='POST',
                headers={'Content-Type': 'application/json', 'Origin': url},
                data=json.dumps({'file': ext_backup['path'], 'project': 'Live_PO33_Set', 'notes': '93 BPM stereo'}).encode('utf-8'),
            )
            self.assertEqual(st_upd, 200, raw_upd)
            upd_b = json.loads(raw_upd)['backup']
            self.assertEqual(upd_b['project'], 'Live_PO33_Set')
            self.assertEqual(upd_b['notes'], '93 BPM stereo')
            self.assertEqual(Path(ext_backup['path']).read_bytes(), good_wav_bytes)

            st_cp, raw_cp = self.request(
                url + '/api/po_backup_copy',
                method='POST',
                headers={'Content-Type': 'application/json', 'Origin': url},
                data=json.dumps({'file': ext_backup['path'], 'destination': 'default'}).encode('utf-8'),
            )
            self.assertEqual(st_cp, 200, raw_cp)
            cp_b = json.loads(raw_cp)['backup']
            self.assertEqual(cp_b['storage_location'], 'default')
            self.assertTrue(Path(cp_b['path']).is_relative_to((parent / 'library/BeatOS/data/po33_backups').resolve()))
            self.assertEqual(Path(cp_b['path']).read_bytes(), good_wav_bytes)

            inv = json.loads(self.request(url + '/api/po33_backups')[1])['backups']
            self.assertEqual(len(inv), 2)
            self.assertEqual({b['storage_location'] for b in inv}, {'external', 'default'})

            st_del, _ = self.request(
                url + '/api/po_backup_delete',
                method='POST',
                headers={'Content-Type': 'application/json', 'Origin': url},
                data=json.dumps({'file': cp_b['path']}).encode('utf-8'),
            )
            self.assertEqual(st_del, 200)
            self.assertFalse(Path(cp_b['path']).exists())
            self.assertFalse(Path(cp_b['path']).with_suffix('.po.json').exists())

            # 4. Safe fallback if external volume is disconnected before a default-mode recording upload
            shutil.rmtree(ext_dir)
            st_fb, raw_fb = self.request(
                url + '/api/po33_backups?name=Fallback.wav&model=PO-33&project=Fallback%20Take',
                data=good_wav_bytes,
                headers={'Content-Type': 'audio/wav', 'Origin': url},
            )
            self.assertEqual(st_fb, 200, raw_fb)
            fb_b = json.loads(raw_fb)['backup']
            self.assertTrue(fb_b['storage_fallback'])
            self.assertEqual(fb_b['storage_location'], 'default')
            self.assertTrue(Path(fb_b['path']).exists())

    def test_po_backup_include_default_false_excludes_default_dir(self):
        from hardware_kit_builder import po33_backup_dirs, save_po_backup_config
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'lib'
            ext = Path(tmp) / 'ext_po'
            root.mkdir()
            ext.mkdir()
            save_po_backup_config(
                root,
                {
                    'storage_mode': 'external',
                    'external_dir': str(ext),
                    'include_default_in_scan': False,
                    'include_legacy_dirs': False,
                },
            )
            dirs = [p.resolve() for p in po33_backup_dirs(root)]
            self.assertIn(ext.resolve(), dirs)
            self.assertNotIn((root / 'BeatOS/data/po33_backups').resolve(), dirs)

    def test_404_does_not_leak_host_path_and_preload_asset_path_works(self):
        with self.server() as (url, root):
            status_404, raw_404 = self.request(url + '/missing_ptax_probe.txt')
            self.assertEqual(status_404, 404)
            text_404 = raw_404.decode('utf-8', errors='replace')
            self.assertNotIn('Buscado en:', text_404)
            self.assertNotIn(str(root), text_404)

            status_asset, raw_asset = self.request(url + '/BeatOS/data/BeatOS/docs/assets/po33-capture-worklet.js')
            self.assertEqual(status_asset, 200)
            self.assertIn(b'AudioWorkletProcessor', raw_asset)

    def test_task_state_snapshot_is_isolated_under_lock(self):
        snap = serve_mpc._snapshot_task_state()
        snap['logs'].append('mutated-only-in-copy')
        self.assertNotIn('mutated-only-in-copy', serve_mpc.TASK_STATE['logs'])

    def test_import_external_sample_rejects_symlink_and_disambiguates_collision(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / 'card'
            ext_mount = base / 'ext_disk'
            (root / 'Custom_Kits').mkdir(parents=True)
            (ext_mount / 'dir_a').mkdir(parents=True)
            (ext_mount / 'dir_b').mkdir(parents=True)
            wav_a = ext_mount / 'dir_a' / 'Kick_01.wav'
            wav_b = ext_mount / 'dir_b' / 'Kick_01.wav'
            wav_a.write_bytes(b'RIFF\x10\x00\x00\x00WAVEfmt aaaa')
            wav_b.write_bytes(b'RIFF\x10\x00\x00\x00WAVEfmt bbbb')
            link = ext_mount / 'sym_kick.wav'
            link.symlink_to(wav_a)
            libs = [{'mount_path': str(ext_mount), 'is_active_root': False}]
            with patch.object(serve_mpc, 'discover_mounted_audio_libraries', return_value=libs):
                with self.assertRaises(ValueError):
                    serve_mpc.import_external_sample_to_library(str(root), {'external_full_path': str(link)})
                res_a = serve_mpc.import_external_sample_to_library(str(root), {'external_full_path': str(wav_a)})
                res_b = serve_mpc.import_external_sample_to_library(str(root), {'external_full_path': str(wav_b)})
            self.assertEqual(res_a['filename'], 'Kick_01.wav')
            self.assertNotEqual(res_b['filename'], 'Kick_01.wav')
            self.assertTrue(res_b['filename'].startswith('Kick_01_') and res_b['filename'].endswith('.wav'))

    def test_pattern_generate_and_search_cache_plus_faiss_fallback(self):
        import sqlite3
        from unittest.mock import patch

        with self.server() as (url, parent):
            root = parent / 'library'
            db_dir = root / 'BeatOS' / 'data'
            db_dir.mkdir(parents=True, exist_ok=True)
            db_file = db_dir / 'mpc_sample.db'
            con = sqlite3.connect(str(db_file))
            con.execute(
                'CREATE TABLE samples (id INTEGER PRIMARY KEY, filename TEXT, sound_type TEXT, '
                'sample_format TEXT, macro_category TEXT, sub_pack TEXT, bpm REAL, musical_key TEXT, '
                'camelot TEXT, energy_level TEXT, size_mb REAL, rel_path TEXT)'
            )
            con.execute(
                "INSERT INTO samples VALUES (1, 'Dusty_Kick.wav', 'KICK', 'WAV', 'Drums', 'Soul', 90.0, 'Am', '8A', 'HIGH', 0.5, 'Samples/Dusty_Kick.wav')"
            )
            con.commit()
            con.close()

            st1, raw1 = self.request(url + '/api/search?q=Dusty&limit=10')
            self.assertEqual(st1, 200, raw1)
            d1 = json.loads(raw1.decode('utf-8'))
            self.assertFalse(d1['cache_hit'])
            self.assertEqual(d1['count'], 1)

            st2, raw2 = self.request(url + '/api/search?q=Dusty&limit=10')
            self.assertEqual(st2, 200, raw2)
            d2 = json.loads(raw2.decode('utf-8'))
            self.assertTrue(d2['cache_hit'])

            with patch.dict(sys.modules, {'cerebro_faiss_engine': type('FakeFaiss', (), {
                'search_faiss_vector': staticmethod(lambda q, top_k=20: (_ for _ in ()).throw(RuntimeError('faiss index unavailable')))
            })()}):
                st3, raw3 = self.request(url + '/api/search?q=vintage%20bolero%20brass&limit=10')
                self.assertEqual(st3, 200, raw3)
                d3 = json.loads(raw3.decode('utf-8'))
                self.assertIn('faiss_warning', d3)

            st_pat, raw_pat = self.request(
                url + '/api/cerebro_pattern_generate',
                method='POST',
                headers={'Origin': url, 'Content-Type': 'application/json'},
                data=json.dumps({'style': 'oldies', 'bpm': 74, 'bars': 2}).encode('utf-8'),
            )
            self.assertEqual(st_pat, 200, raw_pat)
            d_pat = json.loads(raw_pat.decode('utf-8'))
            self.assertTrue(d_pat['success'])
            self.assertEqual(d_pat['swing_unit'], 2)
            self.assertEqual(d_pat['meter'], '12/8')
            self.assertGreater(d_pat['midi_events_count'], 0)
