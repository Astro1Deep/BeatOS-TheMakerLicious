import contextlib
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
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
        try:
            with urllib.request.urlopen(urllib.request.Request(url, **kwargs), timeout=3) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def test_serves_library_and_range(self):
        with self.server() as (url, _):
            self.assertEqual(self.request(url + '/inside.txt'), (200, b'library file'))
            self.assertEqual(self.request(url + '/inside.txt', headers={'Range': 'bytes=0-2'}), (206, b'lib'))

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

    def test_rejects_oversized_or_negative_request_lengths(self):
        with self.server() as (url, _):
            for length in ('-1', '2097152'):
                self.assertIn(self.request(url + '/api/create_kit', data=b'',
                                          headers={'Content-Length': length})[0], (400, 413))

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
