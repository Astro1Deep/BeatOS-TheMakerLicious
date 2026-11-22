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
_SIDECAR_LOCK = threading.Lock()

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

def _atomic_write_sidecar(destination: Path, meta: dict) -> None:
    encoded = (json.dumps(meta, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.po-metadata-', delete=False) as output:
            temporary = Path(output.name)
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_sidecar(path, model, project, *, source='', notes=''):
    """Create lossless provenance metadata; never overwrite an existing project entry."""
    model=validate_model(model)
    safe_slug(project)
    notes_clean = str(notes or '').strip()[:500]
    path=Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError('Original backup WAV not found or symlinked')
    with path.open('rb') as f:
        sha256=hashlib.file_digest(f,'sha256').hexdigest()
    meta={
        'schema':'beatos-pocket-operator-v1','model':model,'project':project.strip(),
        'notes':notes_clean,
        'file':path.name,'source_filename':Path(str(source).replace('\\','/')).name[:120],
        'sha256':sha256,'size_bytes':path.stat().st_size,
        'payload_verified':False,'device_restore_verified':False,
        'verification_status':'AUDIO_ARCHIVED_NOT_DECODED'
    }
    destination=_sidecar(path)
    with _SIDECAR_LOCK:
        if destination.exists() or destination.is_symlink():
            existing=read_sidecar(path,sha256)
            if not existing or existing.get('model')!=model or existing.get('project')!=project.strip():
                raise ValueError('Conflicting project metadata; prior entry not replaced')
            return existing
        _atomic_write_sidecar(destination, meta)
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
        notes_val = meta.get('notes', '')
        if not isinstance(notes_val, str) or len(notes_val) > 500:
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
        # Proof comes from a fresh decoder result, never from editable project metadata.
        meta['notes'] = notes_val.strip()[:500]
        meta['device_restore_verified']=False
        meta['payload_verified']=False
        meta['verification_status']='AUDIO_ARCHIVED_NOT_DECODED'
        return meta
    except (OSError,ValueError,TypeError):
        return None


def update_sidecar_metadata(path, *, project=None, notes=None, model=None):
    """Update editable project title / notes in `.po.json` without modifying the WAV."""
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError('Original backup WAV not found or symlinked')
    with path.open('rb') as f:
        sha256 = hashlib.file_digest(f, 'sha256').hexdigest()
    destination = _sidecar(path)
    if destination.is_symlink():
        raise ValueError('Symlinked metadata file is not supported')
    with _SIDECAR_LOCK:
        existing = read_sidecar(path, sha256)
        target_model = validate_model(model) if model is not None else (
            existing['model'] if existing else validate_model('PO-33')
        )
        if project is not None:
            safe_slug(project)
            target_project = project.strip()
        elif existing:
            target_project = existing['project']
        else:
            target_project = path.stem[:160]
        target_notes = (
            str(notes or '').strip()[:500]
            if notes is not None
            else (existing.get('notes', '') if existing else '')
        )
        meta = {
            'schema': 'beatos-pocket-operator-v1',
            'model': target_model,
            'project': target_project,
            'notes': target_notes,
            'file': path.name,
            'source_filename': (existing.get('source_filename') if existing else path.name)[:120],
            'sha256': sha256,
            'size_bytes': path.stat().st_size,
            'payload_verified': False,
            'device_restore_verified': False,
            'verification_status': 'AUDIO_ARCHIVED_NOT_DECODED',
        }
        _atomic_write_sidecar(destination, meta)
    return meta

def _resolve_decoder_python() -> str:
    """Usa el intérprete actual si tiene numpy o el entorno gestionado (~/.beatos/venv o Cerebro)."""
    try:
        import beatos_runtime  # type: ignore
        return beatos_runtime.resolve_support_python(('numpy',), code_dir=Path(__file__).resolve().parent)
    except Exception:
        pass
    try:
        import numpy  # noqa: F401
        return sys.executable
    except ImportError:
        cerebro_py = Path.home() / '.mlx-stack' / 'venv' / 'bin' / 'python'
        if cerebro_py.is_file() and os.access(cerebro_py, os.X_OK):
            return str(cerebro_py)
        return sys.executable

def verify_modem(wav_path,model):
    """Read-only optional verifier. Supports PO-33 and hardware-compatible PO-133 modem."""
    model=validate_model(model)
    result={'model':model,'payload_verified':False,'device_restore_verified':False,
            'status':'DECODER_NOT_INTEGRATED'}
    if model not in ('PO-33', 'PO-133'):
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
        py_bin = _resolve_decoder_python()
        try:
            with wav.open('rb') as source:
                source_hash=hashlib.file_digest(source,'sha256').hexdigest()
            execution=subprocess.run([py_bin,'-I','-B',str(decoder),str(wav)],
                       stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=90,check=False)
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
            out = {**result,'status':'PROTOCOL_NOT_VERIFIED',
                   'detail':str(report.get('detail',''))[:350]}
            if report.get('failure_reason'):
                out['failure_reason'] = str(report['failure_reason'])
            return out
        try:
            with wav.open('rb') as source:
                after_hash=hashlib.file_digest(source,'sha256').hexdigest()
        except OSError:
            return {**result,'status':'SOURCE_CHANGED_DURING_VERIFICATION'}
        if after_hash!=source_hash or wav.is_symlink():
            return {**result,'status':'SOURCE_CHANGED_DURING_VERIFICATION'}
        return {**result,'status':'PROTOCOL_CHECKSUM_VERIFIED','payload_verified':True,
                'sha256':source_hash,
                'packet_count':report['packet_count'],'pattern_count':16,
                'bpm':report.get('bpm'),
                'sample_count':report.get('sample_count'),
                'unresolved_trims':report.get('unresolved_trims', 0),
                'initial_symbol_rate':report.get('initial_symbol_rate'),
                'signal_start_sec':report.get('signal_start_sec'),
                'signal_duration_sec':report.get('signal_duration_sec'),
                'verification_scope':f'{model} packet CRC, transfer end marker and structure only'}
    finally:
        _VERIFY_SLOT.release()
