#!/usr/bin/env python3
import argparse

parser = argparse.ArgumentParser(
                    prog='strip_toolchange_gcode.py',
                    description='Strips out heating commands from gcode when a start_print macro is defined')
parser.add_argument('input_file', help='Input file')

args = parser.parse_args()
toolchange_macro = 'T'
first_toolchange_instance = True
lines_removed = 0

processed_lines = []

with open(args.input_file, 'r') as f:
    lines = f.readlines()
    for line in lines:
        if line.startswith(toolchange_macro):
            if first_toolchange_instance:
                lines_removed += 1
                first_toolchange_instance = False
                continue
            else:
                processed_lines.append(line)
                continue
        else:
            processed_lines.append(line)

with open(args.input_file, 'w') as f:
    if lines_removed > 0:
        f.write(f'; Edited by {parser.prog}: Removed {lines_removed} lines\n')
    for line in processed_lines:
        f.write(line)


