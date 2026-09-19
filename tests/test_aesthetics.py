from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from toolpath_processors.aesthetics import process, PREFIX
from toolpath_processors.gcode import State
ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (ROOT / 'examples/aesthetics_history.gcode').read_text()

class AnalysisTests(unittest.TestCase):
    def test_history(self):
        events = process(FIXTURE).report['cosmetic_entries']
        self.assertEqual(len(events), 2)
        first = events[0]
        self.assertEqual(first['preceding_deposition']['feature'], 'internal infill')
        self.assertEqual(first['travel_since_deposition_mm'], 10)
        self.assertEqual(first['retraction_since_deposition_mm'], 0.5)
        self.assertEqual(first['entry']['requested_speed_mm_s'], 50)
    def test_idempotent_and_lossless(self):
        for text in (FIXTURE, FIXTURE.replace('\n', '\r\n'), FIXTURE.rstrip('\n')):
            once = process(text)
            twice = process(once.output)
            self.assertEqual(once, twice)
            self.assertEqual(''.join(s for s in once.output.splitlines(keepends=True) if not s.startswith(PREFIX)), text)
    def test_macro_barrier(self):
        text = FIXTURE.replace(';TYPE:Top surface', 'CUSTOM_MACRO\nG90\nM83\nG1 X0 Y10 Z0.2 F3000\n;TYPE:Top surface')
        events = process(text).report['cosmetic_entries']
        self.assertTrue(events)
        self.assertFalse(events[0]['history_known'])
        self.assertTrue(process(text).report['state_barrier_lines'])
    def test_absolute_extrusion_reset(self):
        state = State()
        moves = []
        for n, line in enumerate(['G90', 'M82', 'G92 E0', 'G1 X0 Y0 Z0 F600', 'G1 X10 E1', 'G92 E0', 'G1 X20 E1']):
            move, _ = state.consume(line, n)
            if move: moves.append(move)
        self.assertEqual(moves[-1].extrusion_mm, 1)
        self.assertEqual(moves[-1].length_mm, 10)
    def test_relative_xyz(self):
        state = State()
        state.consume('G91', 1)
        state.consume('M83', 2)
        move, _ = state.consume('G1X3Y4E1F600', 3)
        self.assertEqual(move.length_mm, 5)
        self.assertEqual(move.nominal_seconds, 0.5)
    def test_other_feature_format(self):
        self.assertEqual(len(process(FIXTURE.replace(';TYPE:', '; FEATURE: ')).report['cosmetic_entries']), 2)
    def test_unknown_and_inches(self):
        for command in ('G2 X5 Y5 I1 J1', 'T1', 'G20', 'G1 Xnan', 'G1 X1 X2', 'G1 X' + '9' * 400):
            state = State()
            _, barrier = state.consume(command, 1)
            self.assertTrue(barrier, command)
    def test_report_only(self):
        self.assertEqual(process(FIXTURE, annotate=False).output, FIXTURE)

class CliTests(unittest.TestCase):
    def invoke(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/aesthetics_history.py'), *map(str, args)], capture_output=True, text=True)
    def test_cli_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sample with spaces.gcode'
            path.write_bytes(FIXTURE.replace('\n', '\r\n').encode())
            original = path.read_bytes()
            self.assertEqual(self.invoke('--report-only', path).returncode, 0)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(self.invoke(path).returncode, 0)
            first = path.read_bytes()
            self.assertEqual(self.invoke(path).returncode, 0)
            self.assertEqual(path.read_bytes(), first)
            self.assertTrue(Path(str(path) + '.aesthetics.json').exists())
    def test_failed_report_does_not_modify_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.gcode'
            path.write_text(FIXTURE)
            for report in (path, Path(directory) / 'missing' / 'report.json'):
                self.assertNotEqual(self.invoke(path, '--report', report).returncode, 0)
                self.assertEqual(path.read_text(), FIXTURE)
    def test_binary_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'binary.gcode'
            path.write_bytes(b'G1\0X0')
            self.assertNotEqual(self.invoke(path).returncode, 0)
            self.assertEqual(path.read_bytes(), b'G1\0X0')

if __name__ == '__main__': unittest.main()
