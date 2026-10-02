import json
import math
from pathlib import Path
import random
import tempfile
import unittest
from toolpath_processors.optimizer import QualityProfile, VFAProfile, parse_job
from toolpath_processors.vfa import MARKER, choose_speed, in_band, optimize_vfa, validate_edits
from toolpath_processors.optimizer_cli import main

HEADER = ('G90\nM83\nG92 X0 Y0 Z0.2 E0\n;LAYER_CHANGE\n;LAYER_CHANGE\n'
          ';TYPE:Outer wall\n')


def profile(**kwargs):
    return QualityProfile(max_velocity_mm_s=300, max_flow_mm3_s=40,
                          vfa=VFAProfile(x=((105, 125),), **kwargs))


class VFATests(unittest.TestCase):
    def test_slowdown_preserves_e_coordinates_comments_and_restores_feed(self):
        source = HEADER + 'G1 X20 E1 F6600 ; wall\nG1 Y20 E1\n'
        result = optimize_vfa(parse_job(source), profile())
        self.assertEqual(result.report['changed_segments'], 1)
        self.assertIn('G1 X20 E1 F6240.000000000 ; wall\n', result.output)
        self.assertIn('G1 F6600 ; VFA restore original feedrate\nG1 Y20 E1\n', result.output)
        self.assertTrue(result.report['validation']['replayed'])
        self.assertGreater(result.report['nominal_added_seconds'], 0)
        with self.assertRaises(ValueError): optimize_vfa(parse_job(result.output), profile())

    def test_absolute_e_g92_modal_f_and_line_endings(self):
        source = (HEADER.replace('M83', 'M82') + 'G1 F6600\nG1 X20 E1\nG92 E0\nG1 X40 E1 ;last').replace('\n', '\r\n')
        result = optimize_vfa(parse_job(source), profile())
        self.assertEqual(result.report['changed_segments'], 2)
        self.assertIn('G92 E0\r\n', result.output)
        self.assertIn('E1  F6240.000000000 ;last', result.output)
        self.assertNotIn('\n', result.output.replace('\r\n', ''))

    def test_direction_projection_and_both_axes(self):
        config = VFAProfile(x=((70, 90),), y=((68, 72),), max_slowdown_fraction=.3)
        direction = (math.sqrt(.5), math.sqrt(.5), 0)
        chosen = choose_speed(110, direction, config)
        self.assertLess(chosen, 110)
        self.assertFalse(in_band(chosen, direction, config))
        self.assertEqual(choose_speed(110, (0, 1, 0), VFAProfile(x=((105,125),))), 110)
        self.assertEqual(choose_speed(110, (-1, 0, 0), profile().vfa), 104)

    def test_hysteresis_and_slowdown_bound(self):
        config = profile().vfa
        self.assertEqual(choose_speed(125.5, (1,0,0), config), 125.5)
        self.assertEqual(choose_speed(110, (1,0,0), config, previous=103), 103)
        self.assertIsNone(choose_speed(120, (1,0,0), VFAProfile(x=((50,125),))))
        held = choose_speed(104.5, (1,0,0), config, previous=104)
        self.assertEqual(held, 104)

    def test_unknown_state_and_macro_boundaries_never_optimized(self):
        source = HEADER + 'G1 X20 E1 F6600\nCUSTOM_MACRO\n;TYPE:Outer wall\nG1 X40 E1 F6600\nG1 X60 E1\n'
        result = optimize_vfa(parse_job(source), profile())
        self.assertEqual(result.report['changed_segments'], 1)
        self.assertIn('CUSTOM_MACRO\n;TYPE:Outer wall\nG1 X40 E1 F6600\nG1 X60 E1\n', result.output)
        self.assertEqual(result.report['skipped']['unknown state, unsupported motion, or non-deposition'], 2)

    def test_ineligible_regions_are_byte_identical(self):
        variants = [HEADER.replace('Outer wall','Top surface'), HEADER.replace('Outer wall','Bridge'),
                    HEADER.replace(';LAYER_CHANGE\n', '', 1), HEADER + 'G91\n',
                    HEADER + 'CUSTOM_MACRO\n;TYPE:Outer wall\n']
        for prefix in variants:
            source = prefix + 'G1 X20 E1 F6600\n'
            self.assertEqual(optimize_vfa(parse_job(source), profile()).output, source)
        for motion in ('G1 X1 E.1 F6600\n', 'G1 X20 Z1 E1 F6600\n',
                       'G1 X20 E-1 F6600\n', 'G1 X20 F6600\n',
                       'G2 X20 I10 E1 F6600\n', 'G1 X20 E10 F6600\n'):
            source = HEADER + motion
            self.assertEqual(optimize_vfa(parse_job(source), profile()).output, source)

    def test_overrides_and_firmware_limit(self):
        source = HEADER + 'M220 S50\nM221 S90\nG1 X20 E1 F13200\n'
        result = optimize_vfa(parse_job(source), profile())
        self.assertEqual(result.report['changed_segments'], 1)
        self.assertIn('F12480.000000000', result.output)
        self.assertIn('G1 F13200 ; VFA restore', result.output)
        limited = HEADER + 'SET_VELOCITY_LIMIT VELOCITY=100\nG1 X20 E1 F6600\n'
        self.assertEqual(optimize_vfa(parse_job(limited), profile()).output, limited)

    def test_profile_validation_and_explicit_activation(self):
        for value in ({'x': [[125,105]]}, {'x': [[True,125]]}, {'x': None},
                      {'max_slowdown_fraction': 1}, {'clearance_mm_s': 0},
                      {'transition_weight': -1}, {'surprise': 1}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                QualityProfile.from_json(json.dumps({'vfa': value}))
        for p in (QualityProfile(), QualityProfile(vfa=VFAProfile()),
                  QualityProfile(vfa=VFAProfile(x=((105,125),)))):
            with self.assertRaises(ValueError): optimize_vfa(parse_job(HEADER), p)

    def test_validation_catches_extrusion_or_modal_leaks(self):
        source = HEADER + 'G1 X20 E1 F6600\nG1 Y20 E1\n'
        lines = source.splitlines(keepends=True)
        line = len(lines)-1
        for block in ('G1 X20 E2 F6240\nG1 F6600\n', 'G1 X20 E1 F6240\nG1 F6200\n'):
            with self.assertRaises(ValueError): validate_edits(lines, {line:block}, {line:6240})

    def test_random_directions_obey_all_bands_and_bounds(self):
        rng = random.Random(7)
        config = VFAProfile(x=((60,80),(105,125)), y=((70,90),))
        for _ in range(500):
            angle, original = rng.uniform(-math.pi,math.pi), rng.uniform(40,180)
            direction = (math.cos(angle), math.sin(angle), 0)
            chosen = choose_speed(original, direction, config)
            if chosen is not None:
                self.assertLessEqual(chosen, original)
                self.assertGreaterEqual(chosen, original*(1-config.max_slowdown_fraction))
                self.assertFalse(in_band(chosen, direction, config))

    def test_profile_diameter_cannot_silently_change_ir_flow_basis(self):
        p = QualityProfile(filament_diameter_mm=2.85, max_velocity_mm_s=300,
                           max_flow_mm3_s=40, vfa=VFAProfile(x=((105,125),)))
        with self.assertRaises(ValueError): optimize_vfa(parse_job(HEADER), p)

    def test_fractional_feed_restoration_is_exact(self):
        source = HEADER + 'G1 X20 E1 F6600.123456789\n;TYPE:Sparse infill\nG1 Y20 E1\n'
        result = optimize_vfa(parse_job(source), profile())
        self.assertEqual(result.report['changed_segments'], 1)
        self.assertIn('G1 F6600.123456789 ; VFA restore', result.output)

    def test_realistic_vendor_fixture_cannot_be_optimized_from_intent(self):
        fixture = Path(__file__).resolve().parents[1] / 'examples/optimizer_vendor_fixture.gcode'
        original = fixture.read_text()
        p = QualityProfile(max_velocity_mm_s=300, max_flow_mm3_s=40,
                           vfa=VFAProfile(x=((45,55),)))
        result = optimize_vfa(parse_job(original, p), p)
        self.assertEqual(result.output, original)
        self.assertEqual(result.report['changed_segments'], 0)

    def test_cli_default_noop_opt_in_and_output_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, config = root/'input.gcode', root/'profile.json'
            source.write_text(HEADER + 'G1 X20 E1 F6600\n')
            original = source.read_bytes()
            config.write_text(json.dumps({'max_velocity_mm_s':300,'max_flow_mm3_s':40,'vfa':{'x':[[105,125]]}}))
            common = [str(source), '--profile', str(config)]
            self.assertEqual(main(common + ['--report',str(root/'noop.json'),'--output',str(root/'noop.gcode')]), 0)
            self.assertEqual((root/'noop.gcode').read_bytes(), original)
            self.assertEqual(main(common + ['--apply-vfa','--report',str(root/'vfa.json'),'--output',str(root/'vfa.gcode')]), 0)
            self.assertIn(MARKER, (root/'vfa.gcode').read_text())
            report = json.loads((root/'vfa.json').read_text())
            self.assertFalse(report['validation']['source_preserved'])
            self.assertTrue(report['vfa']['validation']['extrusion_unchanged'])
            with self.assertRaises(SystemExit): main(common + ['--apply-vfa'])
            with self.assertRaises(SystemExit): main(common + ['--apply-vfa','--output',str(source)])
            self.assertEqual(source.read_bytes(), original)


if __name__ == '__main__': unittest.main()
