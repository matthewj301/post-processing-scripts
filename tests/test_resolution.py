import math
import unittest
import tempfile
import subprocess
import sys
import json
from pathlib import Path
from toolpath_processors.aesthetics import process
from toolpath_processors.gcode import State

HEADER = 'G21\nG90\nM83\nG17\nG1 X10 Y0 Z0 F600\n;TYPE:Outer wall\n'

def polyline(sweep=90, count=12, clockwise=False, z=0):
    lines = [HEADER]
    for n in range(1, count+1):
        angle = math.radians(sweep * n/count) * (-1 if clockwise else 1)
        lines.append(f'G1 X{10*math.cos(angle):.8f} Y{10*math.sin(angle):.8f} Z{z*n/count} E0.1\n')
    return ''.join(lines)

class ResolutionTests(unittest.TestCase):
    def resolution(self, text, **kwargs):
        return process(text, **kwargs).report['resolution']
    def test_quarter_circle(self):
        path = self.resolution(polyline())['linear_deposition_paths'][0]
        self.assertEqual(path['move_count'], 12)
        fit = path['fitted_curves'][0]
        self.assertEqual(fit['segment_count'], 12)
        self.assertAlmostEqual(fit['radius_mm'], 10, places=6)
        self.assertAlmostEqual(fit['sweep_degrees'], 90, places=6)
        self.assertAlmostEqual(fit['arc_length_mm'], 5*math.pi, places=6)
        self.assertAlmostEqual(fit['max_chord_error_estimate_mm'], 10*(1-math.cos(math.radians(3.75))), places=6)
        self.assertEqual(fit['fit_confidence'], 'high')
    def test_full_circle_and_clockwise(self):
        for clockwise in (True, False):
            fit = self.resolution(polyline(360, 48, clockwise))['linear_deposition_paths'][0]['fitted_curves'][0]
            self.assertAlmostEqual(fit['sweep_degrees'], 360)
            self.assertEqual(fit['direction'], 'cw' if clockwise else 'ccw')
    def test_straight_square_and_nonplanar_not_curves(self):
        straight = HEADER + ''.join(f'G1 X{10+n} E1\n' for n in range(1,8))
        square = HEADER + 'G1 X10 Y10 E1\nG1 X0 Y10 E1\nG1 X0 Y0 E1\nG1 X10 Y0 E1\n'
        for text in (straight, square, polyline(z=2)):
            self.assertEqual(self.resolution(text)['linear_deposition_paths'][0]['fitted_curves'], [])
    def test_segment_statistics(self):
        path = self.resolution(HEADER+'G1 X11 E1\nG1 X13 E1\nG1 X17 E1\n')['linear_deposition_paths'][0]
        self.assertEqual(path['segment_length_mm']['min'], 1)
        self.assertEqual(path['segment_length_mm']['median'], 2)
        self.assertEqual(path['segment_length_mm']['max'], 4)
        self.assertEqual(path['heading_change_degrees']['max'], 0)
    def test_explicit_arc_and_segment_estimate(self):
        result = self.resolution(HEADER+'G3 X0 Y10 I-10 J0 E1\n', arc_resolution_mm=1)
        arc = result['explicit_arcs'][0]
        self.assertAlmostEqual(arc['commanded_arc']['sweep_degrees'], 90)
        self.assertEqual(arc['estimated_firmware_segment_count'], 15)
        self.assertEqual(result['linear_deposition_paths'], [])
    def test_helical_and_full_arc(self):
        arc = self.resolution(HEADER+'G2 I-10 Z5 E2\n', arc_resolution_mm=2)['explicit_arcs'][0]
        self.assertAlmostEqual(arc['commanded_arc']['sweep_degrees'], 360)
        self.assertAlmostEqual(arc['commanded_arc']['helical_length_mm'], math.hypot(20*math.pi,5))
        self.assertEqual(arc['estimated_firmware_segment_count'], 31)
    def test_no_resolution_no_estimate(self):
        arc = self.resolution(HEADER+'G3 X0 Y10 I-10 E1\n')['explicit_arcs'][0]
        self.assertIsNone(arc['estimated_firmware_segment_count'])
    def test_unsupported_arcs_are_barriers(self):
        for arc in ('G3 X0 Y10 R10', 'G18\nG3 X0 Z10 I-10', 'G91\nG3 X0 Y10 I-10', 'G3 X0 Y15 I-10'):
            result = process(HEADER+arc+'\n').report
            self.assertEqual(result['resolution']['explicit_arcs'], [])
            self.assertTrue(result['state_barrier_lines'])
    def test_arc_updates_state_and_absolute_extrusion(self):
        text = HEADER+'M82\nG92 E0\nG3 X0 Y10 I-10 E1\nG1 X0 Y20 E2\n'
        entries = process(text).report['cosmetic_entries']
        self.assertEqual(entries[0]['entry']['command'], 'G3')
        path = self.resolution(text)['linear_deposition_paths'][0]
        self.assertEqual(path['length_mm'], 10)
        state = State()
        for n, line in enumerate(text.splitlines()): move, _ = state.consume(line, n)
        self.assertEqual(move.extrusion_mm, 1)
    def test_travel_layer_feature_split(self):
        for boundary in ('G1 Y1\n', ';LAYER_CHANGE\n', ';TYPE:Top surface\n', 'G92 X0\n'):
            paths = self.resolution(HEADER+'G1 X11 E1\n'+boundary+'G1 X12 E1\n')['linear_deposition_paths']
            self.assertEqual(len(paths), 2, boundary)
    def test_fit_tolerance_and_bad_parameters(self):
        for kwargs in ({'fit_tolerance_mm':0}, {'fit_tolerance_mm':float('nan')}, {'arc_resolution_mm':-1}, {'arc_resolution_mm':float('inf')}):
            with self.assertRaises(ValueError): self.resolution(HEADER, **kwargs)
    def test_cli_flags(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'arc.gcode'
            path.write_text(HEADER+'G3 X0 Y10 I-10 E1\n')
            original = path.read_bytes()
            run = subprocess.run([sys.executable, str(root/'scripts/aesthetics_history.py'),
                                  '--report-only', '--arc-resolution-mm', '0.5',
                                  '--fit-tolerance-mm', '0.01', str(path)], capture_output=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            report = json.loads(Path(str(path)+'.aesthetics.json').read_text())
            self.assertEqual(report['resolution']['explicit_arcs'][0]['estimated_firmware_segment_count'], 31)
            self.assertEqual(path.read_bytes(), original)
    def test_repeat_annotations_preserve_geometry_report(self):
        text = polyline() + 'G3 X-10 Y0 I0 J-10 E1\n'
        first = process(text, arc_resolution_mm=.5)
        self.assertEqual(first, process(first.output, arc_resolution_mm=.5))

if __name__ == '__main__': unittest.main()
