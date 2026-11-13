"""The installed application and all generated state live below BeatOS/."""
from pathlib import Path

APP_FOLDER = 'BeatOS'
CATALOG_REL = 'BeatOS/data/catalogo.html'
MASTER_DASHBOARD_REL = 'BeatOS/docs/MASTER_ECOSISTEMA_DISCOS.html'
ENTRY_DEFINITIONS = {
    'catalogo_beatos.html': ('beatos', 'Catálogo BeatOS (Beatmaker Station · Rack, Kits y Proyectos MPC)'),
    'catalogo_universal.html': ('universal', 'Catálogo Universal del Ecosistema (Discos Duros y Librerías Analizadas)'),
}
ENTRY_NAMES = ('catalogo_beatos.html', 'catalogo_universal.html')
LEGACY_ENTRY_NAMES = ('catalogo_mpc_sample.html',)


def default_library_root(code_dir):
    code = Path(code_dir).resolve()
    return code.parent if code.name == APP_FOLDER and (code / 'data/catalogo.html').is_file() else code


def data_dir(root):
    return Path(root) / APP_FOLDER / 'data'


def config_dir(root):
    return Path(root) / APP_FOLDER / 'config'


def database_path(root):
    candidates = [data_dir(root) / 'mpc_sample.db',
                  Path(root) / 'SQLITE_DATABASE/mpc_sample.db',
                  Path(root) / '_INDEX_MPC_SAMPLE/mpc_sample.db']
    return next((p for p in candidates if p.is_file()), candidates[0])


def entry_html(name='catalogo_beatos.html', root=None):
    view, label = ENTRY_DEFINITIONS.get(name, ('beatos', 'Abrir BeatOS'))
    if name == 'catalogo_universal.html' and root is not None and (Path(root) / MASTER_DASHBOARD_REL).is_file():
        target_url = MASTER_DASHBOARD_REL
        secondary_link = f'<p><a href="{CATALOG_REL}?view=universal">Abrir Explorador Universal de Muestras (BeatOS)</a></p>'
    else:
        target_url = f'{CATALOG_REL}?view={view}'
        secondary_link = ''
    return ('<!doctype html><html lang="es"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{label}</title><meta http-equiv="refresh" content="0;url={target_url}">'
            f'<p><a href="{target_url}">{label}</a></p>'
            f'{secondary_link}'
            '<p>Para las acciones locales inicia BeatOS/ABRIR_BEATOS.command '
            'o ejecuta BeatOS/installer.py.</p></html>')


def write_catalog(root, html):
    root = Path(root)
    target = root / CATALOG_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    payloads = {target: html, **{root / name: entry_html(name, root=root) for name in ENTRY_NAMES}}
    for path, text in payloads.items():
        temporary = path.with_suffix(path.suffix + '.new')
        try:
            temporary.write_text(text, encoding='utf-8')
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    for legacy_name in LEGACY_ENTRY_NAMES:
        (root / legacy_name).unlink(missing_ok=True)
