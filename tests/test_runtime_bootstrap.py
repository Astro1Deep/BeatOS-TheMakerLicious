"""Tests for BeatOS runtime diagnostics, codec resolution, and from-scratch OS installers."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from threading import Thread
from http.server import HTTPServer
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import beatos_runtime
import serve_mpc


class RuntimeBootstrapTests(unittest.TestCase):
    def setUp(self):
        beatos_runtime.clear_runtime_cache()

    def test_inspect_capabilities_returns_all_six_modes(self):
        caps = beatos_runtime.inspect_capabilities(ROOT, probe_codecs=False)
        self.assertEqual(caps["schema"], beatos_runtime.RUNTIME_SCHEMA)
        mode_ids = [m["id"] for m in caps["modes"]]
        self.assertEqual(
            mode_ids,
            [
                "core_catalog_mpc",
                "universal_codecs",
                "po_backup_modem",
                "acoustic_dsp_chop",
                "mir_mmr_chopping",
                "hardware_hygiene",
            ],
        )
        self.assertEqual(caps["summary"]["total_modes"], 6)
        self.assertIn(caps["summary"]["recommended_profile"], ("none", "full", "essential", "codecs"))
        self.assertIn(caps["platform"]["os_id"], ("macos", "windows", "linux"))

    def test_dry_run_install_plans_use_isolated_venv_without_breaking_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            with unittest.mock.patch.dict(os.environ, {"BEATOS_SUPPORT_DIR": tmp}, clear=False):
                os.environ.pop("BEATOS_VENV_DIR", None)
                for prof in ("full", "essential", "codecs"):
                    plan = beatos_runtime.install_support_profile(prof, dry_run=True, code_dir=ROOT)
                    self.assertTrue(plan["success"])
                    self.assertTrue(plan["dry_run"])
                    self.assertEqual(plan["profile"], prof)
                    joined = " ".join(" ".join(cmd) for cmd in plan["planned_commands"])
                    self.assertNotIn("--break-system-packages", joined)
                    self.assertIn(str(Path(tmp)), plan["venv_dir"])
                    self.assertTrue(any("-m venv" in " ".join(c) or "pip" in " ".join(c) for c in plan["planned_commands"]))

    def test_generated_target_installers_are_portable_and_valid_syntax(self):
        for prof in ("full", "essential", "codecs"):
            for target in ("macos", "windows", "linux"):
                fname, content = beatos_runtime.generate_bootstrap_script(target, prof)
                self.assertTrue(fname)
                self.assertNotIn("/Users/ivan", content)
                self.assertNotIn("/Volumes/MPCSMPL", content)
                self.assertIn("imageio-ffmpeg", content)
                if prof == "full":
                    self.assertIn("librosa", content)
                if target == "windows":
                    self.assertIn("\r\n", content)
                    self.assertIn("%LOCALAPPDATA%\\BeatOS", content)
                    self.assertIn("%SUPPORT_ROOT%\\venv", content)
                else:
                    self.assertIn("$HOME/.beatos", content)
                    if shutil.which("bash"):
                        with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as tf:
                            tf.write(content)
                            tpath = Path(tf.name)
                        try:
                            chk = subprocess.run(["bash", "-n", str(tpath)], capture_output=True, text=True)
                            self.assertEqual(chk.returncode, 0, chk.stderr)
                        finally:
                            tpath.unlink(missing_ok=True)

    def test_export_bootstrap_pack_and_cli_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "instaladores"
            pack = beatos_runtime.export_bootstrap_pack(dest, profile="essential")
            self.assertTrue(pack["success"])
            names = {f["filename"] for f in pack["files"]}
            self.assertEqual(
                names,
                {
                    "Instalar_Soporte_BeatOS_macOS.command",
                    "Instalar_Soporte_BeatOS_Windows.bat",
                    "install_beatos_support_linux.sh",
                    "requirements-beatos.txt",
                },
            )
            for item in pack["files"]:
                p = Path(item["path"])
                self.assertTrue(p.is_file())
                self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(), item["sha256"])

            # CLI flags on installer.py without personal paths or extra prompts
            chk = subprocess.run(
                [sys.executable, "-B", str(ROOT / "installer.py"), "--check-capabilities", "--lang", "en"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(chk.returncode, 0, chk.stderr)
            self.assertIn("CAPABILITIES, CODECS & RUNTIME REPORT", chk.stdout)

            cli_dir = Path(tmp) / "cli_pack"
            gen = subprocess.run(
                [sys.executable, "-B", str(ROOT / "installer.py"), "--generate-installers", str(cli_dir)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(gen.returncode, 0, gen.stderr)
            self.assertTrue((cli_dir / "Instalar_Soporte_BeatOS_Windows.bat").is_file())
            self.assertTrue((cli_dir / "requirements-beatos.txt").is_file())

    def test_server_system_capabilities_and_bootstrap_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = HTTPServer(("127.0.0.1", 0), serve_mpc.MPCAudioRequestHandler)
            server.root_dir = tmp
            t = Thread(target=server.serve_forever, daemon=True)
            t.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urllib.request.urlopen(base + "/api/status", timeout=10) as r:
                    st = json.loads(r.read())
                self.assertIn("capabilities_summary", st)

                with urllib.request.urlopen(base + "/api/system/capabilities", timeout=10) as r:
                    caps = json.loads(r.read())
                self.assertTrue(caps["success"])
                self.assertEqual(caps["capabilities"]["summary"]["total_modes"], 6)

                with urllib.request.urlopen(base + "/api/system/bootstrap_script?target=windows&profile=codecs", timeout=10) as r:
                    cd = r.headers.get("Content-Disposition", "")
                    body = r.read().decode("utf-8")
                self.assertIn("Instalar_Soporte_BeatOS_Windows.bat", cd)
                self.assertIn("imageio-ffmpeg", body)
                self.assertNotIn("/Users/ivan", body)

                req = urllib.request.Request(
                    base + "/api/system/export_bootstrap_pack",
                    data=json.dumps({"profile": "full"}).encode("utf-8"),
                    headers={"Content-Type": "application/json", "Origin": base},
                )
                with urllib.request.urlopen(req, timeout=10) as r:
                    pack = json.loads(r.read())
                self.assertTrue(pack["success"])
                self.assertTrue((Path(tmp) / "BeatOS" / "instaladores" / "Instalar_Soporte_BeatOS_macOS.command").is_file())
                self.assertTrue((Path(tmp) / "BeatOS" / "instaladores" / "requirements-beatos.txt").is_file())

                bad_req = urllib.request.Request(base + "/api/system/bootstrap_script?target=plan9&profile=full")
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(bad_req, timeout=5)
                self.assertEqual(ctx.exception.code, 400)
            finally:
                server.shutdown()
                t.join(timeout=3)
                server.server_close()

    def test_system_ffmpeg_plan_not_blocked_by_portable_imageio_ffmpeg(self):
        from unittest.mock import patch
        portable_only = {"path": "/tmp/fake-imageio-ffmpeg", "source": "imageio_ffmpeg"}
        with patch.object(beatos_runtime, "resolve_ffmpeg_binary", return_value=portable_only), \
             patch.object(beatos_runtime, "resolve_ffprobe_path", return_value=None), \
             patch("beatos_runtime.shutil.which", side_effect=lambda tool: "/usr/local/bin/brew" if tool == "brew" else None):
            with patch.object(beatos_runtime.sys, "platform", "darwin"):
                plan = beatos_runtime.install_support_profile("full", include_system_ffmpeg=True, dry_run=True)
        self.assertTrue(any(cmd[-2:] == ["install", "ffmpeg"] for cmd in plan["planned_commands"]), plan)


if __name__ == "__main__":
    unittest.main()
