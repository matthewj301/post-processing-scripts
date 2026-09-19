"""Per-deposition-path fragmentation, fitted curves and commanded arcs."""
import math
import statistics
from .geometry import fit_circle
from .gcode import State

def distribution(values):
    if not values:
        return None
    ordered = sorted(values)
    def percentile(p):
        index = (len(ordered) - 1) * p
        lo = math.floor(index)
        hi = math.ceil(index)
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)
    return dict(min=min(values), p10=percentile(.1), median=statistics.median(values),
                p90=percentile(.9), max=max(values), mean=statistics.mean(values))

def summarize(moves, tolerance):
    lengths = [m.length_mm for m in moves]
    headings = []
    for a, b in zip(moves, moves[1:]):
        if any(v is None for p in (a.start_xyz, a.end_xyz, b.start_xyz, b.end_xyz) for v in p):
            continue
        u = [y - x for x, y in zip(a.start_xyz, a.end_xyz)]
        v = [y - x for x, y in zip(b.start_xyz, b.end_xyz)]
        norm = math.sqrt(sum(x*x for x in u) * sum(x*x for x in v))
        if norm:
            headings.append(math.degrees(math.acos(max(-1, min(1, sum(x*y for x, y in zip(u, v)) / norm)))))
    curves = []
    i = 0
    while i + 4 <= len(moves):
        sample = moves[i:i+4]
        points = [sample[0].start_xyz] + [m.end_xyz for m in sample]
        if any(v is None for p in points for v in p):
            i += 1
            continue
        fit = fit_circle(points, tolerance)
        if fit is None:
            i += 1
            continue
        end = i + 4
        while end < len(moves) and end - i < 256:
            trial = fit_circle(points + [moves[end].end_xyz], tolerance)
            if trial is None:
                break
            points.append(moves[end].end_xyz)
            fit = trial
            end += 1
        fit.update(start_line=moves[i].line, end_line=moves[end-1].line,
                   capped_at_256_segments=end - i == 256,
                   polyline_length_mm=sum(m.length_mm for m in moves[i:end]))
        curves.append(fit)
        i = end
    return dict(start_line=moves[0].line, end_line=moves[-1].line,
                feature=moves[0].feature, layer=moves[0].layer,
                move_count=len(moves), length_mm=sum(lengths),
                moves_per_mm=len(moves) / sum(lengths),
                segment_length_mm=distribution(lengths),
                heading_change_degrees=distribution(headings),
                fitted_curves=curves)

def analyze(lines, *, fit_tolerance_mm=0.02, arc_resolution_mm=None):
    if not math.isfinite(fit_tolerance_mm) or fit_tolerance_mm <= 0:
        raise ValueError('Fit tolerance must be finite and positive')
    if arc_resolution_mm is not None and (not math.isfinite(arc_resolution_mm) or arc_resolution_mm <= 0):
        raise ValueError('Arc resolution must be finite and positive')
    state = State()
    paths, arcs, pending = [], [], []
    def flush():
        if pending:
            paths.append(summarize(pending, fit_tolerance_mm))
            pending.clear()
    for number, raw in enumerate(lines, 1):
        move, barrier = state.consume(raw, number)
        if barrier or (pending and (state.feature, state.layer) != (pending[-1].feature, pending[-1].layer)):
            flush()
        # Coordinate relabeling is not a physical segment connecting two positions.
        if raw.split(';', 1)[0].strip().upper().startswith('G92'):
            flush()
        if move is None:
            continue
        if move.arc is not None:
            flush()
            item = dict(line=number, feature=move.feature, layer=move.layer, command=move.command,
                        extrusion_mm=move.extrusion_mm, commanded_arc=move.arc.copy(),
                        estimated_firmware_segment_count=None)
            if arc_resolution_mm is not None:
                ratio = move.length_mm / arc_resolution_mm
                if not math.isfinite(ratio):
                    raise ValueError('Arc resolution is too small for this arc')
                item['estimated_firmware_segment_count'] = max(1, math.floor(ratio))
            arcs.append(item)
        elif move.extrusion_mm is not None and move.extrusion_mm > 0 and move.length_mm is not None and move.length_mm > 0:
            pending.append(move)
        elif move.length_mm != 0 or move.extrusion_mm != 0:
            flush()
    flush()
    return dict(fit_tolerance_mm=fit_tolerance_mm, arc_resolution_mm=arc_resolution_mm,
                firmware_estimate_model='Kalico/Klipper-style max(1, floor(helical_length / resolution)); verify installed firmware',
                curve_fit_model='Greedy planar XY circle candidates, >=4 segments, <=256 segments per candidate; heuristic confidence',
                linear_deposition_paths=paths, explicit_arcs=arcs)
