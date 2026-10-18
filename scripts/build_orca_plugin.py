#!/usr/bin/env python3
"""Build a dependency-free Orca plugin wheel from the existing analysis core."""
import argparse
import base64
import csv
import hashlib
import io
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NAME = 'orca_quality_analysis'
VERSION = '0.1.0'
CORE = ('__init__', 'optimizer', 'gcode', 'geometry', 'commands', 'contracts', 'dynamics')


def build(destination):
    files = {}
    for path in (ROOT / 'plugins' / NAME).glob('*.py'):
        files[f'{NAME}/{path.name}'] = path.read_bytes()
    for module in CORE:
        files[f'{NAME}/_core/{module}.py'] = (ROOT / 'src/toolpath_processors' / f'{module}.py').read_bytes()
    dist = f'{NAME}-{VERSION}.dist-info'
    files[f'{dist}/METADATA'] = (
        f'Metadata-Version: 2.1\nName: {NAME}\nVersion: {VERSION}\n'
        'Summary: Read-only toolpath quality and extrusion dynamics analysis\n'
        'Requires-Python: >=3.10\n').encode()
    files[f'{dist}/top_level.txt'] = f'{NAME}\n'.encode()
    files[f'{dist}/WHEEL'] = b'Wheel-Version: 1.0\nGenerator: build_orca_plugin\nRoot-Is-Purelib: true\nTag: py3-none-any\n'
    records = io.StringIO(newline='')
    writer = csv.writer(records, lineterminator='\n')
    for name, data in sorted(files.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
        writer.writerow([name, f'sha256={digest}', len(data)])
    writer.writerow([f'{dist}/RECORD', '', ''])
    files[f'{dist}/RECORD'] = records.getvalue().encode()
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f'{NAME}-{VERSION}-py3-none-any.whl'
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2026, 10, 18, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist')
    print(build(parser.parse_args().output_dir))
