#!/usr/bin/env python3
"""
Unit tests for Universal Hardware Kit Builder & Multi-Sampler Bridge (hardware_kit_builder.py)
Tests export capabilities for Akai MPC, Teenage Engineering EP-133, Roland SP-404, NI Maschine, and PO-33.
"""

import unittest
import tempfile
import wave
import struct
import json
import gzip
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
import shutil

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hardware_kit_builder import (
    export_mpc_program,
    export_mpc_project,
    export_sp404mk2_kit,
    export_sp404a_kit,
    export_ni_maschine_kit,
    export_ep133_ko2_kit,
    export_po33_drum_reel,
    parse_xpm_program,
    create_chromatic_kit,
    parse_note,
    build_scale_offsets,
    SCALES,
    NOTE_NAMES,
)

class TestHardwareKitBuilder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = Path(tempfile.mkdtemp(prefix="beatos_test_"))
        
        # Create 4 dummy audio files
        cls.sample_files = []
        for i in range(1, 5):
            label = ('Kick', 'Snare', 'Hat_Closed', 'Hat_Open')[i - 1]
            p = cls.test_dir / f"{label}_test_sample_{i}.wav"
            with wave.open(str(p), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(44100)
                # 0.1s of audio, safe amplitude
                frames = [struct.pack("<h", int(1000 * (j % 50 - 25))) for j in range(4410)]
                wf.writeframes(b"".join(frames))
            cls.sample_files.append(p)
            
        cls.pads_data = {
            1: {"source_path": str(cls.sample_files[0]), "sample_path": str(cls.sample_files[0]), "sample_name": "Kick_01", "volume": 0.9, "pan": 0.5, "tune": 0, "mute_group": 0},
            2: {"source_path": str(cls.sample_files[1]), "sample_path": str(cls.sample_files[1]), "sample_name": "Snare_01", "volume": 0.8, "pan": 0.5, "tune": 0, "mute_group": 0},
            3: {"source_path": str(cls.sample_files[2]), "sample_path": str(cls.sample_files[2]), "sample_name": "Hat_Cl_01", "volume": 0.7, "pan": 0.4, "tune": 0, "mute_group": 1},
            4: {"source_path": str(cls.sample_files[3]), "sample_path": str(cls.sample_files[3]), "sample_name": "Hat_Op_01", "volume": 0.7, "pan": 0.6, "tune": 0, "mute_group": 1},
        }

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_01_export_mpc_program(self):
        out_dir = self.test_dir / "out_mpc_xpm"
        xpm_path = export_mpc_program("TestKit_MPC", self.pads_data, out_dir, copy_samples=False)
        self.assertTrue(Path(xpm_path).exists())
        
        # Validate XML schema
        tree = ET.parse(xpm_path)
        root = tree.getroot()
        self.assertEqual(root.tag, "MPCVObject")
        prog = root.find("Program")
        self.assertIsNotNone(prog)
        self.assertEqual(prog.find("ProgramName").text, "TestKit_MPC")

    def test_02_export_mpc_project(self):
        out_dir = self.test_dir / "out_mpc_xpj"
        xpj_path = export_mpc_project("TestProject_MPC", self.pads_data, out_dir, tempo=92.0)
        self.assertTrue(Path(xpj_path).exists())
        
        # Native MPC projects wrap JSON in an ACVS header inside gzip.
        with gzip.open(xpj_path, "rt", encoding="utf-8") as gz:
            content = gz.read()
        self.assertTrue(content.startswith('ACVS\n'))
        data = json.loads(content[content.index('{'):])['data']
        self.assertEqual(data['masterTempo'], 92.0)
        self.assertEqual(len(data['samples']), 4)
        project_data = Path(xpj_path).parent / 'TestProject_MPC_[ProjectData]'
        for sample in data['samples']:
            self.assertTrue((project_data / sample['path']).is_file())

    def test_03_export_sp404mk2_kit(self):
        out_dir = self.test_dir / "out_sp404mk2"
        kit_dir = export_sp404mk2_kit("TestKit_SP404MK2", self.pads_data, out_dir)
        self.assertTrue(Path(kit_dir).exists())
        
        pad1_file = Path(kit_dir) / "PAD_01_Kick_01.wav"
        self.assertTrue(pad1_file.exists())
        
        manifest = Path(kit_dir) / "sp404mk2_manifest.json"
        self.assertTrue(manifest.exists())

    def test_04_export_sp404a_kit(self):
        out_dir = self.test_dir / "out_sp404a"
        kit_dir = export_sp404a_kit("TestKit_SP404A", self.pads_data, out_dir)
        self.assertTrue(Path(kit_dir).exists())
        
        pad1_file = Path(kit_dir) / "A01.wav"
        self.assertTrue(pad1_file.exists())

    def test_05_export_ni_maschine_kit(self):
        out_dir = self.test_dir / "out_maschine"
        kit_dir = export_ni_maschine_kit("TestKit_Maschine", self.pads_data, out_dir)
        self.assertTrue(Path(kit_dir).exists())
        
        pad1_file = Path(kit_dir) / "Samples" / "Group_A" / "A01_Kick_01.wav"
        self.assertTrue(pad1_file.exists())

    def test_06_export_ep133_ko2_kit(self):
        out_dir = self.test_dir / "out_ep133"
        kit_dir, pak_path = export_ep133_ko2_kit("TestKit_EP133", self.pads_data, out_dir)
        self.assertTrue(Path(kit_dir).exists())
        self.assertTrue(Path(pak_path).exists())
        
        # Verify JSON metadata
        meta_file = Path(kit_dir) / "meta.json"
        self.assertTrue(meta_file.exists())
        with open(meta_file, "r") as f:
            meta = json.load(f)
        self.assertEqual(meta["device"], "Teenage Engineering EP-133 K.O. II")
        self.assertEqual(meta["package_name"], "TestKit_EP133")
        self.assertEqual(len(meta["sounds"]), 4)
        
        # Verify .pak is a valid zip archive
        # Exported kit instructions are deliverables too: EN is first, ES remains complete.
        english_guide = (Path(kit_dir) / "README_EP133_KO_II.txt").read_text(encoding="utf-8")
        spanish_guide = (Path(kit_dir) / "README_EP133_KO_II_ES.txt").read_text(encoding="utf-8")
        self.assertIn("IMPORT INSTRUCTIONS",english_guide)
        self.assertNotIn("INSTRUCCIONES DE IMPORTACIÓN",english_guide)
        self.assertIn("INSTRUCCIONES DE IMPORTACIÓN",spanish_guide)
        with zipfile.ZipFile(pak_path) as bundle:
            self.assertIn("README_EP133_KO_II.txt",bundle.namelist())
            self.assertIn("README_EP133_KO_II_ES.txt",bundle.namelist())
        self.assertTrue(zipfile.is_zipfile(pak_path))
        with zipfile.ZipFile(pak_path, "r") as z:
            names = z.namelist()
            self.assertIn("meta.json", names)
            self.assertTrue(any(n.startswith("sounds/") for n in names))

    def test_07_export_po33_drum_reel(self):
        out_dir = self.test_dir / "out_po33"
        reel_path, total_dur, slices = export_po33_drum_reel("TestReel_PO33", self.pads_data, out_dir)
        english_po_guide = Path(out_dir) / "TestReel_PO33_PO33_Loading_Guide_EN.txt"
        self.assertTrue(english_po_guide.is_file())
        self.assertIn("IMPORT PROCEDURE",english_po_guide.read_text(encoding="utf-8"))
        self.assertIn("GUÍA DE CARGA RÁPIDA",(Path(out_dir) / "TestReel_PO33_PO33_Carga_Guia.txt").read_text(encoding="utf-8"))

        self.assertTrue(Path(reel_path).exists())
        self.assertGreater(total_dur, 0.0)
        self.assertLessEqual(total_dur, 40.0)
        self.assertEqual(len(slices), 4)
        
        # Check audio properties of concatenated strip
        with wave.open(reel_path, "rb") as wf:
            self.assertEqual(wf.getnchannels(), 1)
            self.assertEqual(wf.getsampwidth(), 2)
            self.assertEqual(wf.getframerate(), 44100)

    def test_08_po33_smart_trim_guarantee_40s(self):
        # Create long 15s audio files that would sum to 60s
        long_pads = {}
        for i in range(1, 5):
            p = self.test_dir / f"long_sample_{i}.wav"
            with wave.open(str(p), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(44100)
                # 12 seconds each -> 4 * 12s = 48s + gaps > 40s
                frames = [struct.pack("<h", 500) for _ in range(44100 * 12)]
                wf.writeframes(b"".join(frames))
            long_pads[i] = {"source_path": str(p), "sample_name": f"Long_{i}", "sound_type": "DRONE"}

        out_dir = self.test_dir / "out_po33_trimmed"
        reel_path, total_dur, slices = export_po33_drum_reel("TestReel_Over40s", long_pads, out_dir)
        self.assertTrue(Path(reel_path).exists())
        self.assertLessEqual(total_dur, 40.0, f"Drum Reel duró {total_dur}s, debe ser <= 40.0s!")
        self.assertEqual(len(slices), 4)
        for s in slices:
            self.assertTrue(s["trimmed"])

    def test_09_parse_xpm_program_avoids_ghost_pads(self):
        # Generar un XPM con 4 pads asignados (los otros 124 instrumentos vacíos en XML)
        out_dir = self.test_dir / "out_mpc_parse"
        xpm_path = export_mpc_program("TestKit_4Pads", self.pads_data, out_dir, copy_samples=False)
        self.assertTrue(Path(xpm_path).exists())

        prog = parse_xpm_program(xpm_path, source_root=self.test_dir)
        self.assertEqual(prog["program_name"], "TestKit_4Pads")
        pads = prog["pads"]

        # Debe tener exactamente 4 pads asignados
        self.assertEqual(len(pads), 4, f"Se esperaban 4 pads asignados, pero se obtuvieron {len(pads)}")
        self.assertEqual(sorted(pads.keys()), [1, 2, 3, 4])

        # Verificar que ningún pad tiene '.wav' como nombre de archivo ni nombres vacíos
        for p_num, p_data in pads.items():
            self.assertNotEqual(p_data["sample_file"], ".wav", f"Pad {p_num} tiene sample_file vacío/erróneo: '.wav'")
            self.assertTrue(len(p_data["sample_name"]) > 0, f"Pad {p_num} tiene sample_name vacío")
            self.assertIn(p_num, [1, 2, 3, 4])

        # Los pads 5 a 128 NO deben estar en el diccionario (evitando pads fantasma)
        for unassigned in range(5, 17):
            self.assertNotIn(unassigned, pads, f"El pad desasignado {unassigned} no debe estar en pads!")

    def test_10_parse_xpm_program_resolves_all_real_samples(self):
        # Comprobar que los samples asignados resuelven sus rutas completas y tipos sonoros
        out_dir = self.test_dir / "out_mpc_parse_res"
        xpm_path = export_mpc_program("TestKit_Resolve", self.pads_data, out_dir, copy_samples=True)
        prog = parse_xpm_program(xpm_path, source_root=self.test_dir)
        pads = prog["pads"]

        self.assertEqual(pads[1]["sound_type"], "KICK")
        self.assertEqual(pads[2]["sound_type"], "SNARE")
        self.assertEqual(pads[3]["sound_type"], "HIHAT")
        self.assertEqual(pads[4]["sound_type"], "HIHAT")
        self.assertTrue(pads[1]["full_path"].endswith("test_sample_1.wav"))

    def test_11_chromatic_helpers_and_scale_offsets(self):
        # 1. Parse note
        pc, octv = parse_note("C2")
        self.assertEqual(pc, 0)
        self.assertEqual(octv, 2)

        pc, octv = parse_note("F#1")
        self.assertEqual(pc, 6)
        self.assertEqual(octv, 1)

        pc, octv = parse_note("Eb3")
        self.assertEqual(pc, 3)
        self.assertEqual(octv, 3)

        with self.assertRaises(ValueError):
            parse_note("H2")

        # 2. Scale offsets
        chrom_offsets = build_scale_offsets("chromatic", count=16, start_octave=0)
        self.assertEqual(chrom_offsets, list(range(16)))

        minor_offsets = build_scale_offsets("minor", count=16, start_octave=0)
        self.assertEqual(minor_offsets[:7], [0, 2, 3, 5, 7, 8, 10])
        # Pad 15 and 16 clamped to <= 24
        self.assertLessEqual(max(minor_offsets), 24)
        self.assertGreaterEqual(min(minor_offsets), -24)

        # Scale with negative start octave
        penta_neg = build_scale_offsets("pentatonic_minor", count=16, start_octave=-1)
        self.assertEqual(len(penta_neg), 16)
        self.assertEqual(penta_neg[0], -12)
        self.assertLessEqual(max(penta_neg), 24)

    def test_12_create_chromatic_kit_mpc_export_and_tuning(self):
        ck_dir = self.test_dir / "Custom_Kits"
        res = create_chromatic_kit(
            sample_path=self.sample_files[0],
            kit_name="TestBass_808",
            scale="minor",
            root_note="C2",
            start_octave=0,
            monophonic=True,
            target="mpc",
            source_root=self.test_dir,
            output_base_dir=ck_dir,
            tempo=128.0,
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["kit_name"], "TestBass_808")
        self.assertEqual(res["scale"], "minor")
        self.assertEqual(res["musical_key"], "C Minor")
        self.assertEqual(res["samples_count"], 16)

        mpc_out = ck_dir / "TestBass_808" / "Akai_MPC"
        xpj_file = mpc_out / "TestBass_808" / "TestBass_808.xpj"
        self.assertTrue(xpj_file.exists(), f"No se encontró el .xpj en {xpj_file}")

        # Comprobar que en [ProjectData] las 16 muestras llevan los nombres de nota
        pdata_dir = mpc_out / "TestBass_808" / "TestBass_808_[ProjectData]"
        self.assertTrue(pdata_dir.is_dir())
        c2_sample = pdata_dir / "PAD001_TestBass_808_C2.wav"
        self.assertTrue(c2_sample.exists(), f"Falta {c2_sample}")

        # Descomprimir y auditar .xpj
        raw = gzip.decompress(xpj_file.read_bytes()).decode("utf-8")
        self.assertTrue(raw.startswith("ACVS"))
        payload = json.loads(raw[raw.index("{"):])
        data = payload["data"]
        self.assertEqual(data["masterTempo"], 128.0)
        drum = data["tracks"][0]["program"]["drum"]
        insts = drum["instruments"]
        self.assertGreaterEqual(len(insts), 16)

        expected_offsets = build_scale_offsets("minor", count=16, start_octave=0)
        for i in range(16):
            inst = insts[i]
            expected_tune = expected_offsets[i]
            self.assertEqual(inst["coarseTune"], expected_tune, f"Pad {i+1} coarseTune mismatch")
            self.assertEqual(inst["whichMuteGroup"], 1, f"Pad {i+1} debe tener muteGroup 1 (monofónico)")
            lay0 = inst["layersv"][0]
            self.assertTrue(lay0["active"])
            self.assertEqual(lay0["coarseTune"], expected_tune)
            self.assertEqual(lay0["pitch"], float(expected_tune))

    def test_13_create_chromatic_kit_polyphonic_and_validation(self):
        ck_dir = self.test_dir / "Custom_Kits"
        res = create_chromatic_kit(
            sample_path=self.sample_files[1],
            kit_name="TestKeys_Poly",
            scale="pentatonic_major",
            root_note="G1",
            monophonic=False,
            target="mpc",
            source_root=self.test_dir,
            output_base_dir=ck_dir,
        )
        self.assertTrue(res["success"])
        self.assertFalse(res["monophonic"])

        # En kit polifónico, mute group debe ser 0
        xpj_file = ck_dir / "TestKeys_Poly" / "Akai_MPC" / "TestKeys_Poly" / "TestKeys_Poly.xpj"
        raw = gzip.decompress(xpj_file.read_bytes()).decode("utf-8")
        payload = json.loads(raw[raw.index("{"):])
        insts = payload["data"]["tracks"][0]["program"]["drum"]["instruments"]
        for i in range(16):
            self.assertEqual(insts[i]["whichMuteGroup"], 0, f"Pad polifónico {i+1} no debe tener muteGroup")

        # Validaciones de error
        with self.assertRaises(ValueError):
            create_chromatic_kit(self.sample_files[0], "BadScale", scale="escala_inexistente", source_root=self.test_dir)

        with self.assertRaises(ValueError):
            create_chromatic_kit(self.sample_files[0], "BadNote", root_note="NotaInvalida", source_root=self.test_dir)

        with self.assertRaises(FileNotFoundError):
            create_chromatic_kit("/ruta/falsa/sample_fantasma.wav", "NoSample", source_root=self.test_dir)

    def test_melodee_settings_read_update_preserve_and_validate(self):
        from hardware_kit_builder import detect_mpc_boot_status, read_melodee_settings, update_melodee_settings

        root = Path(self.test_dir) / "melodee_card"
        (root / "autorun" / "melodee").mkdir(parents=True)
        (root / "autorun" / "melodee" / "app").write_text("melodee\n", encoding="utf-8")
        (root / "autorun" / "melodee" / "VERSION").write_text("v0.4.0 7e5f862\n", encoding="utf-8")
        (root / "Melodee" / "Projects").mkdir(parents=True)
        (root / "Melodee" / "Projects" / "Beat01.mldp").write_bytes(b"MLDP")
        (root / "Melodee" / "Plugins" / "Poly").mkdir(parents=True)
        (root / "Melodee" / "settings").write_text(
            "start=/media/sd/Melodee/Projects/Beat01.mldp\n"
            "last=/media/sd/Melodee/Projects/Beat01.mldp\n"
            "lessons=3\n"
            "pad_response=1\n"
            "knob_takeover=1\n"
            "audio_rate=44100\n"
            "favourites2=0,5,12\n",
            encoding="utf-8",
        )

        boot = detect_mpc_boot_status(root)
        self.assertEqual(boot["active_boot"], "melodee")
        self.assertTrue(boot["melodee_detected"])
        self.assertEqual(boot["melodee_version"], "v0.4.0 7e5f862")
        self.assertEqual(boot["projects_count"], 1)
        self.assertEqual(boot["plugins_count"], 1)

        initial = read_melodee_settings(root)
        self.assertTrue(initial["success"])
        self.assertTrue(initial["conf_exists"])
        self.assertEqual(initial["start_project"], "/media/sd/Melodee/Projects/Beat01.mldp")
        self.assertEqual(initial["raw_values"]["features"], 1)
        self.assertEqual(initial["raw_values"]["stems_best"], 1)

        updated = update_melodee_settings(
            root,
            updates={
                "audio_rate": 48000, "knob_takeover": 2, "slice_play": 1, "rec_quantize": 0,
                "cv_base": 2, "cv_division": 12, "remote_track_cc": 55, "input_track": 3, "input_tap": 0,
            },
        )
        self.assertTrue(updated["backup_exists"])
        self.assertEqual(updated["raw_values"]["audio_rate"], 48000)
        self.assertEqual(updated["raw_values"]["slice_play"], 1)
        self.assertEqual(updated["raw_values"]["rec_quantize"], 0)
        self.assertEqual(updated["raw_values"]["cv_division"], 12)
        self.assertEqual(updated["raw_values"]["remote_track_cc"], 55)
        self.assertEqual(updated["raw_values"]["input_track"], 3)
        self.assertEqual(updated["raw_values"]["input_tap"], 0)
        conf_text = (root / "Melodee" / "settings").read_text(encoding="utf-8")
        self.assertIn("start=/media/sd/Melodee/Projects/Beat01.mldp", conf_text)
        self.assertIn("last=/media/sd/Melodee/Projects/Beat01.mldp", conf_text)
        self.assertIn("lessons=3", conf_text)
        self.assertIn("favourites2=0,5,12", conf_text)
        self.assertIn("pickup=0", conf_text)

        preset_res = update_melodee_settings(root, preset="streaming_mirror")
        self.assertEqual(preset_res["applied_preset"], "streaming_mirror")
        self.assertEqual(preset_res["raw_values"]["screen_mirror"], 1)
        self.assertEqual(preset_res["raw_values"]["mirror_fps"], 60)

        with self.assertRaises(ValueError):
            update_melodee_settings(root, updates={"audio_rate": 22050})
        with self.assertRaises(ValueError):
            update_melodee_settings(root, updates={"screen": 5})
        with self.assertRaises(ValueError):
            update_melodee_settings(root, updates={"features": True})
        with self.assertRaises(ValueError):
            update_melodee_settings(root, updates="not-a-dict")
        with self.assertRaises(ValueError):
            update_melodee_settings(root, preset="no_existe")
        with self.assertRaises(ValueError):
            update_melodee_settings(root, start_project="/media/sd/bad.txt")

    def test_melodee_sampqol_dual_bridge_and_tree(self):
        from hardware_kit_builder import read_mpcqol_conf, update_melodee_settings, update_mpcqol_conf

        root = Path(self.test_dir) / "dual_bridge"
        (root / "autorun" / "melodee").mkdir(parents=True)
        (root / "autorun" / "melodee" / "sample-base").write_bytes(b"ELF")
        (root / "autorun" / "mpcqol.so").write_bytes(b"QOL")
        (root / "mpcqol.conf").write_text("screenlevel=5\npadlevel=6\nfollow=2\nrearusb=1\nresamplekfx=1\nzerosnap=1\n", encoding="utf-8")

        tree_res = update_melodee_settings(root, action="init_melodee_tree")
        self.assertTrue((root / "Melodee" / "Samples" / "Expansions").is_dir())
        self.assertTrue((root / "Melodee" / "SysEx").is_dir())
        self.assertEqual(tree_res["active_boot"], "dual_autorun")

        sync_in = update_melodee_settings(
            root,
            action="sync_from_sampqol",
            start_project="/media/sd/MPC-Sample/Projects/Retro.xpj",
        )
        self.assertEqual(sync_in["raw_values"]["screen"], 90)
        self.assertEqual(sync_in["raw_values"]["pad_response"], 0)
        self.assertEqual(sync_in["raw_values"]["seq_follow"], 2)
        self.assertEqual(sync_in["raw_values"]["input_source"], 5)
        self.assertEqual(sync_in["raw_values"]["rec_fx"], 1)
        self.assertEqual(sync_in["start_project"], "/media/sd/MPC-Sample/Projects/Retro.xpj")

        sync_out = update_melodee_settings(
            root,
            updates={"screen": 60, "pad_response": 2, "seq_follow": 1, "input_source": 1, "rec_fx": 0, "response_before": 0, "monitor_before_mic": 1},
            action="sync_to_sampqol",
        )
        self.assertIn("screenlevel", sync_out.get("synced_sampqol_keys", []))
        qol_after = read_mpcqol_conf(root)
        self.assertEqual(int(qol_after["raw_values"]["screenlevel"]), 3)
        self.assertEqual(int(qol_after["raw_values"]["padlevel"]), 1)
        self.assertEqual(int(qol_after["raw_values"]["follow"]), 1)
        self.assertEqual(int(qol_after["raw_values"]["rearusb"]), 0)
        self.assertEqual(int(qol_after["raw_values"]["resamplekfx"]), 0)
        self.assertEqual(int(qol_after["raw_values"]["zerosnap"]), 1)

        (root / "Melodee" / "Cache").mkdir(parents=True, exist_ok=True)
        (root / "Melodee" / "Cache" / "temp.f32").write_bytes(b"1234")
        cleared = update_melodee_settings(root, action="clear_cache")
        self.assertEqual(cleared["removed_cache_files"], 1)
        self.assertFalse((root / "Melodee" / "Cache" / "temp.f32").exists())

    def test_hierarchical_key_and_bpm_detection_and_drum_guard(self):
        import math
        from hardware_kit_builder import analyze_kit_key_and_bpm
        from index_mpc_library import extract_key

        def _write_wav(path: Path, samples_list, sr: int = 22050):
            with wave.open(str(path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                clamped = [max(-32767, min(32767, int(v))) for v in samples_list]
                wf.writeframes(struct.pack(f"<{len(clamped)}h", *clamped))

        tmp_kdir = Path(self.test_dir) / "hier_key_bpm"
        tmp_kdir.mkdir(parents=True, exist_ok=True)
        sr = 22050

        # 1) Batería seca pura sin loops melódicos: NO debe inventar C Major ni quedarse en 120 BPM
        dry_kick_pcm = [
            16000.0 * math.exp(-i / 750.0) * math.sin(2.0 * math.pi * (140.0 * math.exp(-i / 600.0) + 42.0) * i / sr)
            for i in range(int(sr * 0.16))
        ]
        dry_snare_pcm = [
            12000.0 * math.exp(-i / 500.0) * math.sin(2.0 * math.pi * 190.0 * i / sr) * (1 if (i % 7) else -1)
            for i in range(int(sr * 0.15))
        ]
        dry_kick_p = tmp_kdir / "Kick_C1_Dry.wav"
        dry_snare_p = tmp_kdir / "Snare_Tight.wav"
        _write_wav(dry_kick_p, dry_kick_pcm, sr)
        _write_wav(dry_snare_p, dry_snare_pcm, sr)

        res_drums = analyze_kit_key_and_bpm(
            "UK Drill Dry Kit",
            [dry_kick_p, dry_snare_p],
            project_tempo=120.0,
            project_key="C Major",
            expansion_hint="UK Drill Pack",
        )
        self.assertEqual(res_drums["musical_key"], "Percussion")
        self.assertEqual(res_drums["key_source"], "atonal_drums")
        self.assertFalse(res_drums["confirmed_by_drums"])
        self.assertEqual(res_drums["bpm"], 142.0)
        self.assertEqual(res_drums["bpm_source"], "genre_inference")

        # extract_key con guardia percusiva no debe marcar Kick_C1 como nota C
        self.assertEqual(extract_key("Kick_C1_Dry.wav", sound_type="KICK"), (None, None))
        self.assertEqual(extract_key("Loop_Dmin_120.wav"), ("Dm", "7A"))

        # 2) Kit mixto con loop melódico largo en A Min a 88 BPM + 808 en A1 (55 Hz):
        #    Nivel 1 detecta A Min + ~88 BPM del loop; Nivel 2 confirma por el 808 en A1
        beat_sec = 60.0 / 88.0
        dur_loop = 3.4
        loop_pcm = []
        for i in range(int(sr * dur_loop)):
            t = i / float(sr)
            beat_pos = (t % beat_sec) / beat_sec
            env = math.exp(-beat_pos * 4.5)
            chord = (
                math.sin(2.0 * math.pi * 220.0 * t)
                + math.sin(2.0 * math.pi * 261.63 * t)
                + math.sin(2.0 * math.pi * 329.63 * t)
            ) / 3.0
            loop_pcm.append(16000.0 * env * chord)
        loop_p = tmp_kdir / "Vintage_Vinyl_Phrase.wav"
        _write_wav(loop_p, loop_pcm, sr)

        bass_808_pcm = [
            18000.0 * math.exp(-i / 18000.0) * math.sin(2.0 * math.pi * 55.0 * i / sr)
            for i in range(int(sr * 0.9))
        ]
        bass_808_p = tmp_kdir / "808_Sub_Deep.wav"
        _write_wav(bass_808_p, bass_808_pcm, sr)

        res_mel = analyze_kit_key_and_bpm(
            "Bolero Lo-Fi Kit",
            [dry_kick_p, bass_808_p, loop_p],
            project_tempo=120.0,
            project_key="C Major",
        )
        self.assertEqual(res_mel["musical_key"], "A Min")
        self.assertEqual(res_mel["key_source"], "melodic_loop")
        self.assertTrue(res_mel["confirmed_by_drums"])
        self.assertLessEqual(abs(res_mel["bpm"] - 88.0), 2.0)

    def test_bolero_long_phrase_autochop_and_expansion_metadata_editor(self):
        import math
        from hardware_kit_builder import (
            autochop_sample_to_16_pads,
            _generate_default_expansion_svg_png,
            update_expansion_metadata,
        )

        # 1. Bolero 26s con silencio inicial y transientes cortos internos NO debe cortar micro-transientes
        sr = 22050
        bolero_path = Path(self.test_dir) / "Bolero_Vintage_Mono.wav"
        n_sil = int(sr * 0.7)
        n_act = int(sr * 25.0)
        pcm = [0] * n_sil
        beat_s = 60.0 / 82.0
        for i in range(n_act):
            t = i / float(sr)
            env = 0.55 + 0.45 * math.exp(-((t % beat_s) / beat_s) * 4.0)
            val = 14000.0 * env * (
                0.5 * math.sin(2.0 * math.pi * 220.0 * t)
                + 0.3 * math.sin(2.0 * math.pi * 329.63 * t)
                + 0.2 * math.sin(2.0 * math.pi * 440.0 * t)
            )
            pcm.append(max(-32767, min(32767, int(val))))
        with wave.open(str(bolero_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(struct.pack(f"<{len(pcm)}h", *pcm))

        chop_auto = autochop_sample_to_16_pads(
            bolero_path,
            self.test_dir,
            max_slices=16,
            kit_name="Bolero_Frases",
            style_hint="Bolero 1950s",
            chop_mode="auto",
        )
        self.assertTrue(chop_auto["success"])
        self.assertEqual(chop_auto["applied_chop_mode"], "phrases")
        self.assertEqual(chop_auto["slices_count"], 16)
        min_dur = min(p["duration_sec"] for p in chop_auto["pads"])
        self.assertGreaterEqual(min_dur, 0.75)

        chop_tr = autochop_sample_to_16_pads(
            bolero_path,
            self.test_dir,
            max_slices=16,
            kit_name="Bolero_Trans",
            chop_mode="transients",
        )
        self.assertGreaterEqual(min(p["duration_sec"] for p in chop_tr["pads"]), 0.65)

        # 2. Portada procedural real 320x320 y editor de expansión
        art_bytes = _generate_default_expansion_svg_png("Bolero Vinyl", "Astro1Deep")
        self.assertTrue(art_bytes.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(art_bytes), 2000)
        ihdr_w, ihdr_h = struct.unpack(">II", art_bytes[16:24])
        self.assertEqual((ihdr_w, ihdr_h), (320, 320))

        exp_dir = Path(self.test_dir) / "Expansions" / "Old_Pack"
        exp_dir.mkdir(parents=True)
        (exp_dir / "Artwork.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 60)  # 70B solid pixel simulado
        (exp_dir / "Expansion.xml").write_text(
            '<?xml version="1.0" encoding="utf-8"?><expansion version="2.0.0.1"><title>Old Pack</title><manufacturer>Test</manufacturer><img>Artwork.png</img></expansion>',
            encoding="utf-8",
        )
        upd = update_expansion_metadata(
            "Expansions/Old_Pack",
            title="New Bolero Pack",
            manufacturer="Astro1Deep",
            description="Editado",
            regenerate_cover=True,
            rename_folder=True,
            source_root=self.test_dir,
        )
        self.assertTrue(upd["success"])
        self.assertTrue(upd["renamed_folder"])
        self.assertEqual(upd["expansion_rel_path"], "Expansions/New Bolero Pack")
        new_art = Path(self.test_dir) / "Expansions" / "New Bolero Pack" / "Artwork.png"
        self.assertGreater(new_art.stat().st_size, 2000)
        tree = ET.parse(str(Path(self.test_dir) / "Expansions" / "New Bolero Pack" / "Expansion.xml"))
        self.assertEqual(tree.findtext("title"), "New Bolero Pack")
        self.assertEqual(tree.findtext("description"), "Editado")

        with self.assertRaises(ValueError):
            update_expansion_metadata("Expansions/../../etc", title="Hack", source_root=self.test_dir)
        with self.assertRaises(ValueError):
            update_expansion_metadata("Expansions/New Bolero Pack", cover_bytes=b"not-an-image-bytes", source_root=self.test_dir)

    def test_camelot_wheel_compatibility_and_spectral_drumless_rubato(self):
        import math
        from hardware_kit_builder import (
            parse_musical_key_info,
            camelot_compatibility_score,
            compute_pitch_shift_to_compatible_key,
            analyze_rhythmic_pattern_and_hiphop_adaptation,
            _compute_hiphop_adaptation_profile,
        )

        k_cm = parse_musical_key_info("C Min")
        self.assertEqual(k_cm["camelot"], "5A")
        self.assertEqual(k_cm["pitch_class"], 0)

        sc_same, _ = camelot_compatibility_score("C Min", "C Min")
        sc_rel, _ = camelot_compatibility_score("C Maj", "A Min")
        sc_fifth, _ = camelot_compatibility_score("C Min", "G Min")
        sc_clash, _ = camelot_compatibility_score("C Min", "F# Min")
        self.assertEqual(sc_same, 1.0)
        self.assertGreaterEqual(sc_rel, 0.90)
        self.assertGreaterEqual(sc_fifth, 0.85)
        self.assertLessEqual(sc_clash, 0.25)

        sem_fix, _ = compute_pitch_shift_to_compatible_key(6, 0)  # F# -> C / G
        self.assertEqual(abs(sem_fix), 1)  # +1 semitone lands cleanly on fifth G (7)

        prof_warp = _compute_hiphop_adaptation_profile("lofi_chill", "Lo-Fi", 120.0, 80.0)
        self.assertTrue(prof_warp["formant_warning"])
        self.assertEqual(prof_warp["recommended_mode"], "mpc_warp_0st")
        self.assertAlmostEqual(prof_warp["vinyl_repitch_bpm"], 120.0 * (2.0 ** (prof_warp["repitch_semitones"] / 12.0)), delta=0.5)

        # Pad sostenido rubato sin batería -> detecta is_drumless + is_rubato
        sr = 22050
        rub_path = Path(self.test_dir) / "Unknown_Warm_Sustained_Pad.wav"
        n_s = int(sr * 5.0)
        pcm = []
        for i in range(n_s):
            t = i / float(sr)
            amp = 10000.0 * (0.65 + 0.35 * math.sin(2.0 * math.pi * 0.3 * t))
            v = amp * (0.6 * math.sin(2.0 * math.pi * 261.63 * t) + 0.4 * math.sin(2.0 * math.pi * 392.0 * t))
            pcm.append(max(-32767, min(32767, int(v))))
        with wave.open(str(rub_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(struct.pack(f"<{len(pcm)}h", *pcm))

        rhy = analyze_rhythmic_pattern_and_hiphop_adaptation(rub_path, style_hint="Alchemist 78")
        ra = rhy["rhythm_analysis"]
        self.assertTrue(ra["is_drumless"])
        self.assertIn("crest_db", ra)
        self.assertIn("centroid_hz", ra)
        self.assertIsInstance(ra["mix_eq_advice"], list)

    def test_anti_clipping_float32_key_f0_separation_and_mmr_3bank_48(self):
        import math
        from hardware_kit_builder import (
            _master_pcm_float32_anti_clip,
            _build_harmonic_transposition_info,
            analyze_sample_acoustics,
            autochop_sample_to_16_pads,
        )

        # 1. Cadena float32 anti-clipping: pico +2.8 dBFS + DC offset -> <= -0.80 dBFS + DC eliminado + fade coseno
        sr = 44100
        overshoot_gain = 10.0 ** (2.8 / 20.0)
        raw_f32 = [0.18 + overshoot_gain * math.sin(2.0 * math.pi * 220.0 * (i / sr)) for i in range(4410)]
        mastered = _master_pcm_float32_anti_clip(
            [raw_f32],
            sample_rate=sr,
            target_peak_dbfs=-0.80,
            apply_hpf_24hz=True,
            only_attenuate_above_ceiling=True,
            fade_in_ms=2.0,
            fade_out_ms=8.0,
        )
        self.assertEqual(len(mastered), len(raw_f32))
        peak_db = 20.0 * math.log10(max(abs(x) for x in mastered) / 32767.0)
        self.assertLessEqual(peak_db, -0.78)
        self.assertLess(abs(sum(mastered) / float(len(mastered))) / 32767.0, 0.005)
        self.assertLessEqual(abs(mastered[0]), 4)
        self.assertLessEqual(abs(mastered[-1]), 4)

        # 2. Bug #1 fix: separar tonalidad global (F Maj) de nota F0 (A#4) tras -2 semitonos
        wav_bug1 = Path(self.test_dir) / "Soul_Loop_F_Maj.wav"
        n_s = int(sr * 2.5)
        pcm_b1 = [int(14000.0 * math.sin(2.0 * math.pi * 466.1638 * (i / sr))) for i in range(n_s)]  # A#4 = 466.16 Hz
        with wave.open(str(wav_bug1), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(struct.pack(f"<{len(pcm_b1)}h", *pcm_b1))

        ac_b1 = analyze_sample_acoustics(wav_bug1)
        self.assertFalse(ac_b1["clipping_risk"])
        self.assertIn("dc_offset_warning", ac_b1)
        self.assertIn("overcompressed_risk", ac_b1)

        hinfo = _build_harmonic_transposition_info(wav_bug1, -2)
        self.assertEqual(hinfo["original_key"], "F Maj")
        self.assertEqual(hinfo["transposed_key"], "D# Maj")
        self.assertEqual(hinfo["original_note"], "A#4")
        self.assertEqual(hinfo["transposed_note"], "G#4")  # nunca D#4 mezclando Key + octava F0

        # 3. Modo mmr_3bank_48 sobre pista melódica multi-acorde -> Bancos A/B/C, pico <= -0.80 dBFS
        wav_bol = Path(self.test_dir) / "Bolero_MultiChord_Test.wav"
        n_b = int(sr * 18.0)
        beat_sec = 60.0 / 82.0
        pcm_bol = []
        chords = [(220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (196.0, 246.94, 293.66), (164.81, 207.65, 246.94)]
        for i in range(n_b):
            t = i / float(sr)
            ch = chords[int(t / (beat_sec * 4.0)) % len(chords)]
            env = 0.5 + 0.5 * math.exp(-((t % beat_sec) / beat_sec) * 3.5)
            val = 15000.0 * env * (0.45 * math.sin(2.0 * math.pi * ch[0] * t) + 0.30 * math.sin(2.0 * math.pi * ch[1] * t) + 0.25 * math.sin(2.0 * math.pi * ch[2] * t))
            pcm_bol.append(max(-32767, min(32767, int(val))))
        with wave.open(str(wav_bol), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(struct.pack(f"<{len(pcm_bol)}h", *pcm_bol))

        chop_48 = autochop_sample_to_16_pads(
            wav_bol,
            self.test_dir,
            max_slices=48,
            kit_name="Bolero_3Bank",
            style_hint="Bolero Vintage 82",
            chop_mode="mmr_3bank_48",
        )
        self.assertTrue(chop_48["success"])
        self.assertEqual(chop_48["applied_chop_mode"], "mmr_3bank_48")
        self.assertGreater(chop_48["slices_count"], 16)
        banks_seen = {p.get("bank") for p in chop_48["pads"]}
        self.assertEqual(banks_seen, {"A", "B", "C"})
        self.assertTrue(all(p["peak_dbfs"] <= -0.75 for p in chop_48["pads"]))
        self.assertGreaterEqual(min(p["duration_sec"] for p in chop_48["pads"]), 0.45)

    def test_15_xpj_tempo_flags_pad_role_colors_and_euclidean_pattern(self):
        import gzip
        import json
        from hardware_kit_builder import generate_euclidean_mpc_pattern

        pads = {
            1: {"sample_name": "Punch_Kick", "sample_path": self.sample_files[0], "sound_type": "KICK"},
            2: {"sample_name": "Crisp_Snare", "sample_path": self.sample_files[1], "sound_type": "SNARE"},
            3: {"sample_name": "Sub_808", "sample_path": self.sample_files[2], "sound_type": "BASS_808"},
        }
        xpj_path = Path(export_mpc_project("ColorTempoKit", pads, self.test_dir, tempo=94.5, key="A Minor"))
        raw = gzip.open(str(xpj_path), "rb").read()
        lines = raw.split(b"\n", 5)
        self.assertEqual([x.decode() for x in lines[:5]], ["ACVS", "1.3.0.12", "SerialisableProjectData", "json", "Linux"])
        data = json.loads(lines[5])["data"]
        self.assertEqual(data["masterTempo"], 94.5)
        self.assertTrue(data["masterTempoEnabled"])
        self.assertEqual(data["currentSequence"], 0)
        for seq in data["sequences"]:
            sv = seq["value"]
            self.assertEqual(sv["bpm"], 94.5)
            self.assertTrue(sv["tempoEnable"])
        pp = data["tracks"][0]["program"]["programPads"]
        self.assertFalse(pp["Universal"]["value0"])
        self.assertEqual(pp["Type"]["value0"], 5)
        self.assertNotEqual(pp["pads"]["value0"], 0)
        self.assertNotEqual(pp["pads"]["value1"], 0)
        self.assertNotEqual(pp["pads"]["value0"], pp["pads"]["value1"])
        self.assertEqual(pp["pads"]["value15"], 0)

        pat_bb = generate_euclidean_mpc_pattern("boombap", bpm=92.0, bars=2)
        self.assertTrue(pat_bb["success"])
        self.assertEqual(pat_bb["swing_unit"], 1)
        self.assertEqual(pat_bb["tracks"][0]["euclidean"], "E(4,16)")
        pat_old = generate_euclidean_mpc_pattern("oldies", bpm=74.0, bars=1)
        self.assertEqual(pat_old["swing_unit"], 2)
        self.assertEqual(pat_old["meter"], "12/8")


if __name__ == "__main__":
    unittest.main()
