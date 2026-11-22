#!/usr/bin/env python3
"""Enterprise Upgrade Unit Tests (E-03, E-04, E-05, E-09)."""

import gzip
import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import hardware_kit_builder as hkb
import serve_mpc


def _make_sine_wav(path: Path, freq: float = 220.0, duration_s: float = 2.0, sr: int = 44100) -> None:
    import math
    import struct

    n = int(sr * duration_s)
    frames = bytearray()
    for i in range(n):
        val = int(12000 * math.sin(2.0 * math.pi * freq * i / sr))
        frames.extend(struct.pack("<h", val))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(frames))


class TestEnterpriseUpgrades(unittest.TestCase):
    def test_e09_extract_bpm_handles_90bpm001_suffix(self):
        self.assertEqual(hkb._extract_explicit_bpm_from_text("13 45_Lo-Fi_Piano_Bmaj_90BPM001.wav"), 90.0)
        self.assertEqual(hkb.infer_kit_bpm("13 45_Lo-Fi_Piano_Bmaj_90BPM001.wav"), 90.0)

    def test_e09_astro1deep_kit_01xx_not_misclassified_as_drill(self):
        """Regression for Astro1Deep_Kit_01XX: 1 Drill hi-hat must NOT hijack a Lo-Fi/Boom Bap kit."""
        pads = [
            {"pad": 1, "sample_name": "01_Kick_Punch", "sound_type": "KICK", "duration_sec": 0.25},
            {"pad": 2, "sample_name": "02 Just_Blaze_Snare", "sound_type": "SNARE", "duration_sec": 0.28},
            {"pad": 3, "sample_name": "03 Just_Blaze_Kick", "sound_type": "KICK", "duration_sec": 0.24},
            {"pad": 4, "sample_name": "04 Kick_(Ocean_Boom_Bap_Drum_Kit)", "sound_type": "KICK", "duration_sec": 0.22},
            {"pad": 5, "sample_name": "05 03_Closed_Hi-hat_(Ocean_Drill_2_Drum_Kit)", "sound_type": "HIHAT", "duration_sec": 0.10},
            {"pad": 6, "sample_name": "06 Snare_(Ocean_Boom_Bap_Drum_Kit)", "sound_type": "SNARE", "duration_sec": 0.26},
            {"pad": 7, "sample_name": "07 OpenHat_(Ocean_Boom_Bap_Drum_Kit)", "sound_type": "HIHAT", "duration_sec": 0.35},
            {"pad": 8, "sample_name": "08 Clap_(Ocean_Boom_Bap_Drum_Kit)", "sound_type": "CLAP", "duration_sec": 0.20},
            {"pad": 9, "sample_name": "09 Cymatics_-_Eternity_Fill_6_-_90_BPM", "sound_type": "DRUM_LOOP", "duration_sec": 1.4},
            {"pad": 12, "sample_name": "12 Chopped_Breaks_Loop", "sound_type": "DRUM_LOOP", "duration_sec": 2.1},
            {"pad": 13, "sample_name": "13 45_Lo-Fi_Piano_Bmaj_90BPM001", "sound_type": "KEYS_SYNTH", "duration_sec": 5.3},
            {"pad": 14, "sample_name": "14 BoomBap-Vocal-MP_01", "sound_type": "VOCAL", "duration_sec": 1.1},
            {"pad": 15, "sample_name": "15 BoomBap-Vocal-MP_02", "sound_type": "VOCAL", "duration_sec": 1.0},
            {"pad": 16, "sample_name": "16 09_808Bass1_(MPC3k_Drum_Kit)", "sound_type": "BASS_808", "duration_sec": 0.45, "low_energy_ratio": 0.45},
        ]
        rhythm_mock = {
            "source_bpm": 90.0,
            "effective_source_bpm": 90.0,
            "swing_pct": 61.8,
            "rubato_index": 0.40,
            "timbre_profile": "vintage_oldies",
            "sub_energy_ratio": 0.11,
            "mid_warmth_ratio": 0.85,
            "high_air_ratio": 0.05,
        }
        res = hkb.detect_kit_style_weighted(
            kit_name="Astro1Deep_Kit_01XX",
            pad_reports=pads,
            bpm=90.0,
            sub_heavy_count=0,
            rhythm_analysis=rhythm_mock,
        )
        self.assertIn(res["id"], ("lofi", "boombap", "jazz_hop"))
        self.assertNotEqual(res["id"], "drill")
        self.assertNotEqual(res["mute_profile"], "club_clean")
        self.assertGreaterEqual(res["confidence"], 0.60)
        self.assertLessEqual(res["confidence"], 0.98)
        self.assertTrue(len(res.get("secondary_styles", [])) >= 1)
        self.assertIn("ancla melódica", res.get("style_evidence", ""))

    def test_e09_genuine_drill_kit_still_detects_drill(self):
        pads = [
            {"pad": 1, "sample_name": "UK_Drill_Kick_01", "sound_type": "KICK", "duration_sec": 0.25},
            {"pad": 2, "sample_name": "NY_Drill_Snare_Counter", "sound_type": "SNARE", "duration_sec": 0.22},
            {"pad": 3, "sample_name": "Sliding_808_Drill_C", "sound_type": "BASS_808", "duration_sec": 1.8, "low_energy_ratio": 0.82},
            {"pad": 4, "sample_name": "Glide_808_Sub_F", "sound_type": "BASS_808", "duration_sec": 1.6, "low_energy_ratio": 0.78},
            {"pad": 5, "sample_name": "Dark_Drill_Piano_142BPM", "sound_type": "MELODIC_LOOP", "duration_sec": 4.2},
        ]
        rhythm_mock = {
            "source_bpm": 142.0,
            "effective_source_bpm": 142.0,
            "swing_pct": 50.5,
            "rubato_index": 0.05,
            "timbre_profile": "sub_heavy_modern",
            "sub_energy_ratio": 0.42,
            "mid_warmth_ratio": 0.38,
        }
        res = hkb.detect_kit_style_weighted(
            kit_name="London_Drill_Vol1",
            pad_reports=pads,
            bpm=142.0,
            sub_heavy_count=2,
            rhythm_analysis=rhythm_mock,
        )
        self.assertEqual(res["id"], "drill")
        self.assertEqual(res["mute_profile"], "club_clean")

    def test_e04_and_e05_indexer_fts5_packs_wav_health_and_http_endpoints(self):
        with tempfile.TemporaryDirectory() as td:
            lib = Path(td)
            _make_sine_wav(lib / "MPC-Sample/Samples/LoFi_Pack/45_LoFi_Piano_Bmaj_90BPM001.wav", freq=246.94, duration_s=2.6)
            _make_sine_wav(lib / "MPC-Sample/Samples/BoomBap_Pack/Kick_Dusty_01.wav", freq=65.0, duration_s=0.3)

            proc = subprocess.run(
                [sys.executable, "-B", str(ROOT / "index_mpc_library.py"), "--path", str(lib)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)

            db_p = lib / "BeatOS/data/mpc_sample.db"
            self.assertTrue(db_p.is_file())
            con = sqlite3.connect(str(db_p))
            packs_n = con.execute("SELECT COUNT(*) FROM packs").fetchone()[0]
            self.assertGreaterEqual(packs_n, 1)
            health_rows = dict(con.execute("SELECT wav_health, COUNT(*) FROM samples GROUP BY wav_health").fetchall())
            self.assertEqual(health_rows.get("OK"), 2)
            fts_hits = con.execute("SELECT COUNT(*) FROM samples_fts WHERE samples_fts MATCH '\"piano\"*'").fetchone()[0]
            self.assertEqual(fts_hits, 1)
            con.close()

            # Spin up ephemeral BeatOS HTTP server to verify E-05 (gzip, security headers, /api/search, /api/health_audit)
            httpd = serve_mpc.HTTPServer(("127.0.0.1", 0), serve_mpc.MPCAudioRequestHandler)
            httpd.root_dir = str(lib)
            port = httpd.server_address[1]
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            try:
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/search?q=piano&limit=10",
                    headers={"Accept-Encoding": "gzip"},
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                    self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
                    self.assertEqual(resp.headers.get("X-Frame-Options"), "SAMEORIGIN")
                    raw = resp.read()
                    if resp.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                    data = json.loads(raw.decode("utf-8"))
                    self.assertTrue(data["success"])
                    self.assertEqual(data["count"], 1)
                    self.assertIn("Piano", data["results"][0]["filename"])

                req_h = urllib.request.Request(f"http://127.0.0.1:{port}/api/health_audit")
                with urllib.request.urlopen(req_h, timeout=5) as resp_h:
                    hdata = json.loads(resp_h.read().decode("utf-8"))
                    self.assertTrue(hdata["success"])
                    self.assertTrue(hdata["gzip_enabled"])
                    self.assertTrue(hdata["sqlite"]["fts5_ready"])
                    self.assertEqual(hdata["sqlite"]["integrity"], "ok")
                    self.assertEqual(hdata["sqlite"]["wav_health"].get("OK"), 2)

                # Verify gzip compression on large static HTML catalog
                req_cat = urllib.request.Request(
                    f"http://127.0.0.1:{port}/",
                    headers={"Accept-Encoding": "gzip"},
                )
                with urllib.request.urlopen(req_cat, timeout=5) as resp_c:
                    self.assertEqual(resp_c.status, 200)
                    self.assertEqual(resp_c.headers.get("Content-Encoding"), "gzip")
                    html_txt = gzip.decompress(resp_c.read()).decode("utf-8")
                    self.assertIn("SAMPLES", html_txt)
            finally:
                httpd.shutdown()
                httpd.server_close()


if __name__ == "__main__":
    unittest.main()
