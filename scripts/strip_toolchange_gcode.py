#!/usr/bin/env python3
import argparse

parser = argparse.ArgumentParser(
                    prog='strip_toolchange_gcode.py',
                    description='Strips out heating commands from gcode when a start_print macro is defined')
parser.add_argument('input_file', help='Input file')

args = parser.parse_args()
correct_toolchange_macro = 'ERCF_CHANGE_TOOL_STANDALONE'
incorrect_toolchange_macro = 'T'
correct_toolchange_macro_found = False
first_toolchange_instance = True
lines_removed = 0

processed_lines = []

with open(args.input_file, 'r') as f:
    lines = f.readlines()
    for line in lines:
        if line.startswith(correct_toolchange_macro):
            correct_toolchange_macro_found = True
            if first_toolchange_instance:
                lines_removed += 1
                first_toolchange_instance = False
                continue
            else:
                processed_lines.append(line)
                continue
        else:
            if correct_toolchange_macro_found:
                if line.startswith(incorrect_toolchange_macro):
                    lines_removed += 1
                    continue
                else:
                    processed_lines.append(line)
            else:
                processed_lines.append(line)

with open(args.input_file, 'w') as f:
    if lines_removed > 0:
        f.write(f'; Edited by {parser.prog}: Removed {lines_removed} lines\n')
    for line in processed_lines:
        f.write(line)


