"""Create an explicit experimental output or an unchanged/conditioned A/B pair."""
import argparse
import json
from pathlib import Path
from .cli import atomic_write
from .conditioning import condition

def main(argv=None):
    parser=argparse.ArgumentParser(description='Experimental flow conditioning on interior paths before cosmetic entries.')
    parser.add_argument('input',type=Path)
    destination=parser.add_mutually_exclusive_group(required=True)
    destination.add_argument('--output',type=Path,help='Write a separate conditioned file')
    destination.add_argument('--ab-dir',type=Path,help='Create a new directory with unchanged A and conditioned B')
    destination.add_argument('--in-place',action='store_true',help='Orca integration; saves .control.gcode backup first')
    parser.add_argument('--distance-mm',type=float,default=10)
    parser.add_argument('--max-travel-mm',type=float,default=2)
    parser.add_argument('--min-speed-ratio',type=float,default=.25)
    args=parser.parse_args(argv)
    try:
        source=args.input.resolve(strict=True)
        original=source.read_bytes()
        result=condition(original.decode('utf-8'),distance_mm=args.distance_mm,
                         max_travel_mm=args.max_travel_mm,min_speed_ratio=args.min_speed_ratio)
        if not result.report['changed_transitions']:
            print(json.dumps(result.report,indent=2))
            parser.exit(2,'No eligible transitions changed. No print file was written.\n')
        backup=None
        if args.ab_dir:
            directory=args.ab_dir.resolve()
            if directory.exists(): raise ValueError('A/B directory already exists; choose a new directory')
            output=directory/'B-conditioned.gcode'
            backup=directory/'A-control.gcode'
        elif args.in_place:
            output=source
            backup=source.with_name(source.name+'.control.gcode')
        else:
            output=args.output.resolve()
            if output == source or (output.exists() and output.samefile(source)):
                raise ValueError('Use --in-place explicitly to replace input')
        report=output.with_name(output.name+'.conditioning.json')
        for path in (output,backup,report):
            if path is not None and path != source and path.exists():
                raise ValueError(f'Refusing to overwrite existing file: {path}')
        if args.ab_dir: directory.mkdir(parents=True,exist_ok=False)
        if backup: atomic_write(backup,original)
        atomic_write(report,(json.dumps(result.report,indent=2,allow_nan=False)+'\n').encode())
        if source.read_bytes()!=original: raise ValueError('Input changed during processing')
        atomic_write(output,result.output.encode())
        print(f'Conditioned {result.report["changed_transitions"]} transitions: {output}')
        if backup: print(f'Unchanged control: {backup}')
        print(f'Edit report: {report}')
        return 0
    except (ValueError,OSError,UnicodeError) as error:
        parser.exit(1,f'cosmetic-entry-conditioning: {error}\n')

if __name__=='__main__': raise SystemExit(main())
