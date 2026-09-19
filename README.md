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


## Layout

- `scripts/`: executable slicer post-processing scripts.
- `examples/`: sample invocations, slicer settings, and small example inputs.
- `tests/`: automated tests and G-code fixtures.
- `docs/`: script documentation and compatibility notes.

## Adding a script

Give each script a short, consistent name across source, examples, tests,
and documentation. Document its purpose, dependencies, arguments, slicer setup,
G-code changes, and removal in `docs/<name>.md`.

State explicitly which slicers and firmware dialects it supports. Record the
versions used for testing; compatibility is unverified until tested. Explain
whether it modifies the input file in place or writes a separate output, and
whether running it more than once is safe.

Use small G-code fixtures to verify intended transformations and preservation of
unrelated commands. Include relevant edge cases, such as missing markers,
multiple tools, or an already-processed file.

Keep printer-specific slicer profiles in their own profile repository and
reusable firmware modules and macros in `klipper-addons`. If a post-processor
and firmware module must ship together, keep them in a feature-specific repo.
Scripts that need independent releases or installation can graduate to their
own repositories.
