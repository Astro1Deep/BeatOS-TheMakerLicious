"""ACVS 1.3.0.12 consistency helpers, based on native MPC Sample projects."""
from copy import deepcopy
import re


def normalize_key(value):
    """Normalize observed aliases without guessing unsupported scales."""
    if not isinstance(value, str):
        return value
    m = re.fullmatch(r'([A-G])([b#]?)\s+(Major|Minor|Natural Minor)', value.strip(), re.I)
    if not m:
        return value
    root = m[1].upper() + m[2]
    root = {'Db':'C#','Eb':'D#','Gb':'F#','Ab':'G#','Bb':'A#'}.get(root, root)
    scale = 'Major' if m[3].lower() == 'major' else 'Natural Minor'
    return f'{root} {scale}'


def restore_mixer_tracks(data):
    """Restore missing track wrappers from the project's own mixer programs.

    Native projects represent the same bus program in both locations. Never
    overwrite existing track wrappers or copy effects from another project.
    """
    tracks = data['tracks']
    if not tracks:
        raise ValueError('No track to derive wrapper from')
    names = {t['name'] for t in tracks}
    for field, typ, colour in [('submixes', 8, 16739607), ('outputs', 9, 10660269)]:
        for program in data.get('mixer', {}).get(field, []):
            name = program.get('name')
            if not name or program.get('type') != typ or name in names:
                continue
            t = deepcopy(tracks[0])
            t.update(name=name, colour=colour, samples=[], recordArm=False,
                     arrangementClipMap=[], sharedClipMap=[], program=deepcopy(program))
            t['midiInputRoute'] = {'inputPort': {'type': 0, 'deviceName': 'All Ports', 'deviceId': '', 'os': 'Linux'}, 'inputChannel': 0}
            t['midiOutputRoute'] = {'outputPort': {'type': 1, 'deviceName': '<none>', 'deviceId': '', 'os': 'Linux'}, 'outputChannel': 0}
            tracks.append(t)
            names.add(name)


def reconcile_generated_clips(data, source_name=None, new_names=()):
    """Synchronize generated sequence maps; never silently discard MIDI events."""
    names = [t['name'] for t in data['tracks']]
    for entry in data.get('sequences', []):
        seq = entry['value']
        for clips in seq.get('trackClipMaps', []):
            if not clips:
                raise ValueError('Empty sequence clip map has no prototype')
            if source_name and source_name not in names:
                old = next((c for c in clips if c['key'] == source_name), None)
                if old and new_names:
                    if old['value'].get('eventList', {}).get('events') and len(new_names) != 1:
                        raise ValueError('Cannot split nonempty MIDI blindly')
                    for name in new_names:
                        if not any(c['key'] == name for c in clips):
                            c = deepcopy(old); c['key'] = name; c['value']['name'] = name; clips.append(c)
                    clips.remove(old)
            for c in clips:
                if c['key'] not in names:
                    raise ValueError(f"Orphan sequence clip: {c['key']}")
            existing = {c['key'] for c in clips}
            for name in names:
                if name not in existing:
                    c = deepcopy(clips[0]); c['key'] = name; c['value']['name'] = name
                    c['value']['eventList']['events'] = []
                    clips.append(c)

