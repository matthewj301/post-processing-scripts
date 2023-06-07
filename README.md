# GCode Post-Processing Scripts

This is a collection of useful GCode post-processing scripts I wrote out of necessity.

## Installation
Just post the full path to the script in the "Post-processing scripts" section of your slicer and make sure the scripts are executable.

## Scripts
- `strip_initial_heating_gcode.py`
  - Strips first_layer hotend heating commands from the GCode. 
  - Useful if you use your own start GCode and don't want to heat the hotend twice.
- `strip_toolchange_gcode.py`: 
  - Strips toolchange commands from the GCode. 
  - Some slicers (Orcaslicer, Prusaslicer) insert Tx commands even if you've defined your own toolchange GCode.
    - This script removes those default toolchange commands and leaves the ones you defined.
  - Some slicers also insert Tx commands at the beginning of your gcode file if you have multiple tools defined.
    - I do my initial tool change in my custom start GCode, so I don't need any toolchange commands at the start of the file.
