"""Exercise the shipped wheel against the documented Orca API contract."""
import importlib
import importlib.util
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import patch
import zipfile
import hashlib
import base64
import csv
import io

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_orca_plugin', ROOT / 'scripts/build_orca_plugin.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class OrcaPluginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.wheel = builder.build(cls.temp.name)
        cls.old_orca = sys.modules.get('orca')
        api = ModuleType('orca')
        api.base = object
        api.plugin = lambda cls: cls
        api.slicing = SimpleNamespace(SlicingPipelineCapabilityBase=object,
                                      Step=SimpleNamespace(psGCodePostProcess=42))
        api.script = SimpleNamespace(ScriptPluginCapabilityBase=object)
        api.PluginResult = SimpleNamespace(RecoverableError='error')
        api.ExecutionResult = SimpleNamespace(success=lambda message='': ('ok', message),
                                              failure=lambda status, message: (status, message))
        api.register_capability = lambda cls: None
        api.host = SimpleNamespace(ui=SimpleNamespace(message=lambda *a, **kw: None))
        sys.modules['orca'] = api
        sys.path.insert(0, str(cls.wheel))
        cls.package = importlib.import_module('orca_quality_analysis')
        cls.adapter = importlib.import_module('orca_quality_analysis.adapter')
        cls.api = api

    @classmethod
    def tearDownClass(cls):
        sys.path.remove(str(cls.wheel))
        for key in list(sys.modules):
            if key.startswith('orca_quality_analysis'):
                del sys.modules[key]
        if cls.old_orca is None:
            del sys.modules['orca']
        else:
            sys.modules['orca'] = cls.old_orca
        cls.temp.cleanup()

    def execute(self, data, diameter=(1.75,)):
        path = Path(self.temp.name) / 'input.gcode'
        path.write_bytes(data)
        ctx = SimpleNamespace(step=42, gcode_path=str(path), output_name='test',
                              config_value=lambda key: diameter)
        with patch.object(self.api.host.ui, 'message', side_effect=AssertionError('UI on worker')):
            result = self.adapter.AnalysisPipeline().execute(ctx)
        self.assertEqual(path.read_bytes(), data)
        return result

    def test_registered_capabilities(self):
        with patch.object(self.api, 'register_capability') as register:
            self.package.QualityAnalysis().register_capabilities()
        self.assertEqual(register.call_count, 2)

    def test_noop_corpus_and_repeated_exports(self):
        for path in (ROOT / 'examples').glob('*.gcode'):
            for _ in range(2):
                self.assertEqual(self.execute(path.read_bytes())[0], 'ok', path)
        self.assertEqual(self.execute(b'G90\r\nM83\r\nG92 X0 Y0 Z0 E0\r\nG1 X10 E1 F600')[0], 'ok')

    def test_errors_clear_stale_result(self):
        self.execute(b'G90\n')
        for source in (b'\xff', b'\0binary'):
            self.assertEqual(self.execute(source)[0], 'error')
            self.assertIn('failed', self.adapter._latest)

    def test_diameter_guard(self):
        for diameter in ([2.85], [1.75, 2.85], [], ['bad']):
            self.assertEqual(self.execute(b'G90\n', diameter)[0], 'error')
        self.assertEqual(self.execute(b'G90\n', None)[0], 'ok')
        self.assertIn('1.75 mm assumption', self.adapter._latest)

    def test_geometry_hook_does_not_read_gcode(self):
        ctx = SimpleNamespace(step=0)
        self.assertEqual(self.adapter.AnalysisPipeline().execute(ctx)[0], 'ok')

    def test_report_action_and_unknown_state(self):
        self.execute(b'CUSTOM_MACRO\nG1 X10 E1 F600\n')
        with patch.object(self.api.host.ui, 'message') as show:
            self.adapter.ShowAnalysis().execute()
        self.assertIn('CUSTOM_MACRO', show.call_args.args[0])
        self.assertIn('Known nominal flow: 0', show.call_args.args[0])

    def test_external_change_discards_result(self):
        path = Path(self.temp.name) / 'changed.gcode'
        ctx = SimpleNamespace(step=42, gcode_path=str(path), output_name='changed', config_value=lambda key: None)
        with patch.object(Path, 'read_bytes', side_effect=[b'G90\n', b'G91\n']):
            result = self.adapter.AnalysisPipeline().execute(ctx)
        self.assertEqual(result[0], 'error')
        self.assertIn('discarded', self.adapter._latest)

    def test_wheel_integrity_and_determinism(self):
        before = self.wheel.read_bytes()
        self.assertEqual(builder.build(self.temp.name).read_bytes(), before)
        with zipfile.ZipFile(self.wheel) as archive:
            record = next(n for n in archive.namelist() if n.endswith('/RECORD'))
            for name, digest, size in csv.reader(io.StringIO(archive.read(record).decode())):
                if name == record:
                    continue
                data = archive.read(name)
                self.assertEqual(len(data), int(size))
                actual = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
                self.assertEqual(digest, 'sha256=' + actual)
            for module in builder.CORE:
                self.assertEqual(archive.read(f'orca_quality_analysis/_core/{module}.py'),
                                 (ROOT / 'src/toolpath_processors' / f'{module}.py').read_bytes())
