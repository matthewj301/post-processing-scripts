import math
import unittest
from toolpath_processors.optimizer import parse_job, analyze_job

START = 'G90\nM83\nG92 X0 Y0 Z0 E0\n'
SETTINGS = 'SET_VELOCITY_LIMIT ACCEL=50000\nSET_PRESSURE_ADVANCE ADVANCE=0.02 SMOOTH_TIME=0.04\n'


class DynamicsTests(unittest.TestCase):
    def report(self, source, details=True):
        job = parse_job(source)
        self.assertEqual(job.emit(), source)
        report = analyze_job(job, details=details)
        self.assertEqual(report['modifications'], [])
        return report['extrusion_dynamics']

    def test_analytical_ramp_and_short_move(self):
        report = self.report(START + SETTINGS + 'G1 X1 E0.1 F18000\n')
        ramp = report['extrusion_moves'][0]['ramp']
        self.assertAlmostEqual(ramp['zero_to_requested_speed_s'], .006)
        self.assertAlmostEqual(ramp['rest_to_rest_distance_at_requested_speed_mm'], 1.8)
        self.assertAlmostEqual(ramp['rest_to_rest_peak_speed_mm_s'], math.sqrt(50000))
        self.assertAlmostEqual(ramp['unsmoothed_linear_pa_extra_filament_speed_mm_s'], 100)
        self.assertEqual(report['moves_nominally_shorter_than_smoothing_count'], 1)

    def test_unknown_defaults_are_not_guessed(self):
        report = self.report(START + 'G1 X10 E1 F600\n')
        self.assertIsNone(report['extrusion_moves'][0]['ramp'])
        self.assertEqual(report['coverage']['with_pa'], 0)

    def test_multipliers_and_zero_pa(self):
        source = START + SETTINGS + 'M220 S50\nM221 S200\nSET_PRESSURE_ADVANCE ADVANCE=0\nG1 X10 E1 F18000\n'
        ramp = self.report(source)['extrusion_moves'][0]['ramp']
        self.assertAlmostEqual(ramp['nominal_filament_speed_mm_s'], 30)
        self.assertEqual(ramp['unsmoothed_linear_pa_extra_filament_speed_mm_s'], 0)

    def test_transition_boundaries(self):
        for boundary in ('G4 P100', 'G1 X15', 'G1 E-1', ';LAYER_CHANGE',
                         'SET_PRESSURE_ADVANCE ADVANCE=0.03', 'EXCLUDE_OBJECT_START NAME=part',
                         'CUSTOM_MACRO'):
            report = self.report(START + SETTINGS + 'G1 X10 E1 F600\n' + boundary + '\nG1 X20 E2\n')
            self.assertEqual(report['adjacent_flow_transition_count'], 0, boundary)

    def test_flow_delta_and_cosmetic_entry(self):
        report = self.report(START + 'G1 X10 E2 F600\n;TYPE:Outer wall\nG1 X20 E1\n')
        event = report['largest_nominal_flow_transitions'][0]
        self.assertAlmostEqual(event['flow_delta_mm3_s'], -math.pi * .875**2)
        self.assertTrue(event['is_cosmetic'])

    def test_arcs_have_no_straight_ramp_estimate(self):
        report = self.report(START + SETTINGS + 'G1 X10 E1 F600\nG3 X0 Y10 I-10 J0 E1\n')
        self.assertIsNone(report['extrusion_moves'][-1]['ramp'])

    def test_summary_is_bounded(self):
        source = START + SETTINGS + ''.join(f'G1 X{i} E{i} F600\n' for i in range(1, 101))
        report = self.report(source, details=False)
        self.assertEqual(report['coverage']['extrusion_moves'], 100)
        self.assertEqual(len(report['largest_nominal_flow_transitions']), 20)
        self.assertEqual(len(report['ramp_samples']), 20)
        self.assertNotIn('extrusion_moves', report)
