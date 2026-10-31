"""Pocket Operator audio-data backup profiles and proof levels.

Does NOT claim that a WAV, its SHA-256, or a checksummed transfer has been
restored on hardware. Only PO-33 has an optional packet verifier at present.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import tempfile

# The local HTTP server is threaded. Decode at most one untrusted WAV at a time.
_VERIFY_SLOT = threading.BoundedSemaphore(1)

PROFILES = {
    'PO-32': {'name':'Tonic','send':'WRITE + SOUND','receive':'ACC + SOUND',
              'guide':'https://teenage.engineering/guides/po-32/en','destructive_restore':True},
    'PO-33': {'name':'K.O!','send':'WRITE + SOUND + PLAY','receive':'WRITE + SOUND + RECORD',
              'guide':'https://teenage.engineering/guides/po-33/en','destructive_restore':True},
    'PO-35': {'name':'Speak','send':'WRITE + SOUND','receive':'RECORD + SOUND',
              'guide':'https://teenage.engineering/guides/po-35/en','destructive_restore':True},
    'PO-133':{'name':'Street Fighter','send':'WRITE + SOUND + PLAY','receive':'WRITE + SOUND + RECORD',
              'guide':'https://teenage.engineering/guides/po-133/en','destructive_restore':True},
    'PO-137':{'name':'Rick and Morty','send':'WRITE + SOUND','receive':'RECORD + SOUND',
              'guide':'https://teenage.engineering/guides/po-137/en','destructive_restore':True},
}
AUDIO_ONLY = ('PO-12','PO-14','PO-16','PO-20','PO-24','PO-28','PO-128')

def validate_model(model):
    if not isinstance(model,str) or model not in PROFILES:
        raise ValueError('Unsupported Pocket Operator backup model')
    return model

def safe_slug(value):
    if not isinstance(value,str) or not value.strip() or len(value)>160:
        raise ValueError('Project name must contain 1–160 characters')
    return re.sub(r'[^A-Za-z0-9_-]+','_',value.strip()).strip('_')[:60] or 'Beat'

def _sidecar(path):
    return Path(path).with_suffix('.po.json')

def write_sidecar(path, model, project, *, source=''):
    """Create lossless provenance metadata; never overwrite an existing project entry."""
    model=validate_model(model)
    safe_slug(project)
    path=Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError('Original backup WAV not found or symlinked')
    with path.open('rb') as f:
        sha256=hashlib.file_digest(f,'sha256').hexdigest()
    meta={
        'schema':'beatos-pocket-operator-v1','model':model,'project':project.strip(),
        'file':path.name,'source_filename':Path(str(source).replace('\\','/')).name[:120],
        'sha256':sha256,'size_bytes':path.stat().st_size,
        'payload_verified':False,'device_restore_verified':False,
        'verification_status':'AUDIO_ARCHIVED_NOT_DECODED'
    }
    destination=_sidecar(path)
    encoded=(json.dumps(meta,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    try:
        with destination.open('xb') as output:
            output.write(encoded)
            output.flush();os.fsync(output.fileno())
    except FileExistsError:
        existing=read_sidecar(path,sha256)
        if not existing or existing.get('model')!=model or existing.get('project')!=project.strip():
            raise ValueError('Conflicting project metadata; prior entry not replaced')
        return existing
    return meta

def read_sidecar(path, sha256):
    path=Path(path)
    meta_path=_sidecar(path)
    if meta_path.is_symlink() or not meta_path.is_file():
        return None
    try:
        if meta_path.stat().st_size>32768:
            return None
        meta=json.loads(meta_path.read_text(encoding='utf-8'))
        if not isinstance(meta,dict):
            return None
        if (meta.get('schema')!='beatos-pocket-operator-v1'
                or meta.get('file')!=path.name
                or meta.get('sha256')!=sha256
                or meta.get('model') not in PROFILES
                or not isinstance(meta.get('project'), str)
                or not 1 <= len(meta['project'].strip()) <= 160
                or type(meta.get('size_bytes')) is not int
                or meta['size_bytes'] != path.stat().st_size):
            return None
        # A sidecar may not assert physical verification merely because it was edited.
        meta['device_restore_verified']=False
        return meta
    except (OSError,ValueError,TypeError):
        return None

def verify_modem(wav_path,model):
    """Read-only optional verifier. PO-133/35/137/32 are not decoded by PO-33 logic."""
    model=validate_model(model)
    result={'model':model,'payload_verified':False,'device_restore_verified':False,
            'status':'DECODER_NOT_INTEGRATED'}
    if model!='PO-33':
        return result
    wav=Path(wav_path)
    if not wav.is_file() or wav.is_symlink() or wav.stat().st_size>128*1024*1024:
        return {**result,'status':'INVALID_OR_OVERSIZED_AUDIO'}
    decoder=Path(__file__).resolve().parent/'vendor'/'po33_verify.py'
    if not decoder.is_file():
        return {**result,'status':'DECODER_NOT_INSTALLED'}
    if not _VERIFY_SLOT.acquire(blocking=False):
        return {**result,'status':'VERIFY_BUSY'}
    try:
        try:
            execution=subprocess.run([sys.executable,'-I','-B',str(decoder),str(wav)],
                       capture_output=True,text=True,timeout=90,check=False)
        except subprocess.TimeoutExpired:
            return {**result,'status':'VERIFY_TIMEOUT'}
        except OSError:
            return {**result,'status':'DECODER_START_ERROR'}
        try:
            report=json.loads(execution.stdout)
        except (json.JSONDecodeError,TypeError):
            return {**result,'status':'DECODER_UNAVAILABLE_OR_ERROR',
                    'detail':(execution.stderr or '')[-350:]}
        if not isinstance(report,dict):
            return {**result,'status':'DECODER_INVALID_RESPONSE'}
        # A malformed/malicious decoder response must never grant verified status.
        structurally_complete=(report.get('payload_verified') is True
            and report.get('end_marker_valid') is True
            and report.get('pattern_count') == 16
            and type(report.get('packet_count')) is int
            and report['packet_count'] > 0)
        if execution.returncode!=0 or not structurally_complete:
            return {**result,'status':'PROTOCOL_NOT_VERIFIED',
                    'detail':str(report.get('detail',''))[:350]}
        return {**result,'status':'PROTOCOL_CHECKSUM_VERIFIED','payload_verified':True,
                'packet_count':report['packet_count'],'pattern_count':16,
                'bpm':report.get('bpm'),
                'verification_scope':'PO-33 packet CRC, transfer end marker and structure only'}
    finally:
        _VERIFY_SLOT.release()
