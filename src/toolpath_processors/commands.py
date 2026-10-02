"""Known non-motion commands. Values are commanded state, never sensor readings."""
import json
import math
import re

NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)'

def metadata_command(code):
    """Validate standard bookkeeping commands without changing motion state.

    Object markers assume the complete job, with no objects excluded at runtime.
    EXCLUDE_OBJECT itself is intentionally not accepted.
    """
    command = code.split()[0].upper()
    allowed = {
        'EXCLUDE_OBJECT_DEFINE': {'NAME', 'CENTER', 'POLYGON', 'RESET', 'JSON'},
        'EXCLUDE_OBJECT_START': {'NAME'},
        'EXCLUDE_OBJECT_END': {'NAME'},
        'SET_PRINT_STATS_INFO': {'TOTAL_LAYER', 'CURRENT_LAYER'},
    }
    if command not in allowed:
        return None
    tail = code[len(code.split()[0]):].strip()
    matches = list(re.finditer(r'([A-Za-z_]+)=(.*?)(?=\s+[A-Za-z_]+=|$)', tail))
    args = {}
    cursor = 0
    for match in matches:
        if tail[cursor:match.start()].strip(): return None
        key, value = match[1].upper(), match[2].strip()
        if key not in allowed[command] or key in args or not value: return None
        args[key] = value
        cursor = match.end()
    if tail[cursor:].strip(): return None
    if command == 'EXCLUDE_OBJECT_START' and 'NAME' not in args: return None
    if ('CENTER' in args or 'POLYGON' in args) and 'NAME' not in args: return None
    if 'NAME' in args and not re.fullmatch(r'[A-Za-z0-9_.-]+', args['NAME']): return None
    try:
        for key in ('RESET', 'JSON', 'TOTAL_LAYER', 'CURRENT_LAYER'):
            if key in args:
                if not re.fullmatch(r'\d+', args[key]): return None
                if key in ('RESET', 'JSON') and int(args[key]) not in (0, 1): return None
        if 'CENTER' in args:
            center = [float(v) for v in args['CENTER'].split(',')]
            if len(center) != 2 or not all(math.isfinite(v) for v in center): return None
        if 'POLYGON' in args:
            polygon = json.loads(args['POLYGON'])
            if not isinstance(polygon, list) or len(polygon) < 3: return None
            if not all(isinstance(point, list) and len(point) == 2 and
                       all(type(v) in (int, float) and math.isfinite(v) for v in point)
                       for point in polygon): return None
    except (ValueError, OverflowError):
        return None
    return dict(command=command, duration_s=0.0, timing_known=True,
                updates={}, metadata=True,
                history_boundary=command.startswith('EXCLUDE_OBJECT_'))


def initial_context():
    return dict(hotend_target_c=None, bed_target_c=None, fan_speed=None,
                acceleration_mm_s2=None, pressure_advance=None, smooth_time_s=None,
                speed_factor=1.0, extrusion_factor=1.0)

def known_command(code, context):
    """Return event or None. Parse completely before mutating context."""
    metadata = metadata_command(code)
    if metadata is not None:
        return metadata
    parts = code.split()
    command = parts[0].upper()
    updates = {}
    event = dict(command=command, duration_s=0.0, timing_known=True)
    if command in ('SET_PRESSURE_ADVANCE', 'SET_VELOCITY_LIMIT'):
        allowed = ({'ADVANCE':'pressure_advance', 'SMOOTH_TIME':'smooth_time_s'} if command == 'SET_PRESSURE_ADVANCE'
                   else {'ACCEL':'acceleration_mm_s2', 'VELOCITY':'velocity_limit_mm_s',
                         'SQUARE_CORNER_VELOCITY':'square_corner_velocity_mm_s', 'MINIMUM_CRUISE_RATIO':'minimum_cruise_ratio'})
        seen = set()
        for token in parts[1:]:
            if '=' not in token: return None
            key, value = token.split('=', 1)
            key = key.upper()
            if key not in allowed or key in seen: return None
            seen.add(key)
            try: value = float(value)
            except ValueError: return None
            if not math.isfinite(value) or value < 0: return None
            if key in ('ACCEL', 'VELOCITY') and value == 0: return None
            if key == 'MINIMUM_CRUISE_RATIO' and value >= 1: return None
            updates[allowed[key]] = value
        if not updates: return None
    else:
        match = re.fullmatch(r'(M\d+|G4)\s*(.*)', code.upper())
        if not match: return None
        command, tail = match.groups()
        pairs = re.findall(r'([A-Z])\s*(' + NUMBER + ')', tail)
        if re.sub(r'([A-Z])\s*(' + NUMBER + ')', '', tail).strip(): return None
        if len(dict(pairs)) != len(pairs): return None
        args = {k:float(v) for k,v in pairs}
        if not all(math.isfinite(v) for v in args.values()): return None
        event['command'] = command
        if command == 'M73' and args and set(args) <= {'P', 'R'} and all(v >= 0 for v in args.values()) and args.get('P', 0) <= 100:
            event.update(metadata=True, history_boundary=False)
        elif command in ('M104', 'M109') and 'S' in args and set(args) <= {'S', 'T'} and args['S'] >= 0 and args.get('T', 0) >= 0 and args.get('T', 0.0).is_integer():
            if 'T' in args:
                updates[f'hotend_target_t{int(args["T"])}_c'] = args['S']
                # Active tool is not inferred from tool-change macros.
                updates['hotend_target_c'] = None
            else:
                updates['hotend_target_c'] = args['S']
            if command == 'M109': event.update(duration_s=None, timing_known=False)
        elif command in ('M140','M190') and set(args) == {'S'} and args['S'] >= 0:
            updates['bed_target_c'] = args['S']
            if command == 'M190':
                event.update(duration_s=None, timing_known=False)
        elif command == 'M106' and set(args) <= {'S', 'P'} and 0 <= args.get('S',255) <= 255 and args.get('P', 0) >= 0 and args.get('P', 0.0).is_integer():
            key = f'fan_p{int(args["P"])}_speed' if 'P' in args else 'fan_speed'
            updates[key] = args.get('S',255) / 255
            if 'P' in args:
                # Vendor fan-index mapping is unknown; don't claim an active fan value.
                updates['fan_speed'] = None
        elif command == 'M107' and set(args) <= {'P'} and args.get('P', 0) >= 0 and args.get('P', 0.0).is_integer():
            key = f'fan_p{int(args["P"])}_speed' if 'P' in args else 'fan_speed'
            updates[key] = 0.0
            if 'P' in args: updates['fan_speed'] = None
        elif command in ('M220','M221') and set(args) <= {'S'} and args.get('S',100) > 0:
            updates['speed_factor' if command == 'M220' else 'extrusion_factor'] = args.get('S',100) / 100
        elif command == 'M204' and set(args) <= {'S','P','T'} and args and all(v > 0 for v in args.values()):
            if 'S' in args: value = args['S']
            elif set(args) == {'P','T'}: value = min(args.values())
            else: return None
            updates['acceleration_mm_s2'] = value
        elif command == 'G4' and set(args) == {'P'} and args['P'] >= 0:
            event['duration_s'] = args['P']/1000
        elif command in ('M400', 'M109', 'M190') and not args:
            event.update(duration_s=None, timing_known=False)
        else:
            return None
    context.update(updates)
    event['updates'] = updates
    return event
