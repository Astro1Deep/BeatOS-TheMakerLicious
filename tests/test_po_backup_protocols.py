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

from po_backup_protocols import PROFILES, validate_model, write_sidecar, read_sidecar, update_sidecar_metadata, verify_modem

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
                run.return_value.stdout=json.dumps({'payload_verified':True,'packet_count':18,'pattern_count':16,'end_marker_valid':True,'bpm':120})
                run.return_value.stderr=''
                good=verify_modem(p,'PO-33')
                self.assertTrue(good['payload_verified'])
                self.assertFalse(good['device_restore_verified'])
            with patch('po_backup_protocols.subprocess.run',side_effect=__import__('subprocess').TimeoutExpired('test',90)):
                bad=verify_modem(p,'PO-33')
                self.assertFalse(bad['payload_verified'])
                self.assertIn('TIMEOUT',bad['status'])
    def test_corrupted_project_metadata_never_breaks_complete_inventory(self):
        from hardware_kit_builder import import_po33_backup, scan_po33_backups, po33_backup_dirs
        with tempfile.TemporaryDirectory() as d:
            first=import_po33_backup(d,'first.wav',wav_bytes(),model='PO-33',project='First')
            second=import_po33_backup(d,'other.wav',wav_bytes(),model='PO-35',project='Second')
            sidecar=Path(first['path']).with_suffix('.po.json')
            for malformed in ('[]', '"text"', '17', '{"schema":',
                              json.dumps({'schema':'beatos-pocket-operator-v1',
                                          'model':'PO-33','file':Path(first['path']).name,
                                          'sha256':first['sha256']}),
                              json.dumps({'schema':'beatos-pocket-operator-v1',
                                          'model':'PO-33','file':Path(first['path']).name,
                                          'sha256':first['sha256'],'project':[]}),
                              json.dumps({'schema':'beatos-pocket-operator-v1',
                                          'model':'PO-33','file':Path(first['path']).name,
                                          'sha256':first['sha256'],'project':'B'*200}),
                              ):
                sidecar.write_text(malformed,encoding='utf-8')
                self.assertIsNone(read_sidecar(first['path'],first['sha256']))
                scanned=scan_po33_backups(po33_backup_dirs(d),cache={})
                self.assertEqual(len(scanned),2)
                self.assertEqual(next(x for x in scanned if x['path']==first['path'])['model'],'UNSPECIFIED')
                self.assertEqual(next(x for x in scanned if x['path']==second['path'])['project'],'Second')
    def test_verifier_refuses_missing_crc_evidence_even_when_subprocess_claims_success(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'data.wav';p.write_bytes(wav_bytes())
            with patch('po_backup_protocols.subprocess.run') as run:
                run.return_value.returncode=0
                run.return_value.stderr=''
                for report in ('[]','true',
                               json.dumps({'payload_verified':True,'packet_count':2,'pattern_count':16,
                                           'end_marker_valid':False})):
                    run.return_value.stdout=report
                    self.assertFalse(verify_modem(p,'PO-33')['payload_verified'])
    def test_simultaneous_verification_is_rejected_without_starting_another_decoder(self):
        import po_backup_protocols
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'data.wav';p.write_bytes(wav_bytes())
            semaphore=po_backup_protocols._VERIFY_SLOT
            self.assertTrue(semaphore.acquire(blocking=False))
            try:
                with patch('po_backup_protocols.subprocess.run') as run:
                    result=verify_modem(p,'PO-33')
                    self.assertEqual(result['status'],'VERIFY_BUSY')
                    self.assertFalse(result['payload_verified'])
                    run.assert_not_called()
            finally:
                semaphore.release()

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

    def test_update_sidecar_metadata_preserves_original_audio_and_adds_notes(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'Session.wav'
            original = wav_bytes()
            p.write_bytes(original)
            write_sidecar(p, 'PO-33', 'Old Beat', source='Session.wav')
            updated = update_sidecar_metadata(p, project='New Beat', notes='93 BPM live set')
            self.assertEqual(updated['project'], 'New Beat')
            self.assertEqual(updated['notes'], '93 BPM live set')
            self.assertEqual(p.read_bytes(), original)
            digest = hashlib.sha256(original).hexdigest()
            sidecar = read_sidecar(p, digest)
            self.assertEqual(sidecar['project'], 'New Beat')
            self.assertEqual(sidecar['notes'], '93 BPM live set')

    def test_po133_invokes_modem_verifier_and_decoder_rejects_silent_or_mono(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'po133.wav'
            p.write_bytes(wav_bytes())
            with patch('po_backup_protocols.subprocess.run') as run:
                run.return_value.returncode = 0
                run.return_value.stdout = json.dumps({
                    'payload_verified': True, 'packet_count': 42, 'pattern_count': 16,
                    'end_marker_valid': True, 'bpm': 110, 'sample_count': 12
                })
                run.return_value.stderr = ''
                res = verify_modem(p, 'PO-133')
                self.assertTrue(res['payload_verified'])
                self.assertEqual(res['bpm'], 110)
                self.assertEqual(res['sample_count'], 12)
                self.assertFalse(res['device_restore_verified'])

            try:
                sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'vendor'))
                import po33_decode
            except ImportError:
                self.skipTest('NumPy not installed in test interpreter')

            silent = Path(d) / 'silent.wav'
            with wave.open(str(silent), 'wb') as w:
                w.setparams((2, 2, 44100, 0, 'NONE', ''))
                w.writeframes(struct.pack('<hh', 0, 0) * 44100)
            with self.assertRaisesRegex(ValueError, 'SILENT_RECORDING'):
                po33_decode.demodulate(silent)

            mono = Path(d) / 'mono.wav'
            with wave.open(str(mono), 'wb') as w:
                w.setparams((2, 2, 44100, 0, 'NONE', ''))
                w.writeframes(b''.join(struct.pack('<hh', 4000 if i % 2 else -4000, 4000 if i % 2 else -4000) for i in range(44100)))
            with self.assertRaisesRegex(ValueError, 'MONO_DUPLICATED'):
                po33_decode.demodulate(mono)

if __name__=='__main__': unittest.main()
