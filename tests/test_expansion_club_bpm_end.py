"""Regression tests for [BPM] inference and Expansion SliceEnd / BPM / club_clean normalization."""
from __future__ import annotations

import copy
import gzip
import json
import sys
import tempfile
import unittest
import wave
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import hardware_kit_builder as hkb
from scripts import normalize_expansions_club_bpm_end as norm


def _make_wav(path: Path, n_frames: int, sr: int = 44100) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(b"\x00\x00\x00\x00" * n_frames)


def _make_acvs_xpj(path: Path, sample_files: list[str], *, master_tempo: float = 90.0, slice_end: int = 300000, with_events: bool = False, mute_group: int = 0) -> None:
    tpl_raw = gzip.decompress((ROOT / "templates" / "template_project.xpj").read_bytes()).decode("utf-8")
    jidx = tpl_raw.index("{")
    hdr = tpl_raw[:jidx]
    payload = json.loads(tpl_raw[jidx:])
    data = payload["data"]
    data["masterTempo"] = float(master_tempo)
    seq = data["sequences"][0]["value"]
    seq["bpm"] = float(master_tempo)
    if with_events:
        tname = data["tracks"][0]["name"]
        seq["trackClipMaps"][0][0]["key"] = tname
        seq["trackClipMaps"][0][0]["value"]["name"] = tname
        seq["trackClipMaps"][0][0]["value"]["eventList"]["events"] = [{"time": 0, "type": 3, "note": {"note": 36, "velocity": 1.0, "length": 240}}]

    trk = data["tracks"][0]
    insts = trk["program"]["drum"]["instruments"]
    for idx, sf in enumerate(sample_files):
        inst = insts[idx]
        inst["whichMuteGroup"] = int(mute_group)
        inst["mixable"]["muteGroup"] = int(mute_group)
        lay = inst["layersv"][0]
        lay["active"] = True
        lay["sampleFile"] = sf
        lay["sampleName"] = Path(sf).stem
        lay["sliceInfo"]["Start"] = 0
        lay["sliceInfo"]["End"] = int(slice_end)
    data["samples"] = [{"version": 1, "name": Path(sf).stem, "path": sf, "loadImpl": 0, "metadata": {"tempo": 0.0, "rootNote": 60, "tune": 0.0, "key": "C Major"}} for sf in sample_files]
    trk["samples"] = copy.deepcopy(data["samples"])

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress((hdr + json.dumps(payload, indent=0)).encode("utf-8"), mtime=0))


def _make_xpm(path: Path, sample_specs: list[tuple[str, int, int, int]], *, ptype: str = "Drum") -> None:
    tree = ET.parse(str(ROOT / "templates" / "template_drum.xpm"))
    root = tree.getroot()
    prog = root.find("Program")
    prog.attrib["type"] = ptype
    insts = prog.findall("./Instruments/Instrument")
    for idx, (sf, ss, se, mg) in enumerate(sample_specs):
        inst = insts[idx]
        inst.find("MuteGroup").text = str(mg)
        lay = inst.find("./Layers/Layer")
        lay.find("Active").text = "True"
        lay.find("SampleFile").text = sf
        lay.find("SampleName").text = Path(sf).stem
        lay.find("SliceStart").text = str(ss)
        lay.find("SliceEnd").text = str(se)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))


class ExpansionClubBpmEndTests(unittest.TestCase):
    def test_extract_explicit_bpm_supports_brackets_and_legacy(self):
        self.assertEqual(hkb._extract_explicit_bpm_from_text("HipHop-Stem-Combo[156] G 1974 1.wav"), 156.0)
        self.assertEqual(hkb._extract_explicit_bpm_from_text("R&B-Stem-Bass[89] A Brinks.wav"), 89.0)
        self.assertEqual(hkb._extract_explicit_bpm_from_text("13 45_Lo-Fi_Piano_Bmaj_90BPM001.wav"), 90.0)
        with tempfile.TemporaryDirectory() as td:
            pd = Path(td) / "HipHop-Kit-1974_[ProjectData]"
            _make_wav(pd / "HipHop-Stem-Combo[156] G 1974.wav", 1000)
            _make_wav(pd / "HipHop-Kick-Kick 1974 1.wav", 1000)
            xpj = Path(td) / "HipHop-Kit-1974.xpj"
            self.assertEqual(hkb.infer_kit_bpm(xpj), 156.0)

    def test_normalize_card_fixes_slice_end_bpm_and_club_clean(self):
        with tempfile.TemporaryDirectory() as td:
            card = Path(td)
            pack = card / "Expansions" / "DJ Khalil (AKAINI)"
            pdata = pack / "HipHop-Kit-1974_[ProjectData]"
            samples = [
                ("HipHop-Kick-Kick 1974 1.wav", 85851),
                ("HipHop-Snare-Snare 1974 1.wav", 83092),
                ("HipHop-Hat-ClosedHH 1974.wav", 20251),
                ("Bass-808-Sub 1974.wav", 110000),
                ("HipHop-Tom-FloorTom 1974.wav", 70208),
                ("HipHop-Stem-Combo[156] G 1974 1.wav", 666709),
            ]
            for fn, nf in samples:
                _make_wav(pdata / fn, nf)
                _make_wav(pack / fn, nf)

            xpj = pack / "HipHop-Kit-1974.xpj"
            xpm = pack / "HipHop-Kit-1974.xpm"
            _make_acvs_xpj(xpj, [s[0] for s in samples], master_tempo=90.0, slice_end=300000, with_events=False, mute_group=0)
            _make_xpm(xpm, [(s[0], 0, 300000, 0) for s in samples], ptype="Drum")

            # Also add a Keygroup with intentional shorter end and a demo with MIDI events
            kg_dir = card / "Expansions" / "F9 Instruments Beats Edition"
            _make_wav(kg_dir / "WarmPad-048 C2.wav", 432180)
            _make_xpm(kg_dir / "WarmPad.xpm", [("WarmPad-048 C2.wav", 0, 383700, 0)], ptype="Keygroup")

            midi_pack = card / "Expansions" / "MPC Beats Demos and Templates"
            _make_wav(midi_pack / "Pop_[ProjectData]" / "Loop130.wav", 200000)
            _make_acvs_xpj(midi_pack / "Pop.xpj", ["Loop130.wav"], master_tempo=100.0, slice_end=200000, with_events=True, mute_group=3)

            res = norm.normalize_card(card, dry_run=False)
            self.assertEqual(res["stats"]["errors"], 0)

            # Verify XPJ repaired
            raw_txt = gzip.decompress(xpj.read_bytes()).decode("utf-8")
            self.assertTrue(raw_txt.startswith(norm.ACVS_HEADER))
            self.assertIn('"masterTempo": 156.0', raw_txt)
            doc = json.loads(raw_txt[raw_txt.index("{"):])["data"]
            self.assertEqual(doc["sequences"][0]["value"]["bpm"], 156.0)
            insts = doc["tracks"][0]["program"]["drum"]["instruments"]
            for idx, (fn, nf) in enumerate(samples):
                self.assertEqual(insts[idx]["layersv"][0]["sliceInfo"]["End"], nf)
            expected_mg = [1, 1, 2, 4, 5, 0]
            self.assertEqual([insts[i]["whichMuteGroup"] for i in range(6)], expected_mg)
            self.assertEqual([insts[i]["mixable"]["muteGroup"] for i in range(6)], expected_mg)

            # Verify XPM repaired
            xroot = ET.parse(str(xpm)).getroot()
            xinsts = xroot.findall("./Program/Instruments/Instrument")
            for idx, (fn, nf) in enumerate(samples):
                self.assertEqual(xinsts[idx].findtext("./Layers/Layer/SliceEnd"), str(nf))
                self.assertEqual(xinsts[idx].findtext("MuteGroup"), str(expected_mg[idx]))

            # Verify intentional Keygroup trim & MIDI Demo sequence untouched
            kroot = ET.parse(str(kg_dir / "WarmPad.xpm")).getroot()
            self.assertEqual(kroot.findtext("./Program/Instruments/Instrument/Layers/Layer/SliceEnd"), "383700")
            self.assertEqual(kroot.findtext("./Program/Instruments/Instrument/MuteGroup"), "0")

            m_doc = json.loads(gzip.decompress((midi_pack / "Pop.xpj").read_bytes()).decode("utf-8").split("\n", 5)[5])["data"]
            self.assertEqual(m_doc["masterTempo"], 100.0)
            self.assertEqual(m_doc["tracks"][0]["program"]["drum"]["instruments"][0]["whichMuteGroup"], 3)

            # Verify backup created & idempotent 2nd run
            self.assertTrue((card / "_RAW_SOURCE_ARCHIVES/pre_club_bpm_end_20261121/Expansions/DJ Khalil (AKAINI)/HipHop-Kit-1974.xpj").is_file())
            res2 = norm.normalize_card(card, dry_run=True)
            self.assertEqual(res2["stats"]["xpm_updated"], 0)
            self.assertEqual(res2["stats"]["xpj_updated"], 0)


if __name__ == "__main__":
    unittest.main()
