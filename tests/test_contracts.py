from dataclasses import asdict, replace
import hashlib
import json
import unittest
import tempfile
from pathlib import Path
from toolpath_processors.optimizer_cli import main
from toolpath_processors.contracts import StartupContract
from toolpath_processors.optimizer import parse_job, analyze_job, QualityProfile, VFAProfile
from toolpath_processors.vfa import optimize_vfa

SOURCE = ('PRINT_START HOTEND_TEMP=275 BED_TEMP=105\nG90\nG21\nM83\n'
          'G1 X0 Y0 Z.3 F6600\n;LAYER_CHANGE\n;LAYER_CHANGE\n;TYPE:Outer wall\nG1 X20 E1\n')


def contract(text=SOURCE):
    return StartupContract(hashlib.sha256(text.encode()).hexdigest(), 1,
                           text.splitlines()[0], 'a'*64, 'test-revision',
                           'Synthetic test: startup resets both overrides.', 1.0, 1.0)


class ContractTests(unittest.TestCase):
    def test_only_audited_fields_recover(self):
        baseline = parse_job(SOURCE)
        job = parse_job(SOURCE, startup_contract=contract())
        self.assertIsNone(baseline.segments[-1].volumetric_flow_mm3_s)
        self.assertIsNotNone(job.segments[-1].volumetric_flow_mm3_s)
        self.assertIsNone(job.segments[0].move.length_mm)
        self.assertIsNone(job.segments[-1].move.commanded_state['hotend_target_c'])
        self.assertEqual(job.emit(), SOURCE)
        self.assertEqual(analyze_job(job)['startup_contract']['config_sha256'], 'a'*64)

    def test_mismatch_and_unknown_fields_rejected(self):
        for text in (SOURCE+';changed\n', SOURCE.replace('275','270')):
            with self.assertRaises(ValueError): parse_job(text, startup_contract=contract())
        with self.assertRaises(ValueError):
            parse_job(SOURCE, startup_contract=replace(contract(), line=2))
        data = asdict(contract()); data['position'] = [0,0,0]
        with self.assertRaises(ValueError): StartupContract.from_json(json.dumps(data))
        with self.assertRaises(ValueError): replace(contract(), speed_factor=True)

    def test_later_macros_invalidate_contract_facts(self):
        text = SOURCE + 'CUSTOM_MACRO\nG90\nM83\nG1 X0 Y0 Z0 F6600\nG1 X20 E1\n'
        job = parse_job(text, startup_contract=contract(text))
        self.assertIsNone(job.segments[-1].volumetric_flow_mm3_s)

    def test_cli_rejects_stale_contract_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            src, proof, output, report = [root/name for name in ('in.gcode', 'contract.json', 'out.gcode', 'report.json')]
            src.write_text(SOURCE + '; changed\n')
            proof.write_text(json.dumps(asdict(contract())))
            with self.assertRaises(SystemExit):
                main([str(src), '--startup-contract', str(proof), '--output', str(output), '--report', str(report)])
            self.assertFalse(output.exists())
            self.assertFalse(report.exists())

    def test_vfa_replay_uses_same_explicit_contract(self):
        p = QualityProfile(max_velocity_mm_s=300,max_flow_mm3_s=40,
                           vfa=VFAProfile(x=((105,125),)))
        job = parse_job(SOURCE, p, startup_contract=contract())
        result = optimize_vfa(job, p)
        self.assertEqual(result.report['changed_segments'], 1)
        self.assertTrue(result.report['validation']['replayed'])


if __name__ == '__main__': unittest.main()
