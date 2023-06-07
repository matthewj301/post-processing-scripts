#!/usr/bin/env python3
import argparse

parser = argparse.ArgumentParser(
                    prog='strip_initial_heating_gcode.py',
                    description='Strips out initial heating commands from gcode when a start_print macro is defined')
parser.add_argument('input_file', help='Input file')

args = parser.parse_args()
start_print_macro = 'START_PRINT'
start_print_initial_hotend_temp_variable = 'EXTRUDER_TEMP'
start_print_initial_hotend_temp = None
start_print_macro_found = False
lines_removed = 0

processed_lines = []

with open(args.input_file, 'r') as f:
    lines = f.readlines()
    for line in lines:
        if line.startswith(start_print_macro):
            start_print_macro_found = True
            start_print_initial_hotend_temp = line.split(f'{start_print_initial_hotend_temp_variable}=')[1].split(' ')[0]
            processed_lines.append(line)
            continue
        else:
            if start_print_macro_found:
                if line.startswith('M104'):
                    if line.split('S')[1].split(' ')[0] == start_print_initial_hotend_temp:
                        lines_removed += 1
                        continue
                    else:
                        processed_lines.append(line)
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
