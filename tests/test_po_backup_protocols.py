"""Regression tests for BeatOS Pocket Operator archive models and modem status."""
import hashlib
import io
import json
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from po_backup_protocols import PROFILES, validate_model, write_sidecar, read_sidecar, verify_modem

def wav_bytes():
    b=io.BytesIO()
    with wave.open(b,'wb') as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(48000)
        w.writeframes(struct.pack('<hh',2000,-2000)*480)
    return b.getvalue()

class POBackupProtocolTests(unittest.TestCase):
    def test_explicit_device_profiles_and_backup_only_models(self):
        self.assertEqual(set(PROFILES),{'PO-32','PO-33','PO-35','PO-133','PO-137'})
        for model in PROFILES:
            self.assertTrue(PROFILES[model]['send'])
            self.assertTrue(PROFILES[model]['receive'])
            self.assertTrue(PROFILES[model]['destructive_restore'])
        with self.assertRaises(ValueError):
            validate_model('PO-20')
        with self.assertRaises(ValueError):
            validate_model('../../PO-33')
    def test_metadata_is_non_destructive_and_tied_to_exact_audio_hash(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'My beat.wav';p.write_bytes(wav_bytes())
            a=write_sidecar(p,'PO-33','Mi beat 🎵',source='My beat.wav')
            self.assertEqual(a['model'],'PO-33')
            self.assertEqual(a['project'],'Mi beat 🎵')
            self.assertFalse(a['payload_verified'])
            self.assertFalse(a['device_restore_verified'])
            self.assertEqual(a['sha256'],hashlib.sha256(p.read_bytes()).hexdigest())
            self.assertEqual(read_sidecar(p,a['sha256'])['project'],'Mi beat 🎵')
            with self.assertRaises(ValueError):
                write_sidecar(p,'PO-32','different')
            p.write_bytes(wav_bytes()+b'junk')
            self.assertIsNone(read_sidecar(p,hashlib.sha256(p.read_bytes()).hexdigest()))
    def test_modem_verifier_never_confuses_audio_integrity_with_protocol_validation(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'recording.wav';p.write_bytes(wav_bytes())
            for model in ('PO-32','PO-35','PO-137','PO-133'):
                result=verify_modem(p,model)
                self.assertFalse(result['payload_verified'])
                self.assertFalse(result['device_restore_verified'])
            with patch('po_backup_protocols.subprocess.run') as run:
                run.return_value.returncode=0
                run.return_value.stdout=json.dumps({'payload_verified':True,'packets':18,'patterns':16,'bpm':120})
                run.return_value.stderr=''
                good=verify_modem(p,'PO-33')
                self.assertTrue(good['payload_verified'])
                self.assertFalse(good['device_restore_verified'])
            with patch('po_backup_protocols.subprocess.run',side_effect=__import__('subprocess').TimeoutExpired('test',90)):
                bad=verify_modem(p,'PO-33')
                self.assertFalse(bad['payload_verified'])
                self.assertIn('TIMEOUT',bad['status'])
    def test_legacy_import_and_model_aware_scan(self):
        from hardware_kit_builder import import_po33_backup,scan_po33_backups,po33_backup_dirs
        with tempfile.TemporaryDirectory() as d:
            info=import_po33_backup(d,'MyBeat.wav',wav_bytes(),model='PO-35',project='Funky Beat')
            self.assertEqual(info['model'],'PO-35')
            self.assertEqual(info['project'],'Funky Beat')
            self.assertIn('PO-35',Path(info['path']).parts)
            self.assertEqual(scan_po33_backups(po33_backup_dirs(d))[0]['project'],'Funky Beat')
            other=import_po33_backup(d,'Legacy.wav',wav_bytes())
            self.assertEqual(other['model'],'PO-33')
            self.assertEqual(other['project'],'Legacy')
            self.assertEqual(len(scan_po33_backups(po33_backup_dirs(d))),2)

if __name__=='__main__': unittest.main()
