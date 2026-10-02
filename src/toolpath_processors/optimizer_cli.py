"""Analysis and exact no-op output for the quality optimizer."""
import argparse
import json
from pathlib import Path
from .optimizer import QualityProfile, analyze_job, parse_job
from .vfa import optimize_vfa
from .contracts import StartupContract


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--startup-contract', type=Path, help='Audited startup multipliers bound to this exact input')
    parser.add_argument('--profile', type=Path, help='JSON machine/material limits')
    parser.add_argument('--report', type=Path, help='New report file; defaults to stdout')
    parser.add_argument('--apply-vfa', action='store_true', help='Apply experimental VFA slowdown; requires profile and separate output')
    parser.add_argument('--details', action='store_true', help='Include all segments and diagnostic lines (large files)')
    parser.add_argument('--output', type=Path, help='New G-code output; byte-identical unless --apply-vfa is set')
    args = parser.parse_args(argv)
    try:
        if args.apply_vfa and (args.profile is None or args.output is None):
            raise ValueError('--apply-vfa requires --profile and --output')
        original = args.input.read_bytes()
        profile = QualityProfile.from_json(args.profile.read_text()) if args.profile else QualityProfile()
        contract = StartupContract.from_json(args.startup_contract.read_text()) if args.startup_contract else None
        job = parse_job(original.decode('utf-8'), profile, startup_contract=contract)
        report = analyze_job(job, profile, details=args.details)
        output = job.emit()
        if args.apply_vfa:
            result = optimize_vfa(job, profile)
            output = result.output
            report['mode'] = 'vfa-experiment'
            report['vfa'] = result.report
            report['modifications'] = ([dict(pass_name='vfa-avoidance', changed_segments=result.report['changed_segments'])]
                                       if result.report['changed_segments'] else [])
            report['validation']['source_preserved'] = output == job.source
            # Compact reports retain exact counts and only sample per-edit details.
            if not args.details:
                report['vfa']['edits'] = report['vfa']['edits'][:20]
            report['validation']['scope'] = 'Coverage/limits describe input; source_preserved compares final output; edits checked under vfa.validation'
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
            with args.output.open('xb') as stream: stream.write(output.encode('utf-8'))
        return 2 if report['validation']['violations'] else 0
    except (ValueError, OSError, UnicodeError) as error:
        parser.exit(1, f'quality-optimizer: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
