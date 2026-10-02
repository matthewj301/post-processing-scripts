"""Opt-in, slowdown-only VFA experiment on verified planar outer-wall moves."""
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import math
from .gcode import State, WORD
from .optimizer import Job, QualityProfile

MARKER = '; QUALITY_OPTIMIZER_VFA_V1'
WALLS = {'outer wall', 'external perimeter'}


@dataclass(frozen=True)
class VFAResult:
    output: str
    report: dict


def in_band(speed, direction, config, padding=0.0):
    return any(low-padding <= abs(component)*speed <= high+padding
               for component, bands in zip(direction[:2], (config.x, config.y))
               if abs(component) > 1e-12 for low, high in bands)


def choose_speed(original, direction, config, previous=None):
    """Choose a safe speed with bounded slowdown and an adjacent-transition cost."""
    padding = config.hysteresis_mm_s if previous is not None else 0.0
    if not in_band(original, direction, config, padding):
        return original
    candidates = {original}
    if previous is not None:
        candidates.add(previous)
    for component, bands in zip(direction[:2], (config.x, config.y)):
        if abs(component) > 1e-12:
            for low, _ in bands:
                candidates.add((low-config.clearance_mm_s)/abs(component))
    lower = original*(1-config.max_slowdown_fraction)
    safe = [v for v in candidates if lower <= v <= original and v > 0
            and not in_band(v, direction, config)]
    if not safe:
        return None
    def cost(v):
        transition = abs(v-previous) if previous is not None else 0.0
        return ((original-v) + config.transition_weight*transition, transition, -v)
    return min(safe, key=cost)


def rewrite_feed(raw, feed, default_ending='\n'):
    """Change only F; retain endpoint, extrusion, and comment text."""
    ending = ('\r\n' if raw.endswith('\r\n') else '\n' if raw.endswith('\n')
              else '\r' if raw.endswith('\r') else default_ending)
    body = raw.rstrip('\r\n')
    code, separator, comment = body.partition(';')
    token = f'F{feed:.9f}'
    if any(m[1].upper() == 'F' for m in WORD.finditer(code)):
        code = WORD.sub(lambda m: token if m[1].upper() == 'F' else m[0], code)
    else:
        code += ' ' + token + ' '
    return code + separator + comment + ending


def validate_edits(lines, replacements, feeds, startup_contract=None):
    """Independently replay every emitted line, including modal restoration.

    Each original command must leave identical state after its replacement
    block. Move geometry/E/context must be identical before the restore too.
    """
    if startup_contract is not None:
        startup_contract.verify_source(''.join(lines))
    original, emitted = State(), State()
    for number, raw in enumerate(lines, 1):
        before_move, before_barrier = original.consume(raw, number)
        block = replacements.get(number, raw)
        block_lines = block.splitlines(keepends=True)
        after_move, after_barrier = emitted.consume(block_lines[0], number)
        if startup_contract is not None:
            startup_contract.apply(original, number)
            startup_contract.apply(emitted, number)
        if before_barrier != after_barrier:
            raise ValueError(f'VFA validation: state barrier changed at line {number}')
        if number in replacements:
            a, b = asdict(before_move), asdict(after_move)
            a.pop('requested_speed_mm_s'); b.pop('requested_speed_mm_s')
            if a != b:
                raise ValueError(f'VFA validation: motion changed at line {number}')
            if not math.isclose(after_move.requested_speed_mm_s, feeds[number]/60, rel_tol=1e-12):
                raise ValueError(f'VFA validation: unexpected feed at line {number}')
            if len(block_lines) != 2:
                raise ValueError('VFA validation: expected one restoration command')
            restore, barrier = emitted.consume(block_lines[1], number)
            if barrier or restore is None or restore.length_mm != 0 or restore.extrusion_mm != 0:
                raise ValueError('VFA validation: restoration caused motion')
        elif before_move != after_move:
            raise ValueError(f'VFA validation: unrelated move changed at line {number}')
        a, b = asdict(original), asdict(emitted)
        fa, fb = a.pop('feed'), b.pop('feed')
        if a != b or (fa != fb and (fa is None or fb is None or not math.isclose(fa, fb, rel_tol=1e-12))):
            raise ValueError(f'VFA validation: modal state not restored at line {number}')


def optimize_vfa(job: Job, profile: QualityProfile) -> VFAResult:
    if profile.filament_diameter_mm != job.profile.filament_diameter_mm:
        raise ValueError('Reparse the job when changing filament diameter')
    config = profile.vfa
    if config is None or not (config.x or config.y):
        raise ValueError('VFA requires explicit calibrated x/y bands in the profile')
    if profile.max_velocity_mm_s is None or profile.max_flow_mm3_s is None:
        raise ValueError('VFA requires explicit max_velocity_mm_s and max_flow_mm3_s')
    if MARKER in job.source:
        raise ValueError('Already VFA-processed; start from the untouched original')
    lines = job.source.splitlines(keepends=True)
    default_ending = '\r\n' if '\r\n' in job.source else '\n'
    replacements, feeds, edits = {}, {}, []
    skipped = Counter()
    previous_speed = previous_segment = None
    restore_feed_token = None
    for segment in job.segments:
        m = segment.move
        for word in WORD.finditer(lines[m.line-1].split(';', 1)[0]):
            if word[1].upper() == 'F': restore_feed_token = word[2]
        if m.feature not in WALLS:
            previous_speed = previous_segment = None
            continue
        speed = m.effective_requested_speed_mm_s
        flow = segment.volumetric_flow_mm3_s
        reason = None
        if (m.command != 'G1' or segment.absolute_xyz is not True or segment.absolute_e is None
                or segment.direction_xyz is None or speed is None or flow is None
                or any(v is None for p in (m.start_xyz, m.end_xyz) for v in p)):
            reason = 'unknown state, unsupported motion, or non-deposition'
        elif m.layer is None or m.layer == 0:
            reason = 'unknown or first layer'
        elif m.start_xyz[2] != m.end_xyz[2]:
            reason = 'nonplanar motion'
        elif m.length_mm < config.min_segment_mm:
            reason = 'segment below minimum length'
        elif (speed > min(profile.max_velocity_mm_s, m.commanded_state.get('velocity_limit_mm_s') or math.inf)
              or flow > profile.max_flow_mm3_s):
            reason = 'input already exceeds configured limits'
        if reason:
            skipped[reason] += 1
            previous_speed = previous_segment = None
            continue
        # Only consecutive wall moves can share hysteresis. Any executable
        # intervening command (including metadata/settings) ends the chain.
        if previous_segment is not None:
            pm = previous_segment.move
            if ((pm.feature, pm.layer, pm.end_xyz) != (m.feature, m.layer, m.start_xyz)
                    or any(line.split(';', 1)[0].strip() for line in lines[pm.line:m.line-1])):
                previous_speed = None
        chosen = choose_speed(speed, segment.direction_xyz, config, previous_speed)
        if chosen is None:
            skipped['no safe speed within slowdown bound'] += 1
            previous_speed = previous_segment = None
            continue
        if math.isclose(chosen, speed, rel_tol=1e-12):
            previous_speed = previous_segment = None
            continue
        factor = m.commanded_state['speed_factor']
        feed = float(f'{chosen/factor*60:.9f}')
        actual = feed/60*factor
        if (not math.isfinite(feed) or feed <= 0 or actual > speed
                or actual < speed*(1-config.max_slowdown_fraction)
                or in_band(actual, segment.direction_xyz, config)):
            skipped['rounded feed cannot satisfy bounds'] += 1
            previous_speed = previous_segment = None
            continue
        raw = lines[m.line-1]
        ending = ('\r\n' if raw.endswith('\r\n') else '\n' if raw.endswith('\n')
                  else '\r' if raw.endswith('\r') else default_ending)
        # Restore even before comments/macros/end-of-file so feed changes cannot leak.
        replacements[m.line] = (rewrite_feed(raw, feed, default_ending) +
                                f'G1 F{restore_feed_token} ; VFA restore original feedrate{ending}')
        feeds[m.line] = feed
        edits.append(dict(line=m.line, reason='avoid configured Cartesian-axis velocity band',
                          old_speed_mm_s=speed, new_speed_mm_s=actual,
                          old_flow_mm3_s=flow, new_flow_mm3_s=flow*actual/speed,
                          nominal_added_seconds=m.length_mm/actual-m.length_mm/speed))
        previous_speed, previous_segment = actual, segment
    if replacements:
        validate_edits(lines, replacements, feeds, job.startup_contract)
    output = ''.join(replacements.get(n, raw) for n, raw in enumerate(lines, 1))
    if edits:
        ending = '\r\n' if '\r\n' in job.source else '\n'
        output = MARKER + ' experimental; retain original for A/B comparison' + ending + output
    return VFAResult(output, dict(
        name='vfa-avoidance', status='experimental; physical benefit unverified',
        changed_segments=len(edits), edits=edits, skipped=dict(skipped),
        parameters=asdict(config),
        nominal_added_seconds=sum(edit['nominal_added_seconds'] for edit in edits),
        output_sha256=hashlib.sha256(output.encode('utf-8')).hexdigest(),
        validation=dict(replayed=bool(edits), geometry_unchanged=True, extrusion_unchanged=True,
                        modal_feed_restored=True),
        limitations=['Only planar outer-wall G1 deposition after the first layer is eligible.',
                     'Bands describe Cartesian toolhead-axis velocity components, not motor speeds.',
                     'Only commanded speeds are checked; acceleration traverses other speeds.',
                     'Unknown state and conditional slicer-intent estimates are never used.',
                     'Physical VFA reduction requires machine-specific calibration and an A/B print.']))
