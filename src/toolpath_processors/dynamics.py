"""Read-only extrusion diagnostics; no firmware trajectory reconstruction."""
import math


def analyze_dynamics(job, *, details=False):
    rows, transitions = [], []
    coverage = dict(extrusion_moves=0, with_acceleration=0, with_pa=0,
                    with_smoothing=0, with_ramp_estimate=0)
    for segment in job.segments:
        move = segment.move
        length, extrusion, speed = (move.length_mm, move.effective_extrusion_mm,
                                    move.effective_requested_speed_mm_s)
        if not (length and length > 0 and extrusion is not None and extrusion > 0
                and speed and speed > 0):
            continue
        coverage['extrusion_moves'] += 1
        state = move.commanded_state
        accel = state.get('acceleration_mm_s2')
        pa = state.get('pressure_advance')
        smoothing = state.get('smooth_time_s')
        for key, value in (('with_acceleration', accel), ('with_pa', pa),
                           ('with_smoothing', smoothing)):
            coverage[key] += value is not None
        row = dict(line=move.line, feature=move.feature, length_mm=length,
                   nominal_flow_mm3_s=segment.volumetric_flow_mm3_s,
                   nominal_duration_s=segment.nominal_duration_s,
                   acceleration_mm_s2=accel, pressure_advance_s=pa,
                   smooth_time_s=smoothing, ramp=None)
        # Only straight deposition paths: arc limits and extrusion-only motion
        # require different models. All ramps below are explicit scenarios.
        if move.command in ('G0', 'G1') and accel is not None and accel > 0:
            ratio = extrusion / length
            ramp_time = speed / accel
            row['ramp'] = dict(
                zero_to_requested_speed_s=ramp_time,
                rest_to_rest_distance_at_requested_speed_mm=speed * ramp_time,
                rest_to_rest_peak_speed_mm_s=min(speed, math.sqrt(accel * length)),
                nominal_filament_speed_mm_s=ratio * speed,
                nominal_filament_acceleration_mm_s2=ratio * accel,
                unsmoothed_linear_pa_extra_filament_speed_mm_s=(pa * ratio * accel if pa is not None else None),
                smoothing_to_ramp_time_ratio=(smoothing / ramp_time if smoothing is not None else None))
            coverage['with_ramp_estimate'] += 1
        rows.append(row)
        # Parser already breaks adjacency at waits, settings, macros, travel,
        # retractions and layer/object boundaries. Never bridge those gaps here.
        if segment.flow_delta_mm3_s is not None:
            transitions.append(dict(line=move.line, feature=move.feature,
                                    flow_delta_mm3_s=segment.flow_delta_mm3_s,
                                    nominal_flow_mm3_s=segment.volumetric_flow_mm3_s,
                                    is_cosmetic=segment.is_cosmetic))
    ranked = sorted(transitions, key=lambda r: abs(r['flow_delta_mm3_s']), reverse=True)
    short = [r for r in rows if r['smooth_time_s'] is not None
             and r['nominal_duration_s'] < r['smooth_time_s']]
    report = dict(
        status='diagnostic-only', usable_for_optimization=False, coverage=coverage,
        adjacent_flow_transition_count=len(transitions),
        moves_nominally_shorter_than_smoothing_count=len(short),
        largest_nominal_flow_transitions=ranked if details else ranked[:20],
        ramp_samples=[r for r in rows if r['ramp'] is not None][:20],
        short_move_sample_lines=[r['line'] for r in short][:20],
        assumptions=[
            'Commanded state only; missing firmware defaults remain unknown.',
            'Ramp estimates assume constant commanded acceleration and fixed E/path ratio.',
            'Zero-entry and rest-to-rest scenarios are not predictions of actual junction speeds.',
            'PA demand is the unsmoothed linear-model extra filament speed K * E/path * acceleration, not a hardware limit or total motor speed.',
            'No look-ahead, input shaping, firmware velocity caps, melt pressure, or sensor feedback is simulated.',
            'Flow jumps are nominal adjacent differences, not dQ/dt; transition time is unknown.',
            'Shorter than smoothing is a diagnostic observation, not evidence of a defect.'])
    if details:
        report['extrusion_moves'] = rows
    return report
