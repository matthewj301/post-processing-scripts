import json
import tempfile
import subprocess
import sys
from pathlib import Path
import unittest
from toolpath_processors.aesthetics import process
from toolpath_processors.viewer import render

HEADER='G21\nG90\nM83\nG1 X0 Y0 Z0.2 F600\n;LAYER_CHANGE\n;TYPE:Internal infill\n'
class ContextTests(unittest.TestCase):
    def test_state_commands_preserve_geometry(self):
        commands='M104 S210\nM140 S100\nM106 S128\nM204 S3000\nSET_PRESSURE_ADVANCE ADVANCE=0.04 SMOOTH_TIME=0.02\nM220 S50\nM221 S90\n'
        report=process(HEADER+'G1 X10 E1\n'+commands+';TYPE:Top surface\nG1 X20 E1\n').report
        self.assertEqual(report['unsupported_commands'],[])
        move=report['spatial_moves'][-1]
        self.assertEqual(move['length_mm'],10)
        self.assertEqual(move['effective_requested_speed_mm_s'],5)
        self.assertEqual(move['effective_extrusion_mm'],.9)
        self.assertEqual(move['commanded_state']['pressure_advance'],.04)
        self.assertAlmostEqual(move['commanded_state']['fan_speed'],128/255)
        self.assertEqual(move['commanded_state']['hotend_target_c'],210)
    def test_distance_weighted_invariance(self):
        reports=[]
        for moves in ('G1 X100 E10\n', ''.join(f'G1 X{i*10} E1\n' for i in range(1,11))):
            report=process(HEADER+moves+';TYPE:Top surface\nG1 X110 E1\n',history_window_mm=35).report
            reports.append(report['cosmetic_entries'][0]['history'])
        for h in reports:
            self.assertEqual(h['covered_deposition_mm'],35)
            self.assertAlmostEqual(h['raw_extrusion_mm'],3.5)
            self.assertAlmostEqual(h['effective_extrusion_mm'],3.5)
            self.assertAlmostEqual(h['nominal_deposition_seconds'],3.5)
            self.assertEqual(h['preceding_feature']['deposition_mm'],100)
            self.assertTrue(h['window_filled'])
    def test_retract_prime_dwell_wait(self):
        report=process(HEADER+'G1 X10 E1\nG1 E-1\nG1 Y5\nG1 E1.2\nG4 P250\nM109 S210\n;TYPE:Top surface\nG1 X20 E1\n').report
        h=report['cosmetic_entries'][0]['history']
        self.assertEqual(h['retract_mm'],1)
        self.assertEqual(h['prime_mm'],1.2)
        self.assertEqual(h['travel_mm'],5)
        self.assertEqual(h['dwell_s'],.25)
        self.assertTrue(h['unknown_wait'])
        self.assertEqual(report['unsupported_commands'],[])
    def test_unknown_invalidates_context(self):
        report=process(HEADER+'M104 S210\nG1 X10 E1\nCUSTOM_THING\nG90\nM83\nG1 X0 Y0 Z0.2 F600\n;TYPE:Top surface\nG1 X10 E1\n').report
        move=report['spatial_moves'][-1]
        self.assertIsNone(move['commanded_state']['hotend_target_c'])
        self.assertIsNone(move['effective_requested_speed_mm_s'])
        self.assertEqual(report['cosmetic_entries'][0]['history']['covered_deposition_mm'],0)
        self.assertEqual(report['unsupported_commands'][0]['command'],'CUSTOM_THING')
    def test_invalid_command_is_not_partially_applied(self):
        for command in ('M106 P-1 S128','M220 S0','SET_PRESSURE_ADVANCE ADVANCE=0.1 UNKNOWN=1','M104 SNaN', 'SET_VELOCITY_LIMIT ACCEL=0', 'SET_VELOCITY_LIMIT MINIMUM_CRUISE_RATIO=1'):
            report=process(HEADER+command+'\n').report
            self.assertEqual(len(report['unsupported_commands']),1,command)
    def test_m204_pt_and_limits(self):
        report=process(HEADER+'M204 P4000 T3000\nSET_VELOCITY_LIMIT ACCEL=2500 VELOCITY=200 SQUARE_CORNER_VELOCITY=5\nG1 X10 E1\n').report
        state=report['spatial_moves'][-1]['commanded_state']
        self.assertEqual(state['acceleration_mm_s2'],2500)
        self.assertEqual(state['velocity_limit_mm_s'],200)
    def test_absolute_e_override(self):
        report=process(HEADER+'M82\nG92 E0\nG1 X10 E1\nM221 S50\nG1 X20 E2\n').report
        self.assertEqual(report['spatial_moves'][-1]['effective_extrusion_mm'],.5)
    def test_history_window_validation(self):
        for value in (0,-1,float('inf'),float('nan')):
            with self.assertRaises(ValueError): process(HEADER,history_window_mm=value)
    def test_html_escapes_embedded_content(self):
        report=process(HEADER+';TYPE:</script><script>alert(1)</script>\nG1 X10 E1\n').report
        html=render(report)
        self.assertNotIn('</script><script>alert(1)',html)
        self.assertIn('\\u003c',html)
    def test_cli_viewer_and_alias_guard(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'input.gcode';viewer=Path(directory)/'viewer.html'
            path.write_text(HEADER+';TYPE:Top surface\nG1 X10 E1\n')
            original=path.read_bytes()
            command=[sys.executable,str(root/'scripts/aesthetics_history.py'),'--report-only',str(path),'--viewer']
            run=subprocess.run(command+[str(viewer)],capture_output=True)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertIn('Toolpath inspector',viewer.read_text())
            self.assertEqual(path.read_bytes(),original)
            run=subprocess.run(command+[str(path)],capture_output=True)
            self.assertNotEqual(run.returncode,0)
            self.assertEqual(path.read_bytes(),original)
if __name__=='__main__': unittest.main()
