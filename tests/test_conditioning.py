import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from toolpath_processors.conditioning import condition
from toolpath_processors.gcode import State

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=(ROOT/'examples/cosmetic_entry_fixture.gcode').read_text()

def moves(text):
    state=State();result=[]
    for i,line in enumerate(text.splitlines(),1):
        move,_=state.consume(line,i)
        if move: result.append(move)
    return result

class ConditioningTests(unittest.TestCase):
    def test_changes_only_interior_tail_and_restores_feed(self):
        result=condition(FIXTURE)
        self.assertEqual(result.report['changed_transitions'],1)
        original=moves(FIXTURE);modified=moves(result.output)
        self.assertEqual(original[-1].end_xyz,modified[-1].end_xyz)
        self.assertAlmostEqual(sum(m.extrusion_mm or 0 for m in original),sum(m.extrusion_mm or 0 for m in modified))
        for feature in ('outer wall',):
            a=[m for m in original if m.feature==feature]
            b=[m for m in modified if m.feature==feature]
            self.assertEqual([(m.end_xyz,m.extrusion_mm,m.requested_speed_mm_s) for m in a],[(m.end_xyz,m.extrusion_mm,m.requested_speed_mm_s) for m in b])
        interior=[m for m in modified if m.feature=='inner wall' and m.extrusion_mm and m.extrusion_mm>0]
        self.assertEqual([m.length_mm for m in interior],[30,10])
        self.assertEqual([m.requested_speed_mm_s for m in interior],[100,50])
        travel=[m for m in modified if m.length_mm==1 and m.extrusion_mm==0]
        self.assertEqual(travel[0].requested_speed_mm_s,100)
    def test_absolute_extrusion(self):
        text=FIXTURE.replace('M83','M82\nG92 E0').replace('G1 X0 E2 F3000','G1 X0 E4 F3000').replace('G1 Y2 E0.05','G1 Y2 E4.05')
        result=condition(text)
        self.assertEqual(result.report['changed_transitions'],1)
        self.assertAlmostEqual(sum(m.extrusion_mm or 0 for m in moves(result.output)),4.05)
    def test_flow_matching_accounts_for_width(self):
        result=condition(FIXTURE.replace('G1 X40 E2','G1 X40 E4'))
        edit=result.report['changes'][0]['edits'][0]
        self.assertEqual(edit['new_feedrate_mm_min'],1500)
    def test_all_or_nothing_bound(self):
        result=condition(FIXTURE,min_speed_ratio=.75)
        self.assertEqual(result.output,FIXTURE)
        self.assertIn('slowdown',result.report['skipped_candidates'][0]['reason'])
    def test_no_speedup(self):
        text=FIXTURE.replace('F3000','F12000')
        self.assertEqual(condition(text).output,text)
    def test_retract_macro_z_unknown_and_relative_skip(self):
        for change in ('G1 E-0.5\n','CUSTOM_MACRO\n','G1 Z0.4\n','M221 S90\n','G91\n','G4 P100\n'):
            text=FIXTURE.replace(';TYPE:Outer wall',change+';TYPE:Outer wall')
            self.assertEqual(condition(text).output,text,change)
    def test_insufficient_distance_and_long_travel(self):
        for kwargs in ({'distance_mm':50},{'max_travel_mm':.5}):
            self.assertEqual(condition(FIXTURE,**kwargs).output,FIXTURE)
    def test_multi_segment_tail(self):
        text=FIXTURE.replace('G1 X40 E2 F6000','G1 X35 E1.75 F6000\nG1 X40 E0.25')
        result=condition(text)
        self.assertEqual(len(result.report['changes'][0]['edits']),2)
        slow=[m for m in moves(result.output) if m.feature=='inner wall' and m.extrusion_mm and m.extrusion_mm>0 and m.requested_speed_mm_s==50]
        self.assertAlmostEqual(sum(m.length_mm for m in slow),10)
    def test_preserve_noninterior_source(self):
        result=condition(FIXTURE)
        before=FIXTURE.split(';TYPE:Outer wall')[1]
        after=result.output.split(';TYPE:Outer wall')[1]
        self.assertEqual(before,after)
    def test_rerun_refused(self):
        with self.assertRaisesRegex(ValueError,'Already'): condition(condition(FIXTURE).output)
    def test_parameters(self):
        for kwargs in ({'distance_mm':0},{'distance_mm':float('nan')},{'max_travel_mm':-1},{'min_speed_ratio':2}):
            with self.assertRaises(ValueError): condition(FIXTURE,**kwargs)
    def test_unstable_or_short_entry_skipped(self):
        text=FIXTURE.replace('G1 X0 E2 F3000', 'G1 X39 E0.05 F3000')
        self.assertEqual(condition(text).output,text)
    def test_varied_split_conserves_path_and_extrusion(self):
        for distance in (0.1,1.23456789,10,39.999999,40):
            result=condition(FIXTURE,distance_mm=distance)
            original=moves(FIXTURE);modified=moves(result.output)
            self.assertAlmostEqual(sum(m.length_mm or 0 for m in original),sum(m.length_mm or 0 for m in modified),places=7)
            self.assertAlmostEqual(sum(m.extrusion_mm or 0 for m in original),sum(m.extrusion_mm or 0 for m in modified),places=9)
    def test_cli_in_place_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.gcode';path.write_text(FIXTURE)
            command=[sys.executable,str(ROOT/'scripts/condition_cosmetic_entry.py'),str(path),'--in-place']
            run=subprocess.run(command,capture_output=True)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertEqual(Path(str(path)+'.control.gcode').read_text(),FIXTURE)
            once=path.read_bytes()
            self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0)
            self.assertEqual(path.read_bytes(),once)
    def test_coupon_watertight(self):
        from collections import Counter
        vertices=[]
        for line in (ROOT/'examples/cosmetic_entry_coupon.stl').read_text().splitlines():
            if line.strip().startswith('vertex '): vertices.append(tuple(map(float,line.split()[1:])))
        edges=Counter()
        for i in range(0,len(vertices),3):
            a,b,c=vertices[i:i+3]
            for edge in ((a,b),(b,c),(c,a)): edges[tuple(sorted(edge))]+=1
        self.assertEqual(len(vertices),36)
        self.assertTrue(all(count==2 for count in edges.values()))
    def test_crlf(self):
        result=condition(FIXTURE.replace('\n','\r\n'))
        self.assertNotIn('\n',result.output.replace('\r\n',''))
    def test_cli_ab_and_original_preservation(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'input.gcode';source.write_text(FIXTURE)
            dest=Path(directory)/'ab'
            command=[sys.executable,str(ROOT/'scripts/condition_cosmetic_entry.py'),str(source),'--ab-dir',str(dest)]
            run=subprocess.run(command,capture_output=True)
            self.assertEqual(run.returncode,0,run.stderr)
            self.assertEqual((dest/'A-control.gcode').read_bytes(),source.read_bytes())
            self.assertNotEqual((dest/'B-conditioned.gcode').read_bytes(),source.read_bytes())
            self.assertEqual(json.loads((dest/'B-conditioned.gcode.conditioning.json').read_text())['changed_transitions'],1)
            self.assertNotEqual(subprocess.run(command,capture_output=True).returncode,0)
    def test_cli_zero_changes_no_fake_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'input.gcode';source.write_text('G90\n')
            dest=Path(directory)/'out.gcode'
            run=subprocess.run([sys.executable,str(ROOT/'scripts/condition_cosmetic_entry.py'),str(source),'--output',str(dest)],capture_output=True)
            self.assertEqual(run.returncode,2)
            self.assertFalse(dest.exists())
if __name__=='__main__': unittest.main()
