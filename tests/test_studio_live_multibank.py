#!/usr/bin/env python3
"""
Tests de integración para:
  - Memoria persistente reversible Studio/Pre-Master ↔ Directo/PA (BeatOS/config/rack_mix_profiles.json)
  - Análisis individual (pad/banco) y coherencia global Multi-Banco A–H (/api/cerebro_analyze)
  - Recetas de Compresión/Ducking MPC Sample (9 géneros + regla anti-Pumper + techo AK4558)
  - Exportación .xpj Studio vs _LIVE.xpj con floats lossless y volume_locked
  - Medición de bounce (/api/audio_measure_bounce) y puente Cerebro OS ampliado
"""

from __future__ import annotations

import gzip
import json
import math
import os
import struct
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import wave
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT_REPO = Path(__file__).resolve().parent.parent
if str(ROOT_REPO) not in sys.path:
    sys.path.insert(0, str(ROOT_REPO))

import hardware_kit_builder as hkb
import serve_mpc


def _write_synth_wav(
    path: Path,
    *,
    freq_hz: float = 110.0,
    duration_sec: float = 0.6,
    amp_l: float = 0.5,
    amp_r: float | None = None,
    invert_r: bool = False,
    sr: int = 44100,
    channels: int = 2,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    n_frames = int(round(sr * duration_sec))
    a_r = amp_l if amp_r is None else amp_r
    sign_r = -1.0 if invert_r else 1.0
    frames = bytearray()
    for i in range(n_frames):
        env = 1.0 if i < int(n_frames * 0.85) else max(0.0, 1.0 - (i - n_frames * 0.85) / max(1.0, n_frames * 0.15))
        s = math.sin(2.0 * math.pi * freq_hz * (i / float(sr))) * env
        vl = max(-32767, min(32767, int(round(s * amp_l * 32767.0))))
        if channels == 2:
            vr = max(-32767, min(32767, int(round(s * a_r * sign_r * 32767.0))))
            frames.extend(struct.pack("<hh", vl, vr))
        else:
            frames.extend(struct.pack("<h", vl))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(frames))
    return path


class TestStudioLiveAndMultibank(unittest.TestCase):
    def setUp(self) -> None:
        self._old_disable_llm = os.environ.get("BEATOS_DISABLE_MLX_LLM")
        self._old_disable_rag = os.environ.get("BEATOS_DISABLE_CEREBRO_RAG")
        os.environ["BEATOS_DISABLE_MLX_LLM"] = "1"
        os.environ["BEATOS_DISABLE_CEREBRO_RAG"] = "1"

        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        (self.root / "BeatOS" / "config").mkdir(parents=True, exist_ok=True)
        (self.root / "Samples").mkdir(parents=True, exist_ok=True)

        # Banco A: Kick caliente + 808 fuerte + Snare
        self.kick_wav = _write_synth_wav(self.root / "Samples" / "Kick_Punch_90.wav", freq_hz=58.0, duration_sec=0.35, amp_l=0.95)
        self.snare_wav = _write_synth_wav(self.root / "Samples" / "Snare_Crack_90.wav", freq_hz=220.0, duration_sec=0.25, amp_l=0.82)
        self.bass_wav = _write_synth_wav(self.root / "Samples" / "808_Sub_A.wav", freq_hz=55.0, duration_sec=0.90, amp_l=0.90)
        # Banco B: Chops melódicos mucho más bajos (para forzar spread > 2 dB entre bancos)
        self.chop1_wav = _write_synth_wav(self.root / "Samples" / "Rhodes_Chop_Am.wav", freq_hz=440.0, duration_sec=1.20, amp_l=0.20)
        self.chop2_wav = _write_synth_wav(self.root / "Samples" / "Guitar_Soul_Am.wav", freq_hz=330.0, duration_sec=1.10, amp_l=0.18)
        # Banco C: Subsónico 25 Hz en fase + bajo estéreo antifase 70 Hz (<120 Hz)
        self.sub_rumble_wav = _write_synth_wav(
            self.root / "Samples" / "Sub_Rumble_25Hz.wav", freq_hz=25.0, duration_sec=0.90, amp_l=0.75, invert_r=False
        )
        self.sub_antiphase_wav = _write_synth_wav(
            self.root / "Samples" / "Bass_Antiphase_70Hz.wav", freq_hz=70.0, duration_sec=0.90, amp_l=0.75, invert_r=True
        )

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), serve_mpc.MPCAudioRequestHandler)
        self.server.root_dir = str(self.root)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.tmpdir.cleanup()
        if self._old_disable_llm is None:
            os.environ.pop("BEATOS_DISABLE_MLX_LLM", None)
        else:
            os.environ["BEATOS_DISABLE_MLX_LLM"] = self._old_disable_llm
        if self._old_disable_rag is None:
            os.environ.pop("BEATOS_DISABLE_CEREBRO_RAG", None)
        else:
            os.environ["BEATOS_DISABLE_CEREBRO_RAG"] = self._old_disable_rag

    def _req(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"} if data is not None else {},
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _sample_multibank_pads(self) -> list[dict]:
        return [
            {"pad": 1, "rel_path": "Samples/Kick_Punch_90.wav", "sample_name": "Kick_Punch_90.wav", "sound_type": "KICK", "volume": 0.707946, "volume_locked": True, "pan": 0.5, "tune": 0, "fine_tune": 0, "mute_group": 1},
            {"pad": 2, "rel_path": "Samples/Snare_Crack_90.wav", "sample_name": "Snare_Crack_90.wav", "sound_type": "SNARE", "volume": 0.562341, "volume_locked": True, "pan": 0.52, "tune": 1, "fine_tune": -5, "mute_group": 3},
            {"pad": 3, "rel_path": "Samples/808_Sub_A.wav", "sample_name": "808_Sub_A.wav", "sound_type": "BASS_808", "volume": 0.501187, "volume_locked": True, "pan": 0.5, "tune": 0, "fine_tune": 0, "mute_group": 4},
            {"pad": 17, "rel_path": "Samples/Rhodes_Chop_Am.wav", "sample_name": "Rhodes_Chop_Am.wav", "sound_type": "MELODIC_LOOP", "volume": 0.48, "volume_locked": True, "pan": 0.44, "tune": -2, "fine_tune": 12, "mute_group": 6},
            {"pad": 18, "rel_path": "Samples/Guitar_Soul_Am.wav", "sample_name": "Guitar_Soul_Am.wav", "sound_type": "MELODIC_LOOP", "volume": 0.46, "volume_locked": True, "pan": 0.58, "tune": 0, "fine_tune": 0, "mute_group": 6},
            {"pad": 33, "rel_path": "Samples/Sub_Rumble_25Hz.wav", "sample_name": "Sub_Rumble_25Hz.wav", "sound_type": "BASS_808", "volume": 0.51, "volume_locked": True, "pan": 0.5, "tune": 0, "fine_tune": 0, "mute_group": 4},
            {"pad": 34, "rel_path": "Samples/Bass_Antiphase_70Hz.wav", "sample_name": "Bass_Antiphase_70Hz.wav", "sound_type": "BASS_808", "volume": 0.51, "volume_locked": True, "pan": 0.5, "tune": 0, "fine_tune": 0, "mute_group": 4},
        ]

    def test_reversible_studio_live_pa_snapshots_bit_for_bit(self) -> None:
        studio_pads = self._sample_multibank_pads()
        studio_globals = {"tempo": 90, "gain_profile": "manual", "mute_profile": "real_drums", "route_mode": "submix_split"}

        # 1. Guardar snapshot inicial Studio
        st, saved = self._req("POST", "/api/rack_mix_profiles/save", {
            "kit_name": "BoomBap_Live_Test",
            "mode": "studio_mastering",
            "pads": studio_pads,
            "globals": studio_globals,
        })
        self.assertEqual(st, 200)
        self.assertTrue(saved["success"])
        set_id = saved["set_id"]
        self.assertTrue((self.root / "BeatOS" / "config" / "rack_mix_profiles.json").is_file())

        # 2. Cambiar Studio -> Live PA (sintetiza Live PA por primera vez y guarda Studio)
        st, sw_live = self._req("POST", "/api/rack_mix_profiles/switch", {
            "set_id": set_id,
            "kit_name": "BoomBap_Live_Test",
            "from_mode": "studio_mastering",
            "target_mode": "live_pa",
            "pads": studio_pads,
            "globals": studio_globals,
            "style_id": "boombap",
        })
        self.assertEqual(st, 200)
        self.assertEqual(sw_live["active_mode"], "live_pa")
        self.assertFalse(sw_live["restored_from_snapshot"])
        live_pads = sw_live["pads"]
        self.assertEqual(len(live_pads), len(studio_pads))

        # 3. Editar manualmente un pad en Directo PA (pad 17 -> 0.777777)
        live_pads_edited = [dict(p) for p in live_pads]
        for p in live_pads_edited:
            if p["pad"] == 17:
                p["volume"] = 0.777777
                p["pan"] = 0.61

        # 4. Volver Live PA -> Studio: debe restaurar Studio BIT-A-BIT (incluyendo 0.707946 exacto en pad 1)
        st, sw_studio = self._req("POST", "/api/rack_mix_profiles/switch", {
            "set_id": set_id,
            "kit_name": "BoomBap_Live_Test",
            "from_mode": "live_pa",
            "target_mode": "studio_mastering",
            "pads": live_pads_edited,
            "globals": {"tempo": 92, "gain_profile": "smart_pcm"},
        })
        self.assertEqual(st, 200)
        self.assertEqual(sw_studio["active_mode"], "studio_mastering")
        self.assertTrue(sw_studio["restored_from_snapshot"])
        restored_by_pad = {p["pad"]: p for p in sw_studio["pads"]}
        self.assertAlmostEqual(restored_by_pad[1]["volume"], 0.707946, places=6)
        self.assertAlmostEqual(restored_by_pad[2]["pan"], 0.52, places=6)
        self.assertEqual(restored_by_pad[2]["fine_tune"], -5)
        self.assertAlmostEqual(restored_by_pad[17]["volume"], 0.48, places=6)
        self.assertEqual(sw_studio["globals"]["tempo"], 90)

        # 5. Volver Studio -> Live PA: debe restaurar la edición manual Live PA (0.777777 / pan 0.61)
        st, sw_live2 = self._req("POST", "/api/rack_mix_profiles/switch", {
            "set_id": set_id,
            "kit_name": "BoomBap_Live_Test",
            "from_mode": "studio_mastering",
            "target_mode": "live_pa",
            "pads": sw_studio["pads"],
            "globals": sw_studio["globals"],
        })
        self.assertEqual(st, 200)
        self.assertTrue(sw_live2["restored_from_snapshot"])
        live2_by_pad = {p["pad"]: p for p in sw_live2["pads"]}
        self.assertAlmostEqual(live2_by_pad[17]["volume"], 0.777777, places=6)
        self.assertAlmostEqual(live2_by_pad[17]["pan"], 0.61, places=6)

        # 6. GET /api/rack_mix_profiles?set_id=... y POST /reset a baseline_original
        st, got = self._req("GET", f"/api/rack_mix_profiles?set_id={set_id}")
        self.assertEqual(st, 200)
        self.assertTrue(got["found"])
        self.assertIn("baseline_original", got["available_snapshots"])
        self.assertIn("studio_mastering", got["available_snapshots"])
        self.assertIn("live_pa", got["available_snapshots"])

        st, rst = self._req("POST", "/api/rack_mix_profiles/reset", {"set_id": set_id, "kit_name": "BoomBap_Live_Test"})
        self.assertEqual(st, 200)
        self.assertEqual(rst["restored_from"], "baseline_original")
        self.assertEqual(rst["active_mode"], "studio_mastering")
        self.assertAlmostEqual(rst["pads_map"]["1"]["volume"], 0.707946, places=6)

    def test_multibank_analysis_coherence_and_scopes(self) -> None:
        pads = self._sample_multibank_pads()
        st, res = self._req("POST", "/api/cerebro_analyze", {
            "kit_name": "BoomBap_90_MultiBank",
            "tempo": 90,
            "pads": pads,
            "scope": "all_banks",
            "mix_mode": "live_pa",
            "use_llm": False,
        })
        self.assertEqual(st, 200)
        self.assertTrue(res["success"])
        self.assertEqual(res["mix_mode"], "live_pa")
        self.assertEqual(res["scope"], "all_banks")

        banks = res.get("banks_summary") or []
        bank_letters = [b["bank"] for b in banks]
        self.assertEqual(bank_letters, ["A", "B", "C"])

        gc = res.get("global_coherence") or {}
        self.assertGreater(float(gc.get("bank_rms_spread_db") or 0.0), 2.0)
        trims = gc.get("bank_trims_db") or {}
        for b_let, trim_v in trims.items():
            self.assertGreaterEqual(float(trim_v), -3.0, f"Bank {b_let} trim below -3 dB")
            self.assertLessEqual(float(trim_v), 3.0, f"Bank {b_let} trim above +3 dB")
        # Pad 33 tiene subsónico 25 Hz y Pad 34 tiene antifase estéreo 70 Hz (<120 Hz)
        self.assertIn(33, gc.get("subsonic_pa_risk_pads") or [])
        self.assertIn(34, gc.get("sub_mono_risk_pads") or [])

        # Cada pad trae dual-profile volumes + telemetría acústica
        for p in res["pads"]:
            self.assertIn("recommended_volume_studio", p)
            self.assertIn("recommended_volume_live", p)
            self.assertIn("true_peak_dbtp", p)
            self.assertIn("lufs_active_est", p)

        # Telemetría MLX determinista completa y retrocompatible
        cop = res["mlx_copilot"]
        self.assertFalse(cop["used_llm"])
        self.assertIn("fallback_reason", cop)
        self.assertIn("latency_ms", cop)
        self.assertIn("rag_mode", cop)
        plan = cop["plan"]
        for k in ("chop_plan", "mix_plan", "sequencer_tip", "creative_flip", "profile_advice", "ducking_recipe", "multibank_coherence_plan"):
            self.assertIn(k, plan)

        # Alcance active_bank (solo Banco B -> pads 17 y 18)
        st_b, res_b = self._req("POST", "/api/cerebro_analyze", {
            "kit_name": "BoomBap_90_MultiBank",
            "tempo": 90,
            "pads": pads,
            "scope": "active_bank",
            "target_bank": 1,
            "use_llm": False,
        })
        self.assertEqual(st_b, 200)
        self.assertEqual([p["pad"] for p in res_b["pads"]], [17, 18])

        # Alcance single_pad (solo Pad 33)
        st_p, res_p = self._req("POST", "/api/cerebro_analyze", {
            "kit_name": "BoomBap_90_MultiBank",
            "tempo": 90,
            "pads": pads,
            "scope": "single_pad",
            "target_pad": 33,
            "use_llm": False,
        })
        self.assertEqual(st_p, 200)
        self.assertEqual([p["pad"] for p in res_p["pads"]], [33])

    def test_ducking_recipes_9_genres_and_anti_pumper_rule(self) -> None:
        genres = ("boombap", "lofi", "jazz_hop", "drumless", "drill", "trap", "dnb", "house_techno", "afrobeats")
        for g in genres:
            for mode in ("studio_mastering", "live_pa"):
                rec = hkb.build_mpc_ducking_recipe(style_id=g, bpm=120.0, mix_mode=mode, has_kick=True, has_bass=True, has_melodic=True)
                self.assertAlmostEqual(rec["release_1_16_ms"], 125.0, places=1)
                self.assertAlmostEqual(rec["release_1_8_ms"], 250.0, places=1)
                self.assertAlmostEqual(rec["release_1_32_ms"], 62.5, places=1)
                self.assertIn("mpc_stock_color_comp", rec)
                self.assertIn("sampqol_mother_ducker", rec)
                self.assertIn("melodee_sidechain", rec)
                self.assertIn("pa_safety_chain", rec)
                self.assertLessEqual(float(rec["pa_safety_chain"]["true_peak_ceiling_dbtp"]), -0.8)
        # Regla anti-Pumper estricta en Dilla/Trap/Drill/DnB
        for forbidden in ("jazz_hop", "trap", "drill", "dnb"):
            rec_f = hkb.build_mpc_ducking_recipe(style_id=forbidden, bpm=90.0, mix_mode="live_pa", swing_pct=60.0)
            self.assertFalse(rec_f["pumper_allowed"], f"{forbidden} must forbid Pumper")
        rec_house = hkb.build_mpc_ducking_recipe(style_id="house_techno", bpm=126.0, mix_mode="live_pa", swing_pct=50.0)
        self.assertTrue(rec_house["pumper_allowed"])

    def test_export_live_xpj_lossless_floats_and_volume_locked(self) -> None:
        pads = [
            {"pad": 1, "rel_path": "Samples/Kick_Punch_90.wav", "sample_name": "Kick_Punch_90.wav", "sound_type": "KICK", "volume": 0.707946, "volume_locked": True},
            {"pad": 2, "rel_path": "Samples/808_Sub_A.wav", "sample_name": "808_Sub_A.wav", "sound_type": "BASS_808", "volume": 0.612345, "volume_locked": True},
        ]
        res = hkb.create_kit(
            "LiveSet_Demo",
            pads,
            target="mpc",
            source_root=self.root,
            tempo=92.0,
            mpc_options={
                "gain_profile": "manual",
                "mix_mode": "live_pa",
                "append_mode_suffix": True,
                "audio_route_mode": "submix_split",
            },
        )
        xpj_path = Path(res["targets"]["mpc"]["project_path"])
        self.assertTrue(xpj_path.is_file())
        self.assertTrue(xpj_path.name.endswith("_LIVE.xpj"), f"Expected _LIVE.xpj, got {xpj_path.name}")
        pdata_dir = xpj_path.parent / f"{xpj_path.stem}_[ProjectData]"
        self.assertTrue(pdata_dir.is_dir())
        # Sidecar de reporte fuera de _[ProjectData]
        report_files = list(xpj_path.parent.glob("*_beatos_mix_report.json"))
        self.assertTrue(len(report_files) >= 1)
        self.assertEqual(list(pdata_dir.glob("*_beatos_mix_report.json")), [])

        raw_txt = gzip.decompress(xpj_path.read_bytes()).decode("utf-8")
        self.assertTrue(raw_txt.startswith("ACVS\n1.3.0.12\nSerialisableProjectData\njson\nLinux\n"))
        obj = json.loads(raw_txt[raw_txt.index("{"):])
        mixer = obj["data"]["mixer"]
        self.assertAlmostEqual(mixer["volume"], 0.7943282347242815, places=6)
        self.assertAlmostEqual(mixer["outputs"][0]["mixable"]["volume"], 0.8912509381337456, places=6)
        # Pad 1 con volume_locked=True a 0.707946 NO fue sobrescrito por el centinela
        inst0 = obj["data"]["tracks"][0]["program"]["drum"]["instruments"][0]
        self.assertAlmostEqual(inst0["mixable"]["volume"], 0.707946, places=5)
        # submix_split (PR #21 canónico): Kick -> Track (dest=0, subIdx=0), 808 -> Submix 1 (dest=1, subIdx=0)
        inst1 = obj["data"]["tracks"][0]["program"]["drum"]["instruments"][1]
        self.assertEqual(inst0["mixable"]["audioRoute"]["destination"], 0)
        self.assertEqual(inst0["mixable"]["audioRoute"]["audioRouteSubIndex"], 0)
        self.assertEqual(inst1["mixable"]["audioRoute"]["destination"], 1)
        self.assertEqual(inst1["mixable"]["audioRoute"]["audioRouteSubIndex"], 0)

    def test_bounce_loudness_endpoint_and_cerebro_playbook_9_cards(self) -> None:
        st, res = self._req("POST", "/api/audio_measure_bounce", {"path": "Samples/Kick_Punch_90.wav"})
        self.assertEqual(st, 200)
        self.assertTrue(res["success"])
        rep = res["report"]
        for k in ("lufs_integrated", "true_peak_dbtp", "peak_dbfs", "crest_db", "studio_ready", "live_pa_ready"):
            self.assertIn(k, rep)

        # Path traversal bloqueado
        st_bad, _ = self._req("POST", "/api/audio_measure_bounce", {"path": "../../etc/passwd"})
        self.assertEqual(st_bad, 400)

        # 9 tarjetas Audio/MIR incluyendo las 3 nuevas
        cards = serve_mpc._get_audio_mir_playbook_cards()
        card_ids = {c["id"] for c in cards}
        self.assertEqual(len(cards), 9)
        self.assertTrue({"studio_vs_live_pa", "mpc_ducking_compression", "multibank_coherence"}.issubset(card_ids))

        # detect_cerebro_os reporta nuevas claves de estado/puente
        st_c, c_data = self._req("GET", "/api/cerebro_status")
        self.assertEqual(st_c, 200)
        cos = c_data["cerebro_os"]
        for key in ("gateway_online", "gateway_circuit", "webui_online", "ollama_embed_online", "rag_audio_chunks_count"):
            self.assertIn(key, cos)


if __name__ == "__main__":
    unittest.main()
