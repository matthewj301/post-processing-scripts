"""Known non-motion commands. Values are commanded state, never sensor readings."""
import math
import re

NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)'

def initial_context():
    return dict(hotend_target_c=None, bed_target_c=None, fan_speed=None,
                acceleration_mm_s2=None, pressure_advance=None, smooth_time_s=None,
                speed_factor=1.0, extrusion_factor=1.0)

def known_command(code, context):
    """Return event or None. Parse completely before mutating context."""
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
        if command in ('M104','M109','M140','M190') and set(args) == {'S'} and args['S'] >= 0:
            updates['hotend_target_c' if command in ('M104','M109') else 'bed_target_c'] = args['S']
            if command in ('M109','M190'):
                event.update(duration_s=None, timing_known=False)
        elif command == 'M106' and set(args) <= {'S'} and 0 <= args.get('S',255) <= 255:
            updates['fan_speed'] = args.get('S',255) / 255
        elif command == 'M107' and not args:
            updates['fan_speed'] = 0.0
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
