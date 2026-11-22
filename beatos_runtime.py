"""Portable runtime diagnostics, FFmpeg/codec resolution, and zero-to-full installers for BeatOS.

100% Python stdlib so BeatOS can diagnose, bootstrap, and export target installers
from a completely clean machine (macOS, Windows, Linux) without touching system Python
packages (PEP 668) or storing OS-specific virtualenvs inside FAT32/exFAT SD cards.
"""
from __future__ import annotations

import datetime
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable, Iterable, Optional

RUNTIME_SCHEMA = "beatos-runtime-manifest-v1"
MINIMUM_PYTHON = (3, 10)

INSTALL_PROFILES: dict[str, dict] = {
    "full": {
        "id": "full",
        "title_es": "Completo (Todos los modos · FFmpeg + PO-33 CRC + DSP + MIR MMR)",
        "title_en": "Full (All modes · FFmpeg + PO-33 CRC + DSP + MIR MMR)",
        "packages": ("numpy", "scipy", "librosa", "soundfile", "imageio-ffmpeg"),
        "modules": ("numpy", "scipy", "librosa", "soundfile", "imageio_ffmpeg"),
        "package_to_module": {
            "numpy": "numpy",
            "scipy": "scipy",
            "librosa": "librosa",
            "soundfile": "soundfile",
            "imageio-ffmpeg": "imageio_ffmpeg",
        },
        "include_system_ffmpeg": True,
    },
    "essential": {
        "id": "essential",
        "title_es": "Esencial (Códecs FFmpeg + Verificador PO-33/133 CRC + DSP rápido)",
        "title_en": "Essential (FFmpeg codecs + PO-33/133 CRC verifier + fast DSP)",
        "packages": ("numpy", "imageio-ffmpeg"),
        "modules": ("numpy", "imageio_ffmpeg"),
        "package_to_module": {
            "numpy": "numpy",
            "imageio-ffmpeg": "imageio_ffmpeg",
        },
        "include_system_ffmpeg": True,
    },
    "codecs": {
        "id": "codecs",
        "title_es": "Solo Códecs (FFmpeg portable para MP3/FLAC/AIFF/M4A/MP4 → WAV)",
        "title_en": "Codecs only (Portable FFmpeg for MP3/FLAC/AIFF/M4A/MP4 → WAV)",
        "packages": ("imageio-ffmpeg",),
        "modules": ("imageio_ffmpeg",),
        "package_to_module": {
            "imageio-ffmpeg": "imageio_ffmpeg",
        },
        "include_system_ffmpeg": True,
    },
}

TARGET_SCRIPTS: dict[str, dict] = {
    "macos": {
        "target": "macos",
        "filename": "Instalar_Soporte_BeatOS_macOS.command",
        "label_es": "macOS (Apple Silicon / Intel)",
        "label_en": "macOS (Apple Silicon / Intel)",
        "eol": "\n",
        "executable": True,
    },
    "windows": {
        "target": "windows",
        "filename": "Instalar_Soporte_BeatOS_Windows.bat",
        "label_es": "Windows 10 / 11 (x64 / ARM64)",
        "label_en": "Windows 10 / 11 (x64 / ARM64)",
        "eol": "\r\n",
        "executable": False,
    },
    "linux": {
        "target": "linux",
        "filename": "install_beatos_support_linux.sh",
        "label_es": "Linux (Debian/Ubuntu/Fedora/Arch)",
        "label_en": "Linux (Debian/Ubuntu/Fedora/Arch)",
        "eol": "\n",
        "executable": True,
    },
}

_MODULE_DIST_NAME = {
    "numpy": "numpy",
    "scipy": "scipy",
    "librosa": "librosa",
    "soundfile": "soundfile",
    "imageio_ffmpeg": "imageio-ffmpeg",
}

_CACHE_LOCK = threading.Lock()
_BINARY_CACHE: dict[tuple[str, str], tuple[float, object]] = {}
_VENV_PROBE_CACHE: dict[tuple[str, int], tuple[float, dict]] = {}
_VERSION_CACHE: dict[str, tuple[float, str]] = {}


def clear_runtime_cache() -> None:
    with _CACHE_LOCK:
        _BINARY_CACHE.clear()
        _VENV_PROBE_CACHE.clear()
        _VERSION_CACHE.clear()


def current_os_id() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("win"):
        return "windows"
    return "linux"


def validate_profile(profile: str | None) -> str:
    cleaned = str(profile or "full").strip().lower()
    if cleaned not in INSTALL_PROFILES:
        raise ValueError(f"Perfil de soporte no válido: {profile}. Usa: full, essential o codecs.")
    return cleaned


def validate_target_os(target: str | None) -> str:
    cleaned = str(target or current_os_id()).strip().lower()
    aliases = {
        "darwin": "macos",
        "mac": "macos",
        "osx": "macos",
        "win32": "windows",
        "win": "windows",
    }
    cleaned = aliases.get(cleaned, cleaned)
    if cleaned not in TARGET_SCRIPTS:
        raise ValueError(f"Target no válido: {target}. Usa: macos, windows o linux.")
    return cleaned


def managed_support_root() -> Path:
    override = os.environ.get("BEATOS_SUPPORT_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if sys.platform.startswith("win"):
        local_app = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local_app) if local_app else (Path.home() / "AppData" / "Local")
        return base / "BeatOS"
    return Path.home() / ".beatos"


def managed_venv_dir() -> Path:
    override = os.environ.get("BEATOS_VENV_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return managed_support_root() / "venv"


def managed_bin_dir() -> Path:
    return managed_support_root() / "bin"


def venv_python_path(venv_dir: Path | str) -> Path:
    base = Path(venv_dir)
    if sys.platform.startswith("win"):
        return base / "Scripts" / "python.exe"
    return base / "bin" / "python"


def _is_executable_file(path: Path) -> bool:
    try:
        return path.is_file() and os.access(path, os.X_OK)
    except OSError:
        return False


def _same_executable(a: str | Path, b: str | Path) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return os.path.abspath(str(a)) == os.path.abspath(str(b))


def _probe_inprocess_modules(modules: Iterable[str] = tuple(_MODULE_DIST_NAME)) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for mod in modules:
        installed = importlib.util.find_spec(mod) is not None
        ver = ""
        if installed:
            dist = _MODULE_DIST_NAME.get(mod, mod)
            try:
                ver = importlib.metadata.version(dist)
            except importlib.metadata.PackageNotFoundError:
                ver = ""
        out[mod] = {"installed": installed, "version": ver}
    return out


def _probe_python_env_modules(py_path: str | Path) -> dict[str, dict]:
    py = Path(py_path)
    if not _is_executable_file(py):
        return {}
    if _same_executable(py, sys.executable):
        return _probe_inprocess_modules()
    try:
        mtime_ns = py.stat().st_mtime_ns
    except OSError:
        return {}
    cache_key = (str(py), mtime_ns)
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _VENV_PROBE_CACHE.get(cache_key)
        if cached and (now - cached[0]) < 30.0:
            return dict(cached[1])

    script = (
        "import importlib.metadata, importlib.util, json; "
        "mods={'numpy':'numpy','scipy':'scipy','librosa':'librosa','soundfile':'soundfile','imageio_ffmpeg':'imageio-ffmpeg'}; "
        "res={}; "
        "\nfor m,d in mods.items():\n"
        " ok=importlib.util.find_spec(m) is not None\n"
        " v=''\n"
        " if ok:\n"
        "  try: v=importlib.metadata.version(d)\n"
        "  except Exception: v=''\n"
        " res[m]={'installed':ok,'version':v}\n"
        "print(json.dumps(res))"
    )
    info: dict[str, dict] = {}
    try:
        proc = subprocess.run(
            [str(py), "-I", "-B", "-c", script],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            parsed = json.loads(proc.stdout.strip())
            if isinstance(parsed, dict):
                info = parsed
    except (OSError, subprocess.SubprocessError, ValueError):
        info = {}
    with _CACHE_LOCK:
        _VENV_PROBE_CACHE[cache_key] = (now, dict(info))
    return info


def _candidate_python_interpreters(code_dir: str | Path | None = None) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = [("current", sys.executable)]
    m_py = venv_python_path(managed_venv_dir())
    if _is_executable_file(m_py) and not _same_executable(m_py, sys.executable):
        candidates.append(("managed_venv", str(m_py)))
    if code_dir:
        local_venv_py = venv_python_path(Path(code_dir) / ".venv")
        if _is_executable_file(local_venv_py) and not any(_same_executable(local_venv_py, p) for _, p in candidates):
            candidates.append(("local_venv", str(local_venv_py)))
    cerebro_py = venv_python_path(Path.home() / ".mlx-stack" / "venv")
    if _is_executable_file(cerebro_py) and not any(_same_executable(cerebro_py, p) for _, p in candidates):
        candidates.append(("cerebro_venv", str(cerebro_py)))
    return candidates


def resolve_support_python(required_modules: Iterable[str] = ("numpy",), code_dir: str | Path | None = None) -> str:
    req = tuple(required_modules)
    for _, py_path in _candidate_python_interpreters(code_dir):
        mods = _probe_python_env_modules(py_path)
        if all(mods.get(m, {}).get("installed") for m in req):
            return py_path
    return sys.executable


def _resolve_tool_binary(tool_name: str, env_key: str, code_dir: str | Path | None = None) -> dict | None:
    code_str = str(Path(code_dir).resolve()) if code_dir else ""
    cache_key = (tool_name, code_str)
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _BINARY_CACHE.get(cache_key)
        if cached and (now - cached[0]) < 15.0:
            return dict(cached[1]) if isinstance(cached[1], dict) else None

    exe_name = f"{tool_name}.exe" if sys.platform.startswith("win") else tool_name
    found: dict | None = None

    # 1. Explicit environment override
    env_val = os.environ.get(env_key, "").strip()
    if env_val:
        ep = Path(env_val).expanduser()
        if _is_executable_file(ep):
            found = {"path": str(ep), "source": "env"}

    # 2. System PATH
    if found is None:
        which_path = shutil.which(tool_name)
        if which_path:
            found = {"path": which_path, "source": "path"}

    # 3. Common OS install paths (e.g. macOS GUI launch without Homebrew in PATH)
    if found is None:
        sys_candidates: list[Path] = []
        if sys.platform == "darwin":
            sys_candidates = [Path("/opt/homebrew/bin") / exe_name, Path("/usr/local/bin") / exe_name]
        elif sys.platform.startswith("win"):
            local_app = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData/Local"))
            sys_candidates = [
                Path("C:/ffmpeg/bin") / exe_name,
                local_app / "Microsoft/WinGet/Links" / exe_name,
                Path.home() / "scoop/shims" / exe_name,
            ]
        else:
            sys_candidates = [Path("/usr/bin") / exe_name, Path("/usr/local/bin") / exe_name, Path("/snap/bin") / exe_name]
        for cand in sys_candidates:
            if _is_executable_file(cand):
                found = {"path": str(cand), "source": "system"}
                break

    # 4. BeatOS managed bin dir or local app bin dir
    if found is None:
        managed_cand = managed_bin_dir() / exe_name
        if _is_executable_file(managed_cand):
            found = {"path": str(managed_cand), "source": "managed"}
    if found is None and code_dir:
        local_cand = Path(code_dir) / "bin" / exe_name
        if _is_executable_file(local_cand):
            found = {"path": str(local_cand), "source": "bundled"}

    # 5. Portable Python wheel imageio-ffmpeg (current or managed venv)
    if found is None and tool_name == "ffmpeg":
        if importlib.util.find_spec("imageio_ffmpeg") is not None:
            try:
                import imageio_ffmpeg  # type: ignore
                bin_path = Path(imageio_ffmpeg.get_ffmpeg_exe())
                if _is_executable_file(bin_path):
                    found = {"path": str(bin_path), "source": "imageio_ffmpeg"}
            except Exception:
                found = None
        if found is None:
            for _, py_path in _candidate_python_interpreters(code_dir):
                if _same_executable(py_path, sys.executable):
                    continue
                mods = _probe_python_env_modules(py_path)
                if not mods.get("imageio_ffmpeg", {}).get("installed"):
                    continue
                try:
                    proc = subprocess.run(
                        [py_path, "-I", "-B", "-c", "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"],
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        text=True,
                        timeout=8,
                        check=False,
                    )
                    if proc.returncode == 0 and proc.stdout.strip():
                        cand = Path(proc.stdout.strip().splitlines()[-1])
                        if _is_executable_file(cand):
                            found = {"path": str(cand), "source": "imageio_ffmpeg"}
                            break
                except (OSError, subprocess.SubprocessError):
                    pass

    with _CACHE_LOCK:
        _BINARY_CACHE[cache_key] = (now, dict(found) if found else None)
    return found


def resolve_ffmpeg_binary(code_dir: str | Path | None = None) -> dict | None:
    return _resolve_tool_binary("ffmpeg", "BEATOS_FFMPEG", code_dir=code_dir)


def resolve_ffmpeg_path(code_dir: str | Path | None = None) -> str | None:
    info = resolve_ffmpeg_binary(code_dir=code_dir)
    return info["path"] if info else None


def resolve_ffprobe_path(code_dir: str | Path | None = None) -> str | None:
    info = _resolve_tool_binary("ffprobe", "BEATOS_FFPROBE", code_dir=code_dir)
    return info["path"] if info else None


def _binary_version_line(executable_path: str) -> str:
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _VERSION_CACHE.get(executable_path)
        if cached and (now - cached[0]) < 60.0:
            return cached[1]
    ver = ""
    try:
        proc = subprocess.run(
            [executable_path, "-version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout:
            ver = proc.stdout.splitlines()[0].strip()[:120]
    except (OSError, subprocess.SubprocessError):
        ver = ""
    with _CACHE_LOCK:
        _VERSION_CACHE[executable_path] = (now, ver)
    return ver


def _available_package_managers() -> list[str]:
    mgrs: list[str] = []
    for tool in ("uv", "brew", "winget", "choco", "scoop", "apt-get", "dnf", "pacman", "zypper"):
        if shutil.which(tool):
            mgrs.append(tool)
        elif tool == "brew" and sys.platform == "darwin" and any(
            _is_executable_file(p) for p in (Path("/opt/homebrew/bin/brew"), Path("/usr/local/bin/brew"))
        ):
            mgrs.append("brew")
    return mgrs


def inspect_capabilities(code_dir: str | Path | None = None, *, probe_codecs: bool = True) -> dict:
    """Return full capability and per-mode readiness report across OS targets."""
    os_id = current_os_id()
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    py_ok = sys.version_info >= MINIMUM_PYTHON

    inprocess = _probe_inprocess_modules()
    m_venv = managed_venv_dir()
    m_py = venv_python_path(m_venv)
    m_exists = _is_executable_file(m_py)
    in_managed = m_exists and _same_executable(sys.executable, m_py)

    support_envs: dict[str, dict[str, dict]] = {}
    for kind, py_path in _candidate_python_interpreters(code_dir):
        if kind != "current":
            support_envs[kind] = _probe_python_env_modules(py_path)

    best_support_py = resolve_support_python(("numpy",), code_dir=code_dir)

    ffmpeg_info = resolve_ffmpeg_binary(code_dir=code_dir)
    ffprobe_path = resolve_ffprobe_path(code_dir=code_dir)
    ffmpeg_ver = _binary_version_line(ffmpeg_info["path"]) if (ffmpeg_info and probe_codecs) else ""

    components: dict[str, dict] = {
        "python": {
            "installed": py_ok,
            "version": py_ver,
            "path": sys.executable,
            "source": "managed_venv" if in_managed else "host_python",
        },
        "ffmpeg": {
            "installed": ffmpeg_info is not None,
            "version": ffmpeg_ver,
            "path": ffmpeg_info["path"] if ffmpeg_info else "",
            "source": ffmpeg_info["source"] if ffmpeg_info else "",
        },
        "ffprobe": {
            "installed": ffprobe_path is not None,
            "version": "",
            "path": ffprobe_path or "",
            "source": "system" if ffprobe_path else "",
        },
        "dot_clean": {
            "installed": sys.platform == "darwin" and shutil.which("dot_clean") is not None,
            "path": shutil.which("dot_clean") or "",
            "source": "macos" if sys.platform == "darwin" else "not_applicable",
        },
    }

    for mod in ("numpy", "scipy", "librosa", "soundfile", "imageio_ffmpeg"):
        inproc_info = inprocess.get(mod, {"installed": False, "version": ""})
        installed_in_process = bool(inproc_info.get("installed"))
        installed_in_venv = False
        venv_ver = ""
        venv_source = ""
        for kind, env_mods in support_envs.items():
            if env_mods.get(mod, {}).get("installed"):
                installed_in_venv = True
                venv_ver = env_mods[mod].get("version", "")
                venv_source = kind
                break
        components[mod] = {
            "installed": installed_in_process,
            "installed_in_support_venv": installed_in_venv,
            "available_via_subprocess": installed_in_process or installed_in_venv,
            "version": inproc_info.get("version") or venv_ver,
            "source": "in_process" if installed_in_process else venv_source,
            "needs_restart_for_inprocess": bool(not installed_in_process and installed_in_venv),
        }

    needs_restart = any(components[m]["needs_restart_for_inprocess"] for m in ("numpy", "scipy", "librosa", "soundfile"))

    def _pkg_missing(*mods: str) -> list[str]:
        return [m for m in mods if not components[m]["installed"]]

    # Mode statuses
    codecs_ready = components["ffmpeg"]["installed"]
    po_crc_ready = components["numpy"]["available_via_subprocess"]
    dsp_inproc = components["numpy"]["installed"] and components["scipy"]["installed"]
    dsp_venv = components["numpy"]["available_via_subprocess"] and components["scipy"]["available_via_subprocess"]
    mir_inproc = all(components[m]["installed"] for m in ("numpy", "scipy", "librosa", "soundfile"))
    mir_venv = all(components[m]["available_via_subprocess"] for m in ("numpy", "scipy", "librosa", "soundfile"))

    modes = [
        {
            "id": "core_catalog_mpc",
            "name_es": "Catálogo SQLite, Beatmaker Rack 128 Pads y MPC (.xpm/.xpj/.PGM)",
            "name_en": "SQLite Catalog, 128-Pad Rack & MPC Export (.xpm/.xpj/.PGM)",
            "status": "ready" if py_ok else "missing",
            "missing": [] if py_ok else ["python>=3.10"],
            "note_es": "Motor nativo WAV PCM y formatos Akai MPC / SampQOL / Melodee sin dependencias externas.",
            "note_en": "Native PCM WAV and Akai MPC / SampQOL / Melodee engine with zero external dependencies.",
        },
        {
            "id": "universal_codecs",
            "name_es": "Códecs Universales (MP3, FLAC, AIFF, M4A, AAC, MP4 → WAV 16/24-bit)",
            "name_en": "Universal Audio Codecs (MP3, FLAC, AIFF, M4A, AAC, MP4 → WAV)",
            "status": "ready" if codecs_ready else "missing",
            "missing": [] if codecs_ready else ["ffmpeg"],
            "note_es": (
                f"FFmpeg activo ({components['ffmpeg']['source']})."
                if codecs_ready
                else "Sin FFmpeg: solo se procesarán archivos WAV PCM 16-bit/44.1 kHz estándar."
            ),
            "note_en": (
                f"FFmpeg ready ({components['ffmpeg']['source']})."
                if codecs_ready
                else "Without FFmpeg, conversion of MP3/FLAC/M4A/MP4/AIFF is unavailable."
            ),
        },
        {
            "id": "po_backup_modem",
            "name_es": "Pocket Operator Studio + Verificador Módem CRC (PO-33 / PO-133)",
            "name_en": "Pocket Operator Studio + Modem CRC Verifier (PO-33 / PO-133)",
            "status": "ready" if po_crc_ready else "degraded",
            "missing": [] if po_crc_ready else ["numpy"],
            "note_es": (
                "Captura/archivo WAV e inspección CRC de paquetes QPSK activos."
                if po_crc_ready
                else "Grabación/archivo WAV activos; falta NumPy para decodificar y verificar paquetes CRC del PO-33/PO-133."
            ),
            "note_en": (
                "WAV capture, archive and QPSK CRC packet verification ready."
                if po_crc_ready
                else "WAV capture works; NumPy is required to run PO-33/PO-133 CRC packet verification."
            ),
        },
        {
            "id": "acoustic_dsp_chop",
            "name_es": "Motor Acústico Cerebro DSP, Calibración 808 y Anti-Clipping",
            "name_en": "Cerebro DSP Engine, 808 Pitch Calibration & Anti-Clipping",
            "status": "ready" if dsp_inproc else ("degraded" if dsp_venv else "degraded"),
            "missing": [] if dsp_inproc else _pkg_missing("numpy", "scipy"),
            "note_es": (
                "DSP vectorizado (NumPy + SciPy) cargado en memoria."
                if dsp_inproc
                else (
                    "Soporte instalado en entorno virtual; reinicia BeatOS con ABRIR_BEATOS para activarlo en el servidor."
                    if dsp_venv
                    else "Trabajando en fallback determinista Python; instala NumPy + SciPy para máximo rendimiento."
                )
            ),
            "note_en": (
                "Vectorized NumPy + SciPy DSP active in-process."
                if dsp_inproc
                else (
                    "Packages installed in managed venv; restart BeatOS via launcher to load in-process."
                    if dsp_venv
                    else "Running pure-Python deterministic fallback; install NumPy + SciPy for full DSP precision."
                )
            ),
        },
        {
            "id": "mir_mmr_chopping",
            "name_es": "Auto-Chop Musical MIR (3 Bancos MMR · HPSS / CQT / Downbeat / A440)",
            "name_en": "Musical MIR Auto-Chop (3 MMR Banks · HPSS / CQT / Downbeat / A440)",
            "status": "ready" if mir_inproc else ("degraded" if mir_venv else "missing"),
            "missing": [] if mir_inproc else _pkg_missing("numpy", "scipy", "librosa", "soundfile"),
            "note_es": (
                "Análisis armónico/percusivo completo con Librosa y HPSS activo."
                if mir_inproc
                else (
                    "Librosa ya instalado en venv; reinicia BeatOS con ABRIR_BEATOS para cargarlo."
                    if mir_venv
                    else "Falta instalar el perfil Completo (NumPy, SciPy, Librosa, SoundFile)."
                )
            ),
            "note_en": (
                "Full Librosa HPSS/CQT/Beat musical chopping engine active."
                if mir_inproc
                else (
                    "Librosa installed in managed venv; restart BeatOS via launcher to activate."
                    if mir_venv
                    else "Install Full profile (NumPy, SciPy, Librosa, SoundFile) to enable musical MMR chopping."
                )
            ),
        },
        {
            "id": "hardware_hygiene",
            "name_es": "Higiene Hardware MPC / SP-404 (AppleDouble ._* y .DS_Store)",
            "name_en": "Hardware Storage Hygiene (AppleDouble ._* & .DS_Store cleanup)",
            "status": "ready",
            "missing": [],
            "note_es": "Limpieza segura multiplataforma (con dot_clean nativo en macOS).",
            "note_en": "Cross-platform metadata cleanup ready (uses dot_clean natively on macOS).",
        },
    ]

    ready_count = sum(1 for m in modes if m["status"] == "ready")
    degraded_count = sum(1 for m in modes if m["status"] == "degraded")
    missing_count = sum(1 for m in modes if m["status"] == "missing")
    all_ready = (ready_count == len(modes))

    if all_ready:
        recommended = "none"
    elif not codecs_ready and not po_crc_ready and not mir_inproc:
        recommended = "full"
    elif not mir_inproc:
        recommended = "full"
    elif not codecs_ready:
        recommended = "codecs"
    else:
        recommended = "essential"

    return {
        "schema": RUNTIME_SCHEMA,
        "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "platform": {
            "os_id": os_id,
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python_version": py_ver,
            "python_executable": sys.executable,
            "in_managed_venv": in_managed,
            "managed_support_root": str(managed_support_root()),
            "managed_venv_dir": str(m_venv),
            "managed_venv_python": str(m_py),
            "managed_venv_exists": m_exists,
            "active_support_python": best_support_py,
            "package_managers": _available_package_managers(),
        },
        "components": components,
        "modes": modes,
        "summary": {
            "ready_modes": ready_count,
            "degraded_modes": degraded_count,
            "missing_modes": missing_count,
            "total_modes": len(modes),
            "all_ready": all_ready,
            "needs_restart": needs_restart,
            "recommended_profile": recommended,
        },
    }


def _emit(log_cb: Optional[Callable[[str], None]], line: str) -> None:
    if log_cb:
        log_cb(line)


def install_support_profile(
    profile: str = "full",
    *,
    include_system_ffmpeg: bool = True,
    dry_run: bool = False,
    code_dir: str | Path | None = None,
    log_cb: Optional[Callable[[str], None]] = None,
) -> dict:
    """Install a BeatOS support profile inside an isolated managed virtualenv on the host OS."""
    prof_id = validate_profile(profile)
    prof = INSTALL_PROFILES[prof_id]
    venv_dir = managed_venv_dir()
    venv_py = venv_python_path(venv_dir)
    packages = list(prof["packages"])

    uv_bin = shutil.which("uv")
    brew_bin = shutil.which("brew") or (
        "/opt/homebrew/bin/brew" if sys.platform == "darwin" and _is_executable_file(Path("/opt/homebrew/bin/brew")) else None
    )
    winget_bin = shutil.which("winget") if sys.platform.startswith("win") else None

    ff_info = resolve_ffmpeg_binary(code_dir=code_dir)
    has_system_ffmpeg = bool(ff_info and ff_info.get("source") in ("env", "path", "system")) and bool(
        resolve_ffprobe_path(code_dir=code_dir)
    )

    planned_steps: list[list[str]] = []
    if not _is_executable_file(venv_py):
        planned_steps.append([sys.executable, "-m", "venv", str(venv_dir)])
    if uv_bin:
        planned_steps.append([uv_bin, "pip", "install", "--python", str(venv_py), "--upgrade", *packages])
    else:
        planned_steps.append([str(venv_py), "-m", "pip", "install", "--upgrade", *packages])
    if include_system_ffmpeg and not has_system_ffmpeg:
        if sys.platform == "darwin" and brew_bin:
            planned_steps.append([brew_bin, "install", "ffmpeg"])
        elif sys.platform.startswith("win") and winget_bin:
            planned_steps.append([winget_bin, "install", "--exact", "--id", "Gyan.FFmpeg",
                                  "--accept-package-agreements", "--accept-source-agreements"])

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "profile": prof_id,
            "venv_dir": str(venv_dir),
            "venv_python": str(venv_py),
            "packages": packages,
            "planned_commands": planned_steps,
        }

    logs: list[str] = []

    def log(msg: str) -> None:
        logs.append(msg)
        _emit(log_cb, msg)

    log(f"🛠️ BeatOS Setup · Perfil '{prof_id}' · Target: {platform.system()} ({platform.machine()})")
    managed_support_root().mkdir(parents=True, exist_ok=True)
    managed_bin_dir().mkdir(parents=True, exist_ok=True)

    if not _is_executable_file(venv_py):
        log(f"📦 Creando entorno virtual aislado en: {venv_dir}")
        proc = subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if proc.returncode != 0 or not _is_executable_file(venv_py):
            err = (proc.stderr or proc.stdout or "No se pudo crear el venv").strip()[-400:]
            raise RuntimeError(f"Error creando venv en {venv_dir}: {err}")
        log("✔ Entorno virtual aislado creado.")
    else:
        log(f"✔ Reutilizando entorno virtual existente: {venv_dir}")

    # Install Python packages + portable imageio-ffmpeg binary
    install_cmd = (
        [uv_bin, "pip", "install", "--python", str(venv_py), "--upgrade", *packages]
        if uv_bin
        else [str(venv_py), "-m", "pip", "install", "--upgrade", *packages]
    )
    log(f"⬇️ Instalando dependencias ({', '.join(packages)})...")
    proc = subprocess.Popen(
        install_cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    assert proc.stdout is not None

    def _drain_stdout() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            clean = line.rstrip()
            if clean:
                log("  " + clean)

    reader = threading.Thread(target=_drain_stdout, daemon=True)
    reader.start()
    try:
        rc = proc.wait(timeout=900)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=10)
        except subprocess.SubprocessError:
            pass
        reader.join(timeout=5)
        raise RuntimeError("La instalación de paquetes superó el tiempo límite (900s).")
    reader.join(timeout=5)
    if rc != 0:
        raise RuntimeError(f"La instalación de paquetes terminó con código {rc}.")
    log("✔ Dependencias Python instaladas en el entorno aislado.")

    # Optional system FFmpeg via OS package manager (never fatal because imageio-ffmpeg is included)
    ff_info_now = resolve_ffmpeg_binary(code_dir=code_dir)
    has_sys_ff_now = bool(ff_info_now and ff_info_now.get("source") in ("env", "path", "system")) and bool(
        resolve_ffprobe_path(code_dir=code_dir)
    )
    if include_system_ffmpeg and not has_sys_ff_now:
        if sys.platform == "darwin" and brew_bin:
            log("🍺 Intentando instalar FFmpeg de sistema con Homebrew...")
            b_proc = subprocess.run(
                [brew_bin, "install", "ffmpeg"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
            if b_proc.returncode == 0:
                log("✔ FFmpeg de Homebrew instalado.")
            else:
                log("ℹ️ Homebrew FFmpeg no completado; se usará FFmpeg portable de imageio-ffmpeg.")
        elif sys.platform.startswith("win") and winget_bin:
            log("🪟 Intentando instalar FFmpeg de sistema con winget...")
            w_proc = subprocess.run(
                [winget_bin, "install", "--exact", "--id", "Gyan.FFmpeg",
                 "--accept-package-agreements", "--accept-source-agreements"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
            if w_proc.returncode == 0:
                log("✔ FFmpeg vía winget instalado.")
            else:
                log("ℹ️ winget FFmpeg no completado; se usará FFmpeg portable de imageio-ffmpeg.")
        elif sys.platform.startswith("linux"):
            log("🐧 Tip Linux: para FFmpeg global ejecuta `sudo apt install -y ffmpeg libsndfile1` (BeatOS ya cuenta con FFmpeg portable).")

    # Verify installed modules + imageio_ffmpeg + po33 self-check
    modules_csv = ",".join(prof["modules"])
    verify_code = (
        f"import importlib; mods={prof['modules']!r}; "
        "[importlib.import_module(m) for m in mods]; "
        "import imageio_ffmpeg; print('FFMPEG_PORTABLE=' + imageio_ffmpeg.get_ffmpeg_exe())"
    )
    v_proc = subprocess.run(
        [str(venv_py), "-I", "-B", "-c", verify_code],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if v_proc.returncode != 0:
        raise RuntimeError(
            f"Fallo verificando módulos ({modules_csv}): {(v_proc.stderr or v_proc.stdout)[-300:]}"
        )
    log(f"✔ Verificación de importación OK: {v_proc.stdout.strip()}")

    self_check_ok = False
    if "numpy" in prof["modules"]:
        verifier = (Path(code_dir) if code_dir else Path(__file__).resolve().parent) / "vendor" / "po33_verify.py"
        if verifier.is_file():
            sc_proc = subprocess.run(
                [str(venv_py), "-I", "-B", str(verifier), "--self-check"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self_check_ok = sc_proc.returncode == 0
            if not self_check_ok:
                raise RuntimeError(f"Autoprueba PO-33 falló: {(sc_proc.stderr or sc_proc.stdout)[-250:]}")
            log("✔ Autoprueba decodificador módem PO-33 (CRC/QPSK) OK.")

    clear_runtime_cache()
    caps = inspect_capabilities(code_dir=code_dir, probe_codecs=True)

    manifest_path = managed_support_root() / "runtime_manifest.json"
    manifest_payload = {
        "schema": RUNTIME_SCHEMA,
        "profile": prof_id,
        "installed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "venv_python": str(venv_py),
        "ffmpeg_path": caps["components"]["ffmpeg"].get("path", ""),
        "ffmpeg_source": caps["components"]["ffmpeg"].get("source", ""),
        "packages": packages,
        "self_check_ok": self_check_ok,
    }
    encoded = (json.dumps(manifest_payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    temp_file = None
    try:
        with tempfile.NamedTemporaryFile(dir=manifest_path.parent, prefix=".runtime-", delete=False) as out:
            temp_file = Path(out.name)
            out.write(encoded)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp_file, manifest_path)
    finally:
        if temp_file is not None:
            temp_file.unlink(missing_ok=True)

    return {
        "success": True,
        "dry_run": False,
        "profile": prof_id,
        "venv_dir": str(venv_dir),
        "venv_python": str(venv_py),
        "ffmpeg_path": caps["components"]["ffmpeg"].get("path", ""),
        "self_check_ok": self_check_ok,
        "needs_restart": caps["summary"]["needs_restart"],
        "capabilities": caps,
        "logs": logs,
    }


def generate_requirements_txt(profile: str = "full") -> str:
    prof_id = validate_profile(profile)
    pkgs = INSTALL_PROFILES[prof_id]["packages"]
    lines = [
        f"# BeatOS Runtime Requirements (profile: {prof_id})",
        "# Install inside an isolated virtualenv (~/.beatos/venv on macOS/Linux, %LOCALAPPDATA%\\BeatOS\\venv on Windows):",
        *pkgs,
        "",
    ]
    return "\n".join(lines)


def generate_bootstrap_script(target_os: str | None = None, profile: str = "full") -> tuple[str, str]:
    """Generate a portable, zero-personal-path installer script for macOS, Windows or Linux."""
    tgt = validate_target_os(target_os)
    prof_id = validate_profile(profile)
    prof = INSTALL_PROFILES[prof_id]
    pkgs = " ".join(prof["packages"])
    mods_tuple = repr(prof["modules"])
    filename = TARGET_SCRIPTS[tgt]["filename"]

    if tgt == "macos":
        script = f"""#!/usr/bin/env bash
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.beatos/bin:$PATH"
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
SUPPORT_ROOT="${{BEATOS_SUPPORT_DIR:-$HOME/.beatos}}"
VENV_DIR="${{BEATOS_VENV_DIR:-$SUPPORT_ROOT/venv}}"
PROFILE="{prof_id}"
PACKAGES="{pkgs}"

echo "=================================================================="
echo "  BeatOS — Instalador de Soporte, Codecs & Modos (macOS)"
echo "  Perfil seleccionado: $PROFILE"
echo "=================================================================="

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: Python 3.10+ no encontrado en el sistema."
  echo "Instala Python desde https://www.python.org/downloads/macos/ o con Homebrew: brew install python"
  exit 1
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit(f"Se requiere Python 3.10+, detectado {{sys.version.split()[0]}}")
print("✔ Python:", sys.version.split()[0])
PY

if ! command -v ffmpeg >/dev/null 2>&1 && command -v brew >/dev/null 2>&1; then
  echo "🍺 Instalando FFmpeg de sistema con Homebrew..."
  brew install ffmpeg || echo "ℹ️ Se usará FFmpeg portable (imageio-ffmpeg) dentro del venv."
fi

mkdir -p "$SUPPORT_ROOT/bin"
if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "📦 Creando entorno virtual aislado en $VENV_DIR..."
  python3 -m venv "$VENV_DIR"
fi

echo "⬇️ Instalando paquetes ($PACKAGES)..."
if command -v uv >/dev/null 2>&1; then
  uv pip install --python "$VENV_DIR/bin/python" --upgrade $PACKAGES
else
  "$VENV_DIR/bin/python" -m pip install --upgrade pip $PACKAGES
fi

echo "🔍 Verificando módulos y códec FFmpeg portable..."
"$VENV_DIR/bin/python" -I -B - <<PY
import importlib
for mod in {mods_tuple}:
    importlib.import_module(mod)
import imageio_ffmpeg
print("✔ Módulos importados OK:", {mods_tuple})
print("✔ FFmpeg portable:", imageio_ffmpeg.get_ffmpeg_exe())
PY

for cand in "$SCRIPT_DIR/vendor/po33_verify.py" "$SCRIPT_DIR/../vendor/po33_verify.py"; do
  if [ -f "$cand" ] && echo "{mods_tuple}" | grep -q "numpy"; then
    "$VENV_DIR/bin/python" -I -B "$cand" --self-check
    break
  fi
done

echo ""
echo "🎉 Soporte de BeatOS listo en: $VENV_DIR"
echo "   Para iniciar BeatOS con todos los modos activos ejecuta ABRIR_BEATOS.command."
"""
        return filename, script

    if tgt == "windows":
        lines = [
            "@echo off",
            "setlocal EnableDelayedExpansion",
            "chcp 65001 >nul",
            'set "SCRIPT_DIR=%~dp0"',
            'if defined BEATOS_SUPPORT_DIR (set "SUPPORT_ROOT=%BEATOS_SUPPORT_DIR%") else (set "SUPPORT_ROOT=%LOCALAPPDATA%\\BeatOS")',
            'if defined BEATOS_VENV_DIR (set "VENV_DIR=%BEATOS_VENV_DIR%") else (set "VENV_DIR=%SUPPORT_ROOT%\\venv")',
            f'set "PROFILE={prof_id}"',
            f'set "PACKAGES={pkgs}"',
            "echo ==================================================================",
            "echo   BeatOS - Support, Codecs and Modes Installer (Windows)",
            "echo   Profile: %PROFILE%",
            "echo ==================================================================",
            "",
            'set "HOST_PY="',
            'where py >nul 2>&1 && (py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1 && set "HOST_PY=py -3")',
            'if not defined HOST_PY where python >nul 2>&1 && (python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1 && set "HOST_PY=python")',
            'if not defined HOST_PY (',
            "  echo ERROR: Python 3.10+ not found in PATH.",
            "  echo Install Python 3.10+ from https://www.python.org/downloads/windows/ and check Add python.exe to PATH.",
            "  pause",
            "  exit /b 1",
            ")",
            "",
            "where ffmpeg >nul 2>&1",
            "if errorlevel 1 (",
            "  where winget >nul 2>&1 && (",
            "    echo Installing FFmpeg via winget...",
            "    winget install --exact --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements",
            "  )",
            ")",
            "",
            'if not exist "%SUPPORT_ROOT%\\bin" mkdir "%SUPPORT_ROOT%\\bin"',
            'if not exist "%VENV_DIR%\\Scripts\\python.exe" (',
            '  echo Creating isolated Python virtualenv at "%VENV_DIR%"...',
            '  %HOST_PY% -m venv "%VENV_DIR%"',
            "  if errorlevel 1 (",
            "    echo ERROR: Failed to create virtualenv.",
            "    pause",
            "    exit /b 1",
            "  )",
            ")",
            "",
            'echo Installing packages: %PACKAGES%...',
            '"%VENV_DIR%\\Scripts\\python.exe" -m pip install --upgrade pip %PACKAGES%',
            "if errorlevel 1 (",
            "  echo ERROR: Package installation failed.",
            "  pause",
            "  exit /b 1",
            ")",
            "",
            f'"%VENV_DIR%\\Scripts\\python.exe" -I -B -c "import importlib, imageio_ffmpeg; [importlib.import_module(m) for m in {mods_tuple}]; print(\'FFmpeg:\', imageio_ffmpeg.get_ffmpeg_exe())"',
            "if errorlevel 1 (",
            "  echo ERROR: Verification failed.",
            "  pause",
            "  exit /b 1",
            ")",
            "",
            "echo.",
            'echo BeatOS support installed at "%VENV_DIR%".',
            "echo Launch BeatOS with ABRIR_BEATOS.bat.",
            "pause",
            "endlocal",
            "",
        ]
        return filename, "\r\n".join(lines)

    # linux
    script = f"""#!/usr/bin/env bash
set -euo pipefail

export PATH="$HOME/.beatos/bin:/usr/local/bin:$PATH"
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
SUPPORT_ROOT="${{BEATOS_SUPPORT_DIR:-$HOME/.beatos}}"
VENV_DIR="${{BEATOS_VENV_DIR:-$SUPPORT_ROOT/venv}}"
PROFILE="{prof_id}"
PACKAGES="{pkgs}"

echo "=================================================================="
echo "  BeatOS — Support, Codecs & Modes Installer (Linux)"
echo "  Profile: $PROFILE"
echo "=================================================================="

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: Python 3.10+ not found. Install python3, python3-venv and ffmpeg via your distro package manager."
  exit 1
fi

python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit(f"Python 3.10+ required, found {{sys.version.split()[0]}}")
print("✔ Python:", sys.version.split()[0])
PY

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ℹ️ System ffmpeg not found in PATH."
  if [ "$(id -u)" -eq 0 ] || command -v sudo >/dev/null 2>&1; then
    SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo -n"
    if command -v apt-get >/dev/null 2>&1; then
      $SUDO apt-get update && $SUDO apt-get install -y ffmpeg libsndfile1 python3-venv || true
    elif command -v dnf >/dev/null 2>&1; then
      $SUDO dnf install -y ffmpeg libsndfile python3-virtualenv || true
    elif command -v pacman >/dev/null 2>&1; then
      $SUDO pacman -S --noconfirm ffmpeg libsndfile || true
    fi
  fi
fi

mkdir -p "$SUPPORT_ROOT/bin"
if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "📦 Creating isolated virtualenv at $VENV_DIR..."
  python3 -m venv "$VENV_DIR" || {{
    echo "ERROR: Could not create venv (on Debian/Ubuntu run: sudo apt install python3-venv)"
    exit 1
  }}
fi

echo "⬇️ Installing packages ($PACKAGES)..."
if command -v uv >/dev/null 2>&1; then
  uv pip install --python "$VENV_DIR/bin/python" --upgrade $PACKAGES
else
  "$VENV_DIR/bin/python" -m pip install --upgrade pip $PACKAGES
fi

echo "🔍 Verifying modules and portable FFmpeg..."
"$VENV_DIR/bin/python" -I -B - <<PY
import importlib
for mod in {mods_tuple}:
    importlib.import_module(mod)
import imageio_ffmpeg
print("✔ Modules OK:", {mods_tuple})
print("✔ Portable FFmpeg:", imageio_ffmpeg.get_ffmpeg_exe())
PY

for cand in "$SCRIPT_DIR/vendor/po33_verify.py" "$SCRIPT_DIR/../vendor/po33_verify.py"; do
  if [ -f "$cand" ] && echo "{mods_tuple}" | grep -q "numpy"; then
    "$VENV_DIR/bin/python" -I -B "$cand" --self-check
    break
  fi
done

echo ""
echo "🎉 BeatOS support ready at: $VENV_DIR"
"""
    return filename, script


def export_bootstrap_pack(destination_dir: str | Path, profile: str = "full") -> dict:
    """Write cross-platform bootstrap installers + requirements-beatos.txt atomically."""
    prof_id = validate_profile(profile)
    dest = Path(destination_dir)
    if dest.exists() and dest.is_symlink():
        raise ValueError("La carpeta de instaladores no puede ser un enlace simbólico")
    dest.mkdir(parents=True, exist_ok=True)
    dest_res = dest.resolve()

    written: list[dict] = []
    entries: list[tuple[str, str, bool]] = []
    for target_id, meta in TARGET_SCRIPTS.items():
        fname, content = generate_bootstrap_script(target_id, prof_id)
        entries.append((fname, content, bool(meta["executable"])))
    entries.append(("requirements-beatos.txt", generate_requirements_txt(prof_id), False))

    for fname, content, is_exec in entries:
        out_path = (dest_res / fname)
        if not out_path.resolve().is_relative_to(dest_res):
            raise ValueError("Ruta de salida inválida")
        if out_path.exists() and out_path.is_symlink():
            raise ValueError(f"Enlace simbólico inesperado en {out_path}")
        raw = content.encode("utf-8")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=dest_res, prefix=".bootstrap-", delete=False) as tf:
                temporary = Path(tf.name)
                tf.write(raw)
                tf.flush()
                os.fsync(tf.fileno())
            os.replace(temporary, out_path)
            if is_exec and not sys.platform.startswith("win"):
                try:
                    os.chmod(out_path, 0o755)
                except OSError:
                    pass
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        written.append({
            "filename": fname,
            "path": str(out_path),
            "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "executable": is_exec,
        })

    return {
        "success": True,
        "profile": prof_id,
        "folder": str(dest_res),
        "files": written,
    }


def format_capabilities_report(caps: dict, lang: str = "es") -> str:
    en = (lang == "en")
    plat = caps["platform"]
    summ = caps["summary"]
    lines = [
        "=" * 68,
        ("🛠️  BEATOS — CAPABILITIES, CODECS & RUNTIME REPORT" if en else "🛠️  BEATOS — DIAGNÓSTICO DE CAPACIDADES, CÓDECS Y MODOS"),
        "=" * 68,
        f"OS: {plat['system']} ({plat['machine']}) · Python {plat['python_version']} ({plat['python_executable']})",
        (f"Managed venv: {plat['managed_venv_dir']} ({'EXISTS' if plat['managed_venv_exists'] else 'NOT CREATED'})"
         if en else
         f"Venv gestionado: {plat['managed_venv_dir']} ({'ACTIVO' if plat['managed_venv_exists'] else 'SIN CREAR'})"),
        f"FFmpeg: {caps['components']['ffmpeg']['path'] or ('NOT FOUND' if en else 'NO ENCONTRADO')}",
        "-" * 68,
    ]
    for mode in caps["modes"]:
        icon = "✅" if mode["status"] == "ready" else ("⚠️" if mode["status"] == "degraded" else "❌")
        title = mode["name_en"] if en else mode["name_es"]
        note = mode["note_en"] if en else mode["note_es"]
        lines.append(f"{icon} [{mode['status'].upper()}] {title}")
        lines.append(f"    {note}")
    lines.append("-" * 68)
    lines.append(
        f"Ready modes: {summ['ready_modes']}/{summ['total_modes']} · Recommended profile: {summ['recommended_profile']}"
        if en else
        f"Modos listos: {summ['ready_modes']}/{summ['total_modes']} · Perfil recomendado: {summ['recommended_profile']}"
    )
    return "\n".join(lines)
