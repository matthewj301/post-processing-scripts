"""Annotate cosmetic path entries with preceding commanded extrusion history."""
from dataclasses import asdict, dataclass
import hashlib
from .gcode import State
from .resolution import analyze
from .history import History

PREFIX = '; TOOLPATH_AESTHETICS_V1 '
VISIBLE = {'outer wall', 'top surface', 'external perimeter', 'top solid infill'}

@dataclass
class Result:
    output: str
    report: dict

def process(text: str, *, annotate: bool = True, fit_tolerance_mm: float = 0.02, arc_resolution_mm: float | None = None, history_window_mm: float = 50.0) -> Result:
    lines = [line for line in text.splitlines(keepends=True) if not line.startswith(PREFIX)]
    state = State()
    history = History(history_window_mm)
    spatial_moves, state_events, unsupported = [], [], []
    events, barriers, output = [], [], []
    previous = None
    active = None
    travel_mm = 0.0
    retracted_mm = 0.0
    for number, line in enumerate(lines, 1):
        move, barrier = state.consume(line, number)
        if state.event:
            history.command(state.event)
            state_events.append(dict(line=number, **state.event))
        if barrier:
            previous, active = None, None
            travel_mm = retracted_mm = 0.0
            if line.split(';', 1)[0].strip():
                barriers.append(number)
                history.reset()
                unsupported.append(dict(line=number, command=line.split(';', 1)[0].strip(),
                                        reason='Unsupported or invalid command; inferred state cleared'))
        if move:
            record = asdict(move)
            record['effective_requested_speed_mm_s'] = move.effective_requested_speed_mm_s
            record['effective_extrusion_mm'] = move.effective_extrusion_mm
            speed = move.effective_requested_speed_mm_s
            duration = move.length_mm / speed if move.length_mm and speed else None
            record['nominal_filament_speed_mm_s'] = move.effective_extrusion_mm / duration if duration and move.effective_extrusion_mm is not None else None
            spatial_moves.append(record)
            extrusion = move.extrusion_mm
            depositing = extrusion is not None and extrusion > 0 and move.length_mm is not None and move.length_mm > 0
            key = (move.feature, move.layer)
            if depositing:
                if move.feature in VISIBLE and active != key:
                    event = dict(id=len(events) + 1, entry=asdict(move),
                                 preceding_deposition=previous,
                                 travel_since_deposition_mm=travel_mm,
                                 retraction_since_deposition_mm=retracted_mm,
                                 history_known=previous is not None, history=history.snapshot())
                    events.append(event)
                    if annotate:
                        ending = '\r\n' if line.endswith('\r\n') else '\n'
                        output.append(f'{PREFIX}entry={event["id"]} feature={move.feature}{ending}')
                active = key
                previous = asdict(move)
                previous['nominal_seconds'] = move.nominal_seconds
                previous['requested_filament_speed_mm_s'] = (extrusion / move.nominal_seconds if move.nominal_seconds else None)
                travel_mm = retracted_mm = 0.0
            else:
                # Unknown geometry/extrusion breaks the history chain.
                if extrusion is None or move.length_mm is None:
                    previous = None
                    travel_mm = retracted_mm = 0.0
                else:
                    travel_mm += move.length_mm
                    retracted_mm += max(0.0, -extrusion)
                if move.length_mm != 0 or extrusion != 0:
                    active = None
            history.add(move)
        output.append(line)
    clean = ''.join(lines)
    return Result(''.join(output), dict(
        schema_version=3, processor='aesthetics-history',
        input_sha256=hashlib.sha256(clean.encode('utf-8')).hexdigest(),
        assumptions=['Input uses millimeters unless G20 is encountered.',
                     'Speeds and durations are commanded/nominal, not executed motion or measured pressure.',
                     'Rolling history is weighted by deposition distance; duration is nominal, not executed.',
                     'Temperature/fan/PA values are commands, not measurements; no thermal or pressure model.',
                     'Speed and extrusion overrides initially assume 100%; become unknown after a state barrier.',
                     'Unknown executable commands clear inferred state and history.'],
        state_barrier_lines=barriers, unsupported_commands=unsupported,
        state_events=state_events, spatial_moves=spatial_moves, cosmetic_entries=events,
        coverage=dict(total_moves=len(spatial_moves),
                      known_geometry_moves=sum(all(v is not None for p in (m['start_xyz'], m['end_xyz']) for v in p) for m in spatial_moves),
                      cosmetic_entries=len(events), unsupported_commands=len(unsupported)),
        resolution=analyze(lines, fit_tolerance_mm=fit_tolerance_mm, arc_resolution_mm=arc_resolution_mm)))
