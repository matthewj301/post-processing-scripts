"""Analysis and exact no-op output for the quality optimizer."""
import argparse
import json
from pathlib import Path
from .optimizer import QualityProfile, analyze_job, parse_job


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--profile', type=Path, help='JSON machine/material limits')
    parser.add_argument('--report', type=Path, help='New report file; defaults to stdout')
    parser.add_argument('--details', action='store_true', help='Include all segments and diagnostic lines (large files)')
    parser.add_argument('--output', type=Path, help='Optional new, byte-identical G-code copy')
    args = parser.parse_args(argv)
    try:
        original = args.input.read_bytes()
        profile = QualityProfile.from_json(args.profile.read_text()) if args.profile else QualityProfile()
        job = parse_job(original.decode('utf-8'), profile)
        report = analyze_job(job, profile, details=args.details)
        serialized = (json.dumps(report, indent=2, allow_nan=False) + '\n').encode()
        destinations = [p.resolve() for p in (args.report, args.output) if p is not None]
        if len(set(destinations)) != len(destinations) or any(p.exists() for p in destinations):
            raise ValueError('Output paths must be distinct new files; existing files are never overwritten')
        # Exclusive creation also protects input and existing files against races.
        if args.report:
            with args.report.open('xb') as stream: stream.write(serialized)
        else:
            print(serialized.decode(), end='')
        if args.output:
            with args.output.open('xb') as stream: stream.write(job.emit().encode('utf-8'))
        return 2 if report['validation']['violations'] else 0
    except (ValueError, OSError, UnicodeError) as error:
        parser.exit(1, f'quality-optimizer: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
