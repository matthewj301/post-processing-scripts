"""Read-only export hook and UI-thread report action."""
from pathlib import Path
from threading import Lock
import orca
from ._core.optimizer import QualityProfile, analyze_job, parse_job

_lock = Lock()
_latest = 'No analysis yet. Select Quality analysis in the slicing pipeline, then export G-code.'


def _publish(message):
    global _latest
    with _lock:
        _latest = message


def summarize(report, name):
    coverage = report['coverage']
    dynamics = report['extrusion_dynamics']
    dc = dynamics['coverage']
    lines = [f'Quality analysis: {name}', 'Analysis only — G-code unchanged.',
             f"Input SHA-256: {report['input_sha256']}",
             f"Validation: {report['validation']['status']} (not a physical print qualification)",
             f"Known motion: {coverage['known_motion_moves']} / {coverage['total_moves']} moves",
             f"Known nominal flow: {coverage['known_flow_moves']} moves",
             f"Unknown commands/metadata warnings: {report['warning_count']}",
             f"PA / smoothing / acceleration coverage: {dc['with_pa']} / {dc['with_smoothing']} / {dc['with_acceleration']} of {dc['extrusion_moves']} extrusion moves",
             f"Nominally shorter than smoothing: {dynamics['moves_nominally_shorter_than_smoothing_count']}",
             '', 'Largest nominal flow changes (not measured flow or dQ/dt):']
    for event in dynamics['largest_nominal_flow_transitions'][:5]:
        lines.append(f"Line {event['line']}: {event['flow_delta_mm3_s']:+.2f} mm³/s → {event['nominal_flow_mm3_s']:.2f} ({event['feature']})")
    if not dynamics['largest_nominal_flow_transitions']:
        lines.append('No verified adjacent flow transitions available.')
    lines += ['', 'Linear PA demand samples (unsmoothed extra filament speed):']
    samples = [r for r in dynamics['ramp_samples']
               if r['ramp']['unsmoothed_linear_pa_extra_filament_speed_mm_s'] is not None]
    for row in samples[:5]:
        lines.append(f"Line {row['line']}: {row['ramp']['unsmoothed_linear_pa_extra_filament_speed_mm_s']:.2f} mm/s")
    if not samples:
        lines.append('Unavailable: requires known acceleration and PA in sampled moves.')
    lines += ['', 'Missing evidence / interpretation:']
    for group in report['warning_groups'][:5]:
        lines.append(f"{group['command']}: {group['reason']} ({group['count']})")
    lines += ['Missing firmware defaults remain unknown. No macro execution or live printer access.',
              'Slicer-intent estimates are not substituted for verified state.',
              'Durations, flow and PA demand are commanded-state estimates, not firmware trajectories.',
              'Filament diameter: 1.75 mm assumption; other diameters are rejected when reported by Orca.',
              'No machine flow/velocity limits or startup contract supplied by this adapter.']
    return '\n'.join(lines)


class AnalysisPipeline(orca.slicing.SlicingPipelineCapabilityBase):
    def get_name(self):
        return 'Quality analysis (read-only)'

    def execute(self, ctx):
        if ctx.step != orca.slicing.Step.psGCodePostProcess:
            return orca.ExecutionResult.success()
        _publish('Analysis running. Previous results cleared.')
        try:
            # Do not silently interpret multi-diameter jobs with a single area.
            diameter = ctx.config_value('filament_diameter')
            if diameter is not None:
                values = diameter if isinstance(diameter, (list, tuple)) else [diameter]
                if not values or any(float(v) != 1.75 for v in values):
                    raise ValueError('This adapter currently supports only 1.75 mm filament')
            path = Path(ctx.gcode_path)
            original = path.read_bytes()
            job = parse_job(original.decode('utf-8'), QualityProfile())
            report = analyze_job(job)
            if job.emit().encode('utf-8') != original or path.read_bytes() != original:
                raise ValueError('G-code changed during analysis; result discarded')
            message = summarize(report, str(ctx.output_name))
            _publish(message)
            return orca.ExecutionResult.success(
                f"Quality analysis complete: {report['coverage']['known_flow_moves']} known-flow moves. "
                'Run Show latest quality analysis in Plugins for details. G-code unchanged.')
        except Exception as error:
            message = f'Quality analysis failed; no result available: {error}'
            _publish(message)
            return orca.ExecutionResult.failure(orca.PluginResult.RecoverableError, message)


class ShowAnalysis(orca.script.ScriptPluginCapabilityBase):
    def get_name(self):
        return 'Show latest quality analysis'

    def execute(self):
        with _lock:
            message = _latest
        # Script actions run on the UI thread; the slicing hook never calls UI.
        orca.host.ui.message(message, title='Toolpath quality analysis', buttons='ok', icon='info')
        return orca.ExecutionResult.success()
