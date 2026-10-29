from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import installer
import serve_mpc

class InstallerTests(unittest.TestCase):
    def test_index_option_runs_and_open_uses_local_server(self):
        with tempfile.TemporaryDirectory(prefix='Biblioteca Productor ') as tmp:
            (Path(tmp)/'catalogo_mpc_sample.html').write_text('<html></html>')
            with patch('builtins.input',side_effect=['1',tmp,'s']),patch('builtins.print'),patch('installer.subprocess.run') as run,patch('serve_mpc.run_server') as server:
                installer.main()
            self.assertEqual(run.call_args.args[0][-2:],['--path',tmp]);server.assert_called_once_with(tmp)

    def test_separate_code_and_library_find_builder_without_personal_paths(self):
        with tempfile.TemporaryDirectory(prefix='Biblioteca Productor ') as tmp:
            self.assertIsNotNone(serve_mpc.get_hardware_kit_builder(tmp))
            self.assertEqual(serve_mpc.get_system_status(tmp)['sample_count'],0)
            with patch('serve_mpc.subprocess.Popen') as popen:
                popen.return_value.stdout=[];popen.return_value.wait.return_value=0
                serve_mpc.run_reindex_thread(tmp)
            command=popen.call_args.args[0]
            self.assertEqual(Path(command[2]).parent,Path(serve_mpc.__file__).resolve().parent)
            self.assertEqual(command[-2:],['--path',tmp])

    def test_offline_export_script_requests_user_paths(self):
        html=(Path(__file__).resolve().parents[1]/'templates/catalogo.html').read_text()
        script=html[html.index('const scriptLines = ['):html.index('const scriptContent =')]
        self.assertNotIn('/Volumes/MPCSMPL',script)
        self.assertIn('test -f "$BEATOS_PROGRAM/hardware_kit_builder.py"',script)
        self.assertIn('--root "$BEATOS_LIBRARY"',script)

    def test_action_runner_does_not_offer_commands_for_another_user(self):
        html=(Path(__file__).resolve().parents[1]/'templates/catalogo.html').read_text()
        action=html[html.index('function executeLibraryAction('):html.index('function startTaskPolling(')]
        self.assertNotIn('/Users/ivan',action)
        self.assertNotIn('/Volumes/MPCSMPL',action)
        self.assertNotIn('dot_clean',action)
        self.assertIn('La acción no se completó en',action)
