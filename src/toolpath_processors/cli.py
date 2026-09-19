import argparse
import json
import os
from pathlib import Path
import stat
import tempfile
from .aesthetics import process

def atomic_write(path, data):
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)

def main(argv=None):
    parser = argparse.ArgumentParser(description='Annotate cosmetic path entries; never change executable G-code.')
    parser.add_argument('input', type=Path, help='G-code file supplied by OrcaSlicer')
    parser.add_argument('--report', type=Path, help='JSON output; default: INPUT.aesthetics.json')
    parser.add_argument('--report-only', action='store_true', help='Leave input byte-for-byte unchanged')
    args = parser.parse_args(argv)
    try:
        path = args.input.resolve(strict=True)
        report = (args.report or Path(str(path) + '.aesthetics.json')).resolve()
        if report == path or (report.exists() and os.path.samefile(report, path)):
            raise ValueError('Report must not overwrite the input')
        original = path.read_bytes()
        if b'\0' in original: raise ValueError('Binary input is unsupported; export plain text G-code')
        result = process(original.decode('utf-8'), annotate=not args.report_only)
        # Write the report first: a report failure must not alter the print file.
        atomic_write(report, (json.dumps(result.report, indent=2, allow_nan=False) + '\n').encode())
        if not args.report_only:
            if path.read_bytes() != original: raise ValueError('Input changed during processing')
            atomic_write(path, result.output.encode('utf-8'))
        print(f'Aesthetics history: {len(result.report["cosmetic_entries"])} entries; report: {report}')
        if not result.report['cosmetic_entries']:
            print('No analyzable cosmetic entries; check feature comments and modal-state barriers.')
    except (OSError, UnicodeError, ValueError) as error:
        parser.exit(1, f'aesthetics-history: {error}\n')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
