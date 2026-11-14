import contextlib
import io
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
