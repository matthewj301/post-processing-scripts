import json
import math
from pathlib import Path
import tempfile
import unittest
from toolpath_processors.optimizer import QualityProfile, analyze_job, parse_job
from toolpath_processors.optimizer_cli import main

START = 'G90\nM83\nG92 X0 Y0 Z0 E0\n'


class OptimizerTests(unittest.TestCase):
    def test_lossless_corpus(self):
        for path in Path('examples').glob('*.gcode'):
            source = path.read_bytes().decode()
            self.assertEqual(parse_job(source).emit().encode(), path.read_bytes())
        text = START.replace('\n', '\r\n') + '; Unicode café\r\nCUSTOM_MACRO FOO=1'
        self.assertEqual(parse_job(text).emit(), text)

    def test_flow_and_metadata(self):
        job = parse_job(START + ';WIDTH:0.4\n;HEIGHT:0.2\n;TYPE:Outer wall\nG1 X10 E1 F600\nG1 X20 E2\n')
        a, b = job.segments
        self.assertEqual(a.width_mm, .4)
        self.assertEqual(a.height_mm, .2)
        self.assertTrue(a.is_cosmetic)
        self.assertEqual(a.direction_xyz, (1, 0, 0))
        self.assertAlmostEqual(a.volumetric_flow_mm3_s, math.pi * .875**2)
        self.assertAlmostEqual(b.flow_delta_mm3_s, a.volumetric_flow_mm3_s)

    def test_modes_reset_and_retract(self):
        job = parse_job(START + 'M82\nG1 X10 E2 F600\nG92 E0\nG1 X20 E1\nG91\nM83\nG1 X5 E-0.5\nG1 X5 E1\n')
        self.assertEqual([s.move.extrusion_mm for s in job.segments], [2, 1, -.5, 1])
        self.assertEqual(job.segments[-1].move.end_xyz, (30, 0, 0))
        self.assertIsNone(job.segments[-1].flow_delta_mm3_s)

    def test_barriers_and_arcs(self):
        job = parse_job(START + 'G1 X10 E1 F600\nG3 X0 Y10 I-10 J0 E1\nCUSTOM_MACRO\nG1 X20 E1\n')
        self.assertAlmostEqual(job.segments[1].move.length_mm, math.pi*5)
        self.assertIsNone(job.segments[1].direction_xyz)
        self.assertEqual(analyze_job(job)['validation']['status'], 'incomplete')
        self.assertIsNone(job.segments[-1].flow_delta_mm3_s)

    def test_limits_and_profiles(self):
        profile = QualityProfile(max_velocity_mm_s=5, max_flow_mm3_s=1)
        report = analyze_job(parse_job(START + 'G1 X10 E1 F600\n', profile), profile)
        self.assertEqual(len(report['validation']['violations']), 2)
        for text in ('{"bad":1}', '{"max_flow_mm3_s":NaN}', '{"filament_diameter_mm":null}',
                     '{"max_velocity_mm_s":true}', '[]'):
            with self.assertRaises(ValueError): QualityProfile.from_json(text)

    def test_bookkeeping_preserves_modes_geometry_and_flow(self):
        bookkeeping = ('EXCLUDE_OBJECT_DEFINE NAME=part CENTER=5,5 POLYGON=[[0, 0], [10,0], [10,10]]\n'
                       'EXCLUDE_OBJECT_START NAME=part\n'
                       'SET_PRINT_STATS_INFO TOTAL_LAYER=2 CURRENT_LAYER=1\n'
                       'M73 P1 R72\n')
        text = START + 'G1 X10 E1 F600\n' + bookkeeping + 'G1 X20 E1\nM73 P2 R71\nG1 X30 E2\n'
        job = parse_job(text)
        report = analyze_job(job)
        self.assertEqual(report['warning_count'], 0)
        self.assertEqual(report['coverage']['known_motion_moves'], 3)
        self.assertEqual(job.segments[1].move.length_mm, 10)
        self.assertIsNone(job.segments[1].flow_delta_mm3_s)  # object boundary
        self.assertAlmostEqual(job.segments[2].flow_delta_mm3_s, math.pi*.875**2)
        self.assertEqual(job.emit(), text)

    def test_invalid_bookkeeping_and_device_commands_fail_closed(self):
        for command in ('EXCLUDE_OBJECT_START', 'EXCLUDE_OBJECT_START NAME=x NAME=y',
                        'EXCLUDE_OBJECT_DEFINE NAME=x CENTER=nan,0',
                        'EXCLUDE_OBJECT_DEFINE NAME=x POLYGON=[[0,0],[1,0],[NaN,1]]',
                        'EXCLUDE_OBJECT_DEFINE NAME=x POLYGON=null',
                        'SET_PRINT_STATS_INFO CURRENT_LAYER=-1', 'M73 P101',
                        'M106 P1.5 S128', 'M107 P-1', 'M104 T-1 S210',
                        'M104 T3 S210 A0', 'EXCLUDE_OBJECT NAME=x'):
            with self.subTest(command=command):
                job = parse_job(START + 'G1 X10 E1 F600\n' + command + '\nG1 X20 E1\n')
                self.assertEqual(len(job.warnings), 1)
                self.assertIsNone(job.segments[-1].volumetric_flow_mm3_s)

    def test_indexed_devices_preserve_motion_without_claiming_active_device(self):
        job = parse_job(START + 'M104 S210\nM106 S255\nG1 X10 E1 F600\n'
                        'M109 T3 S255\nM106 P2 S128\nG1 X20 E1\nM107 P2\nG1 X30 E1\n')
        move = job.segments[1].move
        self.assertEqual(move.length_mm, 10)
        self.assertIsNone(move.commanded_state['hotend_target_c'])
        self.assertIsNone(move.commanded_state['fan_speed'])
        self.assertEqual(move.commanded_state['hotend_target_t3_c'], 255)
        self.assertAlmostEqual(move.commanded_state['fan_p2_speed'], 128/255)
        self.assertEqual(job.segments[-1].move.commanded_state['fan_p2_speed'], 0)
        self.assertEqual(job.warnings, ())

    def test_vendor_fixture_has_conditional_estimates_only(self):
        text = (Path(__file__).resolve().parents[1] / 'examples/optimizer_vendor_fixture.gcode').read_text()
        job = parse_job(text)
        report = analyze_job(job)
        self.assertEqual(report['coverage']['known_flow_moves'], 0)
        self.assertEqual(report['slicer_intent']['known_flow_moves'], 4)
        self.assertFalse(report['slicer_intent']['usable_for_optimization'])
        self.assertEqual(report['validation']['status'], 'incomplete')
        self.assertEqual({w['command'] for w in job.warnings},
                         {'PRINT_START', 'T3', 'TIMELAPSE_TAKE_FRAME', 'DEFECT_DETECTION_DETECT', 'PRINT_END'})
        self.assertEqual(job.emit(), text)

    def test_intent_drops_macro_position_and_waits_for_coordinate_recovery(self):
        job = parse_job(START + 'G1 X10 E1 F600\nCUSTOM_MACRO\nG1 X20 E1 F600\n'
                        'G1 Y0 Z0\nG1 X30 E1\n')
        intent = job.slicer_intent_segments
        self.assertIsNone(intent[1].length_mm)
        self.assertIsNone(intent[2].length_mm)
        self.assertEqual(intent[3].length_mm, 10)
        self.assertIsNone(job.segments[-1].volumetric_flow_mm3_s)

    def test_intent_does_not_guess_extrusion_mode_or_ignore_bad_motion(self):
        for middle in ('G1 Xnan', 'G20'):
            job = parse_job(START + 'G1 X10 E1 F600\n' + middle + '\nG1 X20 E1 F600\n')
            self.assertEqual(analyze_job(job)['slicer_intent']['known_flow_moves'], 1)
        job = parse_job('G90\nG92 X0 Y0 Z0 E0\nCUSTOM_MACRO\nG1 X0 Y0 Z0 F600\nG1 X10 E1\n')
        self.assertEqual(analyze_job(job)['slicer_intent']['known_flow_moves'], 0)

    def test_intent_retains_arc_diagnostics_when_verified_geometry_unknown(self):
        job = parse_job(START + 'CUSTOM_MACRO\nG1 X10 Y0 Z0 F600\nG3 X0 Y10 I-10 J0 E1\n')
        self.assertEqual(len(job.segments), 1)
        self.assertEqual(len(job.slicer_intent_segments), 2)
        self.assertAlmostEqual(job.slicer_intent_segments[-1].length_mm, math.pi*5)

    def test_report_stays_compact_and_details_preserve_all_records(self):
        job = parse_job(START + ('CUSTOM_MACRO\nG1 X0 Y0 Z0 F600\nG1 X10 E1\n' * 100))
        compact, detailed = analyze_job(job), analyze_job(job, details=True)
        self.assertNotIn('segments', compact)
        self.assertEqual(compact['warning_count'], 100)
        self.assertEqual(len(compact['warning_groups'][0]['sample_lines']), 20)
        self.assertEqual(len(compact['validation']['unknown_motion_lines']), 20)
        self.assertEqual(len(detailed['warnings']), 100)
        self.assertEqual(len(detailed['segments']), 200)
        self.assertEqual(compact['coverage'], detailed['coverage'])
        self.assertLess(len(json.dumps(compact)), 6000)

    def test_missing_overrides_are_not_reported_as_verified_motion(self):
        job = parse_job('CUSTOM_MACRO\n' + START + 'G1 X10 E1 F600\n')
        self.assertEqual(analyze_job(job)['coverage']['known_motion_moves'], 0)
        self.assertIsNone(job.segments[-1].volumetric_flow_mm3_s)
        self.assertIsNotNone(job.slicer_intent_segments[-1].volumetric_flow_mm3_s)
        recovered = parse_job('CUSTOM_MACRO\n' + START + 'M220 S100\nM221 S100\nG1 X10 E1 F600\n')
        self.assertEqual(analyze_job(recovered)['coverage']['known_motion_moves'], 1)

    def test_absolute_intent_requires_e_baseline_after_macro(self):
        job = parse_job(START + 'M82\nG1 X10 E1 F600\nCUSTOM_MACRO\n'
                        'G1 X0 Y0 Z0 F600\nG1 X10 E2\nG1 X20 E3\n')
        self.assertIsNone(job.slicer_intent_segments[-2].extrusion_mm)
        self.assertEqual(job.slicer_intent_segments[-1].extrusion_mm, 1)
        self.assertIsNone(job.segments[-1].move.extrusion_mm)

    def test_cli_details_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            source, report = Path(directory)/'input.gcode', Path(directory)/'details.json'
            source.write_text(START + 'G1 X10 E1 F600\n')
            self.assertEqual(main([str(source), '--report', str(report), '--details']), 0)
            data = json.loads(report.read_text())
            self.assertEqual(data['detail_level'], 'full')
            self.assertEqual(len(data['segments']), 1)
            self.assertEqual(len(data['slicer_intent']['segments']), 1)

    def test_cli_preserves_files(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output, report = [Path(directory)/name for name in ('in.gcode', 'out.gcode', 'report.json')]
            original = (START + 'G1 X10 E1 F600\n').replace('\n', '\r\n').encode()
            source.write_bytes(original)
            args = [str(source), '--output', str(output), '--report', str(report)]
            self.assertEqual(main(args), 0)
            self.assertEqual(output.read_bytes(), original)
            self.assertEqual(json.loads(report.read_text())['modifications'], [])
            with self.assertRaises(SystemExit): main(args)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(output.read_bytes(), original)


if __name__ == '__main__': unittest.main()
