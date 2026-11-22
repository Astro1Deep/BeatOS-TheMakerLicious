#!/usr/bin/env python3
"""
Unit tests for Boom Bap v2 Bolero & Ranchera Structural Slicer, Beat-1 Bass+Chord
Downbeat Phase Lock, Asymmetric Backward Zero-Crossing, and Akai MPC `atem` + `slic`
WAV Chunk Embedding.
"""

from __future__ import annotations

import gzip
import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import soundfile as sf

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import repair_mpc_expansions as rme  # noqa: E402
from reorganize_samples_and_bolero_templates import (  # noqa: E402
    SR_TARGET,
    _parse_bolero_filename,
    _snap_zero_crossing_backward,
    _write_boombap_wav_16bit,
    analyze_boombap_bolero,
    embed_mpc_atem_slic,
    read_mpc_atem_slic,
    stage_rebuild_bolero_structural_templates,
)


def _synth_bolero_track(
    sr: int = SR_TARGET,
    bpm: float = 76.0,
    meter: int = 4,
    total_bars: int = 24,
) -> tuple[np.ndarray, list[int]]:
    """
    Synthesize a realistic 1950s Bolero (4/4) or Ranchera/Vals (3/4) track:
      - Beat 1 of every bar: deep contrabajo / guitarron fundamental pluck (55..87 Hz)
        + chord change every 4 bars (Am -> Dm -> E7 -> Am -> F -> E7)
      - Beats 2..meter: high-frequency guitar offbeat strums (1200..3500 Hz) that are
        brighter in HF spectral flux than Beat 1 (testing that our Beat-1 Bass+Chord
        estimator locks onto Beat 1 instead of the guitar offbeats!)
      - Bars 0..8: Instrumental Requinto + Bass (clean harmonic sustain)
      - Bars 8..16: Vocal Bolero Melody with 5.6 Hz vibrato in 350..2800 Hz band
      - Bars 16..24: Instrumental Outro + Guitar Turnaround
    Returns `(y_mono, true_bar_downbeat_samples)`.
    """
    beat_sec = 60.0 / bpm
    bar_sec = beat_sec * meter
    total_sec = total_bars * bar_sec + 0.5
    n_samples = int(round(total_sec * sr))
    y = np.zeros(n_samples, dtype=np.float32)

    chord_sequence = [
        (55.0, [220.0, 261.63, 329.63]),   # Am (bars 0..4)
        (73.42, [293.66, 349.23, 440.0]),  # Dm (bars 4..8)
        (82.41, [329.63, 415.30, 493.88]), # E7 (bars 8..12)
        (55.0, [220.0, 261.63, 329.63]),   # Am (bars 12..16)
        (87.31, [349.23, 440.0, 523.25]),  # F  (bars 16..20)
        (82.41, [329.63, 415.30, 493.88]), # E7 (bars 20..24)
    ]

    downbeat_samples: list[int] = []
    t_offset = 0.08  # 80 ms initial vinyl lead-in

    for bar in range(total_bars):
        chord_idx = (bar // 4) % len(chord_sequence)
        bass_f0, triad = chord_sequence[chord_idx]
        bar_t0 = t_offset + bar * bar_sec
        s_bar = int(round(bar_t0 * sr))
        downbeat_samples.append(s_bar)

        for beat in range(meter):
            bt_t0 = bar_t0 + beat * beat_sec
            s0 = int(round(bt_t0 * sr))
            dur_s = int(round(min(beat_sec * 0.92, 0.70) * sr))
            s1 = min(n_samples, s0 + dur_s)
            if s1 <= s0:
                continue
            t_local = np.arange(s1 - s0, dtype=np.float32) / float(sr)
            atk = np.minimum(1.0, t_local / 0.003)

            if beat == 0:
                # Beat 1: Contrabajo / Guitarron pluck + warm chord change attack
                env_bass = atk * np.exp(-3.2 * t_local)
                bass_sig = (
                    0.55 * np.sin(2.0 * np.pi * bass_f0 * t_local)
                    + 0.28 * np.sin(2.0 * np.pi * (2.0 * bass_f0) * t_local)
                ) * env_bass
                env_chord = atk * np.exp(-2.2 * t_local)
                chord_sig = sum(
                    0.16 * np.sin(2.0 * np.pi * f * t_local) for f in triad
                ) * env_chord
                y[s0:s1] += (bass_sig + chord_sig).astype(np.float32)
            else:
                # Beats 2..meter: Offbeat high-frequency guitar strum (minimal bass, same chord)
                env_strum = atk * np.exp(-9.0 * t_local)
                strum_sig = sum(
                    0.11 * np.sin(2.0 * np.pi * (f * 2.0) * t_local)
                    + 0.06 * np.sin(2.0 * np.pi * (f * 4.0) * t_local)
                    for f in triad
                ) * env_strum
                y[s0:s1] += strum_sig.astype(np.float32)

        # Add vocal melody with 5.6 Hz vibrato in middle section (bars 8..16)
        if 8 <= bar < 16:
            s_end = min(n_samples, int(round((bar_t0 + bar_sec) * sr)))
            t_bar = np.arange(s_end - s_bar, dtype=np.float32) / float(sr)
            vib_phase = 2.0 * np.pi * 5.6 * t_bar
            inst_freq = 440.0 + 28.0 * np.sin(vib_phase)
            phase = 2.0 * np.pi * np.cumsum(inst_freq) / float(sr)
            am_env = (0.65 + 0.30 * np.sin(vib_phase)) * np.minimum(1.0, t_bar / 0.04)
            vox_sig = (
                0.34 * np.sin(phase)
                + 0.22 * np.sin(2.0 * phase)
                + 0.14 * np.sin(3.0 * phase)
            ) * am_env
            y[s_bar:s_end] += vox_sig.astype(np.float32)

    peak = float(np.max(np.abs(y)))
    if peak > 0:
        y = (y / peak * 0.85).astype(np.float32)
    return y, downbeat_samples


class TestBoomBapBoleroSlicer(unittest.TestCase):
    def test_embed_and_read_mpc_atem_slic_roundtrip(self) -> None:
        """Verify bit-exact Akai MPC `atem` JSON + `slic` binary WAV chunks."""
        with tempfile.TemporaryDirectory() as tmp:
            wav_path = Path(tmp) / "test_chop.wav"
            n_frames = SR_TARGET * 4  # 4 seconds = 176,400 frames
            t = np.arange(n_frames, dtype=np.float32) / float(SR_TARGET)
            y = (0.5 * np.sin(2.0 * np.pi * 220.0 * t)).astype(np.float32)

            # Build 16 touching slices covering [0, n_frames - 1]
            step = n_frames // 16
            slices: list[tuple[int, int]] = []
            for i in range(16):
                s0 = i * step
                s1 = (n_frames - 1) if i == 15 else ((i + 1) * step)
                slices.append((s0, s1))

            pk = _write_boombap_wav_16bit(wav_path, y, seed=12345)
            self.assertLessEqual(pk, 0.915)
            embed_mpc_atem_slic(
                wav_path,
                slices,
                num_bars=4,
                note_sharp="Bb",  # Must normalize to sharp notation "A#"
                scale_name="Natural Minor",
            )

            info = read_mpc_atem_slic(wav_path)
            self.assertTrue(info["riff_size_ok"], "RIFF header size must equal file_size - 8")
            self.assertTrue(info["atem_even_size"], "atem chunk size must always be even for ACVS 1.3.0.12")
            self.assertEqual(info["smpl_size"], 94, "Akai smpl chunk must be 94 bytes")
            self.assertEqual(info["meta_size"], 4, "Akai meta chunk must be 4 bytes")
            self.assertEqual(info["chunk_order"], ["fmt ", "atem", "slic", "smpl", "meta", "data"])

            atem = info["atem"]
            self.assertIsNotNone(atem)
            self.assertEqual(atem["version"], 1)
            v0 = atem["value0"]
            self.assertEqual(v0["numBars"], 4)
            self.assertEqual(v0["Num slices"], 16)
            self.assertEqual(v0["defaultSlice"]["LoopCrossfadeLength"], -1)
            prev_pulse = -1
            for i, (exp_s0, exp_s1) in enumerate(slices):
                sk = v0[f"Slice {i}"]
                self.assertEqual(sk["Start"], exp_s0)
                self.assertEqual(sk["End"], exp_s1)
                self.assertEqual(sk["LoopStart"], exp_s0)
                self.assertGreater(sk["PulsePosition"], prev_pulse)
                prev_pulse = sk["PulsePosition"]
            self.assertEqual(atem["value1"]["note"], "A#")
            self.assertEqual(atem["value1"]["scale"], "Natural Minor")

            # Verify binary slic chunk (16 slices)
            self.assertEqual(info["slic_header"], (1, 16, 0))
            self.assertEqual(len(info["slic_slices"]), 16)
            for (got_s0, got_s1, got_loop, got_pad), (exp_s0, exp_s1) in zip(info["slic_slices"], slices):
                self.assertEqual(got_s0, exp_s0)
                self.assertEqual(got_s1, exp_s1)
                self.assertEqual(got_loop, exp_s0)
                self.assertEqual(got_pad, 0)

            # Verify soundfile still decodes all 176,400 audio frames cleanly
            y_read, sr_read = sf.read(str(wav_path), dtype="float32")
            self.assertEqual(sr_read, SR_TARGET)
            self.assertEqual(len(y_read), n_frames)
            self.assertLessEqual(float(np.max(np.abs(y_read))), 0.915)

    def test_asymmetric_backward_zero_crossing(self) -> None:
        """Verify `_snap_zero_crossing_backward` prefers pre-attack zero crossing over post-attack."""
        y = np.ones(1000, dtype=np.float32) * 0.4
        # Place a backward zero-crossing at -30 samples and a forward one at +20 samples
        # Because forward penalty is 2x (20 * 2 = 40 > 30), it must pick the backward crossing at 470!
        y[469] = -0.05
        y[470] = 0.02
        y[519] = -0.05
        y[520] = 0.01
        snapped = _snap_zero_crossing_backward(y, 500, back_samples=220, ahead_samples=44)
        self.assertEqual(snapped, 470)

    def test_analyze_boombap_bolero_4_4_and_3_4(self) -> None:
        """Verify Beat-1 Bass+Chord phase lock, 4/8-bar DP sections, Inst vs Vox, and Boom Bap loops."""
        with tempfile.TemporaryDirectory() as tmp:
            for idx, (meter, bpm, total_bars) in enumerate([(4, 76, 24), (3, 81, 24)], 1):
                fname = f"Astro1Deep - 0{idx} Test Song {idx} [Am {bpm}BPM {meter}-4 Mono].wav"
                wav_path = Path(tmp) / fname
                y, true_downbeats = _synth_bolero_track(SR_TARGET, bpm=float(bpm), meter=meter, total_bars=total_bars)
                sf.write(str(wav_path), y, SR_TARGET, subtype="PCM_16")
                meta = _parse_bolero_filename(fname)

                _y_out, bpm_est, sections, boombap_loops, _beats, _d, _atk = analyze_boombap_bolero(wav_path, meta)

                self.assertAlmostEqual(bpm_est, float(bpm), delta=3.0)
                self.assertGreaterEqual(len(sections), 3)
                self.assertLessEqual(len(sections), 9)

                # Interior sections must be 4 or 8 bars
                for sec in sections[:-1]:
                    self.assertIn(sec["bars"], (4, 8), f"Interior section must be 4 or 8 bars, got {sec['bars']}")

                # Verify that section start cuts snap near real Beat-1 downbeats (never Beat 2/3 offbeats!)
                beat_samples = int(round((60.0 / float(bpm)) * SR_TARGET))
                errors_ms: list[float] = []
                for sec in sections[:-1]:
                    s0 = sec["s0"]
                    nearest_db = min(true_downbeats, key=lambda db: abs(db - s0))
                    err_ms = abs(s0 - nearest_db) * 1000.0 / float(SR_TARGET)
                    errors_ms.append(err_ms)
                    self.assertLess(abs(s0 - nearest_db), beat_samples * 0.30)
                self.assertLess(float(np.median(errors_ms)), 35.0)

                # Verify both Inst and Vox sections or Inst detection
                vox_tags = {s["vox_tag"] for s in sections}
                self.assertIn("Inst", vox_tags)

                # Verify 3..6 non-overlapping Boom Bap loops with embedded slices
                self.assertGreaterEqual(len(boombap_loops), 3)
                self.assertLessEqual(len(boombap_loops), 6)
                for lp in boombap_loops:
                    self.assertIn(lp["bars"], (2, 4))
                    self.assertGreaterEqual(len(lp["slices"]), 6)

    def test_stage_rebuild_bolero_structural_templates_end_to_end(self) -> None:
        """Verify end-to-end Bank C Chop Template (.xpm + .xpj + WAV atem/slic) generation."""
        with tempfile.TemporaryDirectory() as tmp:
            card = Path(tmp)
            exp_root = card / "Expansions" / "Astro1Deep - Bolero & Ranchera 1950s (Mono Vinyl)"
            full_dir = exp_root / "01_Full_Tracks_Mono_44k"
            full_dir.mkdir(parents=True, exist_ok=True)

            # Create 1 synthetic 32-bar 4/4 Bolero full track in 01_Full_Tracks_Mono_44k
            fname = "Astro1Deep - 01 Besame Mucho [Dm 76BPM 4-4 Mono].wav"
            y, _ = _synth_bolero_track(SR_TARGET, bpm=76.0, meter=4, total_bars=32)
            track_path = full_dir / fname
            sf.write(str(track_path), y, SR_TARGET, subtype="PCM_16")

            tpl = rme.AcvsTemplateLoader()
            report = stage_rebuild_bolero_structural_templates(card, tpl)
            self.assertEqual(report["songs_processed"], 1)
            self.assertGreaterEqual(report["total_sections"], 3)
            self.assertGreaterEqual(report["total_loops"], 3)
            self.assertLessEqual(report["max_peak_dbfs"], -0.78)

            meta = _parse_bolero_filename(fname)
            tstem = meta["stem"]

            # 1. Verify all section WAVs and Boom Bap loop WAVs have valid atem + slic chunks
            sec_dir = exp_root / "02_Song_Sections" / tstem
            sec_wavs = sorted(sec_dir.glob("*.wav"))
            loop_wavs = sorted((sec_dir / "BoomBap_Loops").glob("*.wav"))
            self.assertEqual(len(sec_wavs), report["total_sections"])
            self.assertEqual(len(loop_wavs), report["total_loops"])

            for w in sec_wavs + loop_wavs:
                winfo = read_mpc_atem_slic(w)
                self.assertTrue(winfo["riff_size_ok"], f"RIFF size mismatch in {w.name}")
                self.assertTrue(winfo["atem_even_size"], f"atem chunk size must be even in {w.name}")
                self.assertEqual(winfo["smpl_size"], 94, f"Missing 94-byte smpl in {w.name}")
                self.assertEqual(winfo["meta_size"], 4, f"Missing 4-byte meta in {w.name}")
                self.assertIsNotNone(winfo["atem"], f"Missing atem in {w.name}")
                self.assertGreaterEqual(len(winfo["slic_slices"]), 6, f"Missing slic slices in {w.name}")

            # 2. Verify C16 Full Track WAV in _[ProjectData] has embedded structural section slices
            tpl_dir = exp_root / "03_Chop_Templates" / tstem
            pdata_dir = tpl_dir / f"{tstem}_[ProjectData]"
            c16_wavs = list(pdata_dir.glob("16_C16_Full_*.wav"))
            self.assertEqual(len(c16_wavs), 1)
            c16_info = read_mpc_atem_slic(c16_wavs[0])
            self.assertTrue(c16_info["riff_size_ok"])
            self.assertIsNotNone(c16_info["atem"])
            self.assertEqual(c16_info["atem"]["value0"]["Num slices"], report["total_sections"])

            # 3. Verify .xpm program layout: Bank A (1..16) & Bank B (17..32) EMPTY, Bank C (33..48) populated
            xpm_path = tpl_dir / f"{tstem}.xpm"
            self.assertTrue(xpm_path.is_file())
            self.assertGreater(xpm_path.stat().st_size, 900_000)

            root = ET.fromstring(xpm_path.read_text(encoding="utf-8"))
            inst_by_num = {
                int(inst.attrib["number"]): inst
                for inst in root.findall(".//Instruments/Instrument")
            }

            # Banks A and B (1..32) MUST have empty SampleName
            for pad_num in range(1, 33):
                sn = (inst_by_num[pad_num].findtext(".//Layer/SampleName") or "").strip()
                self.assertEqual(sn, "", f"Pad {pad_num} (Bank A/B) must be strictly empty, got {sn!r}")

            # Bank C C01..C09 (33..41): populated with sections (OneShot=True + MuteGroup=1)
            self.assertNotEqual((inst_by_num[33].findtext(".//Layer/SampleName") or "").strip(), "")
            self.assertEqual(inst_by_num[33].findtext("MuteGroup"), "1")
            self.assertEqual(inst_by_num[33].findtext("Mono"), "True")
            self.assertEqual(inst_by_num[33].findtext("OneShot"), "True")

            # Bank C C10 (Pad 42): populated with first Boom Bap Loop
            c10_sn = (inst_by_num[42].findtext(".//Layer/SampleName") or "").strip()
            self.assertTrue(c10_sn.startswith("10_Loop1_"), f"Unexpected C10 SampleName: {c10_sn!r}")

            # Bank C C16 (Pad 48): populated with Full Track
            c16_sn = (inst_by_num[48].findtext(".//Layer/SampleName") or "").strip()
            self.assertTrue(c16_sn.startswith("16_C16_Full_"))

            # 4. Verify .xpj is valid ACVS 1.3.0.12 gzip JSON with Banks A & B clear
            xpj_path = tpl_dir / f"{tstem}.xpj"
            self.assertTrue(xpj_path.is_file())
            raw_xpj = gzip.decompress(xpj_path.read_bytes())
            lines = raw_xpj.split(b"\n", 5)
            self.assertEqual(lines[0], b"ACVS")
            self.assertEqual(lines[1], b"1.3.0.12")
            payload = json.loads(lines[5].decode("utf-8"))
            insts = payload["data"]["tracks"][0]["program"]["drum"]["instruments"]
            for idx in range(32):
                self.assertEqual(
                    insts[idx]["layersv"][0]["sampleName"],
                    "",
                    f"XPJ instrument {idx} (Bank A/B) must be empty",
                )
            self.assertTrue(insts[47]["layersv"][0]["sampleName"].startswith("16_C16_Full_"))


if __name__ == "__main__":
    unittest.main()
