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
)

class TestHardwareKitBuilder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = Path(tempfile.mkdtemp(prefix="beatos_test_"))
        
        # Create 4 dummy audio files
        cls.sample_files = []
        for i in range(1, 5):
            p = cls.test_dir / f"test_sample_{i}.wav"
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
        
        # Validate gzip JSON schema
        with gzip.open(xpj_path, "rt", encoding="utf-8") as gz:
            data = json.load(gz)
        self.assertEqual(data["formatVersion"], "2.0")
        self.assertEqual(data["programType"], "Drum")
        self.assertEqual(data["tempo"], 92.0)

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
        self.assertEqual(len(meta["sounds"]), 16)
        
        # Verify .pak is a valid zip archive
        self.assertTrue(zipfile.is_zipfile(pak_path))
        with zipfile.ZipFile(pak_path, "r") as z:
            names = z.namelist()
            self.assertIn("meta.json", names)
            self.assertTrue(any(n.startswith("sounds/") for n in names))

    def test_07_export_po33_drum_reel(self):
        out_dir = self.test_dir / "out_po33"
        reel_path, total_dur, slices = export_po33_drum_reel("TestReel_PO33", self.pads_data, out_dir)
        self.assertTrue(Path(reel_path).exists())
        self.assertGreater(total_dur, 0.0)
        self.assertEqual(len(slices), 4)
        
        # Check audio properties of concatenated strip
        with wave.open(reel_path, "rb") as wf:
            self.assertEqual(wf.getnchannels(), 1)
            self.assertEqual(wf.getsampwidth(), 2)
            self.assertEqual(wf.getframerate(), 44100)

if __name__ == "__main__":
    unittest.main()
