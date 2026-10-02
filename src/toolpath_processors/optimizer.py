"""Lossless quality-optimizer foundation; no motion transformations enabled."""
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
from .gcode import Move, State
from .contracts import StartupContract


@dataclass(frozen=True)
class VFAProfile:
    # Cartesian toolhead-axis bands in mm/s, not CoreXY motor speeds.
    x: tuple = ()
    y: tuple = ()
    min_segment_mm: float = 5.0
    max_slowdown_fraction: float = 0.15
    clearance_mm_s: float = 1.0
    hysteresis_mm_s: float = 1.0
    transition_weight: float = 1.0

    def __post_init__(self):
        for axis in ('x', 'y'):
            bands = getattr(self, axis)
            if not isinstance(bands, (tuple, list)):
                raise ValueError(f'VFA {axis} bands must be a list of [low, high] pairs')
            for band in bands:
                if (not isinstance(band, (tuple, list)) or len(band) != 2 or
                        any(type(v) not in (int, float) or not math.isfinite(v) for v in band) or
                        not 0 < band[0] < band[1]):
                    raise ValueError(f'Invalid VFA {axis} band')
            object.__setattr__(self, axis, tuple(tuple(band) for band in bands))
        for key in ('min_segment_mm', 'max_slowdown_fraction', 'clearance_mm_s',
                    'hysteresis_mm_s', 'transition_weight'):
            value = getattr(self, key)
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f'Invalid VFA {key}')
        if self.min_segment_mm <= 0 or self.clearance_mm_s <= 0 or not 0 < self.max_slowdown_fraction < 1:
            raise ValueError('VFA length/clearance must be positive and slowdown fraction in (0, 1)')


@dataclass(frozen=True)
class QualityProfile:
    filament_diameter_mm: float = 1.75
    max_velocity_mm_s: float | None = None
    max_flow_mm3_s: float | None = None
    tiny_segment_mm: float = 0.05
    vfa: VFAProfile | None = None

    def __post_init__(self):
        if self.vfa is not None and not isinstance(self.vfa, VFAProfile):
            raise ValueError('vfa must be a VFAProfile')
        for key, value in asdict(self).items():
            if key == 'vfa': continue
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or not math.isfinite(value) or value <= 0):
                raise ValueError(f'{key} must be a finite positive number')
        if self.filament_diameter_mm is None or self.tiny_segment_mm is None:
            raise ValueError('Filament diameter and tiny-segment threshold are required')

    @classmethod
    def from_json(cls, text):
        values = json.loads(text)
        if not isinstance(values, dict) or set(values) - set(cls.__dataclass_fields__):
            raise ValueError('Profile must be an object containing only supported profile fields')
        if values.get('vfa') is not None:
            config = values['vfa']
            if not isinstance(config, dict) or set(config) - set(VFAProfile.__dataclass_fields__):
                raise ValueError('Invalid VFA profile fields')
            values['vfa'] = VFAProfile(**config)
        return cls(**values)


@dataclass(frozen=True)
class SlicerIntent:
    """Diagnostic source E/F estimates, never authority for a transformation."""
    line: int
    length_mm: float | None
    extrusion_mm: float | None
    requested_speed_mm_s: float | None
    nominal_duration_s: float | None
    volumetric_flow_mm3_s: float | None


def consume_intent(state, raw, number):
    # Only this diagnostic track assumes custom macros/tool selection preserve
    # slicer modes. Drop coordinates and feed: macro motion is not reconstructed.
    modes = state.absolute_xyz, state.absolute_e, state.millimeters, state.plane
    move, barrier = state.consume(raw, number)
    code = raw.split(';', 1)[0].strip()
    if barrier and code:
        command = code.split()[0].upper()
        if (re.fullmatch(r'T\d+', command) or
                re.fullmatch(r'(?![GMT]\d)[A-Z_][A-Z0-9_]*', command)):
            state.absolute_xyz, state.absolute_e, state.millimeters, state.plane = modes
    return move


@dataclass(frozen=True)
class PathSegment:
    move: Move
    width_mm: float | None
    height_mm: float | None
    direction_xyz: tuple | None
    nominal_duration_s: float | None
    volumetric_flow_mm3_s: float | None
    flow_delta_mm3_s: float | None
    is_cosmetic: bool
    absolute_xyz: bool | None = None
    absolute_e: bool | None = None


@dataclass(frozen=True)
class Job:
    source: str
    segments: tuple[PathSegment, ...]
    warnings: tuple[dict, ...]
    slicer_intent_segments: tuple[SlicerIntent, ...] = ()
    profile: QualityProfile = QualityProfile()
    startup_contract: StartupContract | None = None

    def emit(self):
        """Preserve every source character, including comments and line endings."""
        return self.source


def parse_job(text: str, profile: QualityProfile | None = None, *, startup_contract: StartupContract | None = None) -> Job:
    profile = profile or QualityProfile()
    if '\x00' in text:
        raise ValueError('Binary G-code is unsupported')
    if startup_contract is not None:
        startup_contract.verify_source(text)
    state = State()
    intent_state = State()
    width = height = previous_flow = None
    segments, warnings, intent_segments = [], [], []
    area = math.pi * (profile.filament_diameter_mm / 2) ** 2
    for number, raw in enumerate(text.splitlines(keepends=True), 1):
        stripped = raw.strip()
        for label, name in ((';WIDTH:', 'width'), ('; LINE_WIDTH:', 'width'),
                            (';HEIGHT:', 'height'), ('; LAYER_HEIGHT:', 'height')):
            if stripped.startswith(label):
                try:
                    value = float(stripped[len(label):])
                    if not math.isfinite(value) or value <= 0:
                        raise ValueError
                except ValueError:
                    value = None
                    warnings.append(dict(line=number, reason=f'Invalid {name} metadata'))
                if name == 'width': width = value
                else: height = value
        intent_move = consume_intent(intent_state, raw, number)
        move, barrier = state.consume(raw, number)
        if startup_contract is not None:
            startup_contract.apply(state, number)
        if barrier:
            previous_flow = None
            if raw.split(';', 1)[0].strip():
                width = height = None
                warnings.append(dict(line=number, command=raw.split(';', 1)[0].strip().split()[0].upper(),
                                     reason='Unsupported or invalid command; inferred state cleared'))
        if state.event and (not state.event.get('metadata') or state.event.get('history_boundary')):
            # Flow adjacency is deliberately local, never inferred across settings/waits.
            previous_flow = None
        if intent_move is not None:
            ilength, iextrusion, ispeed = (intent_move.length_mm, intent_move.extrusion_mm,
                                         intent_move.requested_speed_mm_s)
            itime = ilength / ispeed if ilength and ispeed else None
            iflow = iextrusion * area / itime if itime and iextrusion is not None and iextrusion > 0 else None
            intent_segments.append(SlicerIntent(number, ilength, iextrusion, ispeed, itime, iflow))
        if move is None:
            continue
        length = move.length_mm
        speed = move.effective_requested_speed_mm_s
        extrusion = move.effective_extrusion_mm
        duration = length / speed if length is not None and length > 0 and speed and speed > 0 else None
        flow = extrusion * area / duration if duration and extrusion is not None and extrusion > 0 else None
        direction = None
        if (move.command in ('G0', 'G1') and length and
                all(v is not None for point in (move.start_xyz, move.end_xyz) for v in point)):
            direction = tuple((b-a)/length for a, b in zip(move.start_xyz, move.end_xyz))
        segments.append(PathSegment(move, width, height, direction, duration, flow,
                                    flow - previous_flow if flow is not None and previous_flow is not None else None,
                                    move.feature in {'outer wall', 'top surface', 'external perimeter', 'top solid infill'},
                                    state.absolute_xyz, state.absolute_e))
        previous_flow = flow
    return Job(text, tuple(segments), tuple(warnings), tuple(intent_segments), profile, startup_contract)


def analyze_job(job: Job, profile: QualityProfile | None = None, *, details: bool = False) -> dict:
    profile = profile or job.profile
    if profile.filament_diameter_mm != job.profile.filament_diameter_mm:
        raise ValueError('Reparse the job when changing filament diameter')
    violations, unknown, tiny = [], [], []
    for segment in job.segments:
        move = segment.move
        values = [move.length_mm, move.extrusion_mm, move.requested_speed_mm_s,
                  segment.nominal_duration_s, segment.volumetric_flow_mm3_s]
        values += list(move.start_xyz or ()) + list(move.end_xyz or ())
        if any(v is not None and not math.isfinite(v) for v in values):
            violations.append(dict(line=move.line, reason='Nonfinite reconstructed motion'))
        if (move.length_mm is None or move.extrusion_mm is None or move.requested_speed_mm_s is None
                or move.effective_requested_speed_mm_s is None or move.effective_extrusion_mm is None
                or any(v is None for point in (move.start_xyz, move.end_xyz) for v in point)):
            unknown.append(move.line)
        if move.length_mm is not None and 0 < move.length_mm < profile.tiny_segment_mm:
            tiny.append(move.line)
        for value, limit, reason in (
            (move.effective_requested_speed_mm_s, profile.max_velocity_mm_s, 'Commanded velocity exceeds profile'),
            (segment.volumetric_flow_mm3_s, profile.max_flow_mm3_s, 'Nominal flow exceeds profile')):
            if value is not None and limit is not None and value > limit:
                violations.append(dict(line=move.line, reason=reason, value=value, limit=limit))
    sample_limit = 20
    warnings = {}
    for warning in job.warnings:
        key = warning.get('command', 'metadata'), warning['reason']
        group = warnings.setdefault(key, dict(command=key[0], reason=key[1], count=0, sample_lines=[]))
        group['count'] += 1
        if len(group['sample_lines']) < sample_limit:
            group['sample_lines'].append(warning['line'])
    intent_segments = job.slicer_intent_segments
    intent_flows = [s.volumetric_flow_mm3_s for s in intent_segments if s.volumetric_flow_mm3_s is not None]
    intent_lengths = [s.length_mm for s in intent_segments if s.length_mm is not None]
    report = dict(schema_version=2, processor='quality-optimizer', mode='analysis-only',
                  detail_level='full' if details else 'summary',
                  input_sha256=hashlib.sha256(job.source.encode('utf-8')).hexdigest(),
                  profile=asdict(profile), modifications=[],
                  coverage=dict(total_moves=len(job.segments),
                                known_motion_moves=len(job.segments)-len(unknown),
                                known_flow_moves=sum(s.volumetric_flow_mm3_s is not None for s in job.segments),
                                features=dict(sorted(Counter(s.move.feature for s in job.segments).items())),
                                layers=len({s.move.layer for s in job.segments if s.move.layer is not None})),
                  validation=dict(source_preserved=job.emit() == job.source,
                                  status='violations' if violations else 'incomplete' if unknown or job.warnings else 'checked',
                                  violation_count=len(violations),
                                  violations=violations if details else violations[:sample_limit],
                                  unknown_motion_count=len(unknown),
                                  unknown_motion_lines=unknown if details else unknown[:sample_limit]),
                  warning_count=len(job.warnings), warning_groups=list(warnings.values()),
                  tiny_segment_count=len(tiny), tiny_segment_lines=tiny if details else tiny[:sample_limit],
                  sample_limit=None if details else sample_limit,
                  slicer_intent=dict(
                      status='conditional_estimate', usable_for_optimization=False,
                      basis='Source XYZ/E/F only; assumes custom macros and tool selection preserve slicer modes. '
                            'Coordinates and feed are discarded at barriers and must be re-established. '
                            'Excludes M220/M221 overrides and hidden macro motion, extrusion, or timing.',
                      total_moves=len(intent_segments),
                      known_length_moves=len(intent_lengths), known_flow_moves=len(intent_flows),
                      tiny_segment_count=sum(0 < length < profile.tiny_segment_mm for length in intent_lengths),
                      nominal_path_length_mm=sum(intent_lengths),
                      max_volumetric_flow_mm3_s=max(intent_flows, default=None)),
                  assumptions=['Durations and flow use commanded speed, not firmware look-ahead or acceleration.',
                               'Volumetric flow assumes filament-length E in millimeters and the configured filament diameter.',
                               'Standard command meanings are assumed; firmware command overrides are not evaluated.',
                               'Object markers describe the complete job; runtime object exclusions are not simulated.',
                               'Indexed fan values have no assumed mapping to the active part-cooling fan.',
                               'Unknown macros and tool changes invalidate verified state; conditional slicer intent is separate.',
                               'No physical quality benefit or firmware execution safety is certified.'])
    if job.startup_contract is not None:
        report['startup_contract'] = asdict(job.startup_contract)
        report['assumptions'].append('Startup multipliers come from the supplied audited contract; its config fingerprint is provenance, not a live firmware check.')
    if details:
        report['warnings'] = list(job.warnings)
        report['segments'] = [asdict(segment) for segment in job.segments]
        report['slicer_intent']['segments'] = [asdict(segment) for segment in intent_segments]
    return report
