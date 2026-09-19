"""Annotate cosmetic path entries with preceding commanded extrusion history."""
from dataclasses import asdict, dataclass
import hashlib
from .gcode import State
from .resolution import analyze

PREFIX = '; TOOLPATH_AESTHETICS_V1 '
VISIBLE = {'outer wall', 'top surface', 'external perimeter', 'top solid infill'}

@dataclass
class Result:
    output: str
    report: dict

def process(text: str, *, annotate: bool = True, fit_tolerance_mm: float = 0.02, arc_resolution_mm: float | None = None) -> Result:
    lines = [line for line in text.splitlines(keepends=True) if not line.startswith(PREFIX)]
    state = State()
    events, barriers, output = [], [], []
    previous = None
    active = None
    travel_mm = 0.0
    retracted_mm = 0.0
    for number, line in enumerate(lines, 1):
        move, barrier = state.consume(line, number)
        if barrier:
            previous, active = None, None
            travel_mm = retracted_mm = 0.0
            if line.split(';', 1)[0].strip():
                barriers.append(number)
        if move:
            extrusion = move.extrusion_mm
            depositing = extrusion is not None and extrusion > 0 and move.length_mm is not None and move.length_mm > 0
            key = (move.feature, move.layer)
            if depositing:
                if move.feature in VISIBLE and active != key:
                    event = dict(id=len(events) + 1, entry=asdict(move),
                                 preceding_deposition=previous,
                                 travel_since_deposition_mm=travel_mm,
                                 retraction_since_deposition_mm=retracted_mm,
                                 history_known=previous is not None)
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
        output.append(line)
    clean = ''.join(lines)
    return Result(''.join(output), dict(
        schema_version=2, processor='aesthetics-history',
        input_sha256=hashlib.sha256(clean.encode('utf-8')).hexdigest(),
        assumptions=['Input uses millimeters unless G20 is encountered.',
                     'Speeds and durations are commanded/nominal, not executed motion or measured pressure.',
                     'History records only the most recent deposition segment; no thermal model.',
                     'Unknown executable commands clear inferred state and history.'],
        state_barrier_lines=barriers, cosmetic_entries=events,
        resolution=analyze(lines, fit_tolerance_mm=fit_tolerance_mm, arc_resolution_mm=arc_resolution_mm)))
