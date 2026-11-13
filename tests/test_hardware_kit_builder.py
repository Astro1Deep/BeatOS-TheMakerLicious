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


if __name__ == "__main__":
    unittest.main()
