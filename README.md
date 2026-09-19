# G-code post-processing scripts

Experimental print-behavior transformations for OrcaSlicer and Klipper/Kalico,
plus the existing heating/toolchange cleanup scripts. Physical print results,
not report or viewer features, determine whether an aesthetics processor helps.

## Cosmetic-entry conditioning — first behavior-changing experiment

`scripts/condition_cosmetic_entry.py` changes the last part of an interior path
before an outer-wall/top-surface entry to match its commanded filament rate.
Cosmetic commands remain unchanged. This tests whether changing preceding flow
history improves the visible entry. **Physical benefit is not yet verified.**

It preserves geometry and total extrusion, never speeds up interior motion, and
skips retracted, unsupported, short or excessively slowed transitions. It is a
fixed-length conditioning experiment, not another general slope limiter; Orca's
existing extrusion-rate smoothing is the comparison baseline.

Create an untouched control and conditioned test from one Orca export:

```sh
python3 scripts/condition_cosmetic_entry.py /path/to/coupon.gcode \
  --ab-dir /path/to/coupon-ab --distance-mm 10
```

The new directory contains `A-control.gcode`, `B-conditioned.gcode`, and an edit
report. Existing files are not overwritten. Zero changes returns exit code 2 and
creates no print files. Already conditioned input is refused.

Slice `examples/cosmetic_entry_coupon.stl` with your own printer/filament profile.
The full A/B procedure, eligible paths, conservative limits, Orca integration and
known limitations are in [the processor documentation](docs/cosmetic_entry_conditioning.md).
The `.gcode` fixtures in `examples/` are synthetic software tests, not printable jobs.

## Existing cleanup scripts

- `scripts/strip_initial_heating_gcode.py`: strips duplicate first-layer heating
  commands when your start macro owns heating.
- `scripts/strip_toolchange_gcode.py`: strips slicer-inserted toolchange commands
  when your custom workflow owns tool selection.

Use their absolute executable paths in the slicer's post-processing field. These
legacy scripts remain independent of the new package and its dependencies.

## Optional diagnostics

`scripts/aesthetics_history.py` reports commanded state, extrusion history,
segmentation and fitted/explicit arc geometry. Its local viewer is a debugging
aid; Orca remains the main print preview. It does not optimize print quality or
simulate firmware execution. No further preview expansion is part of this work.

```sh
python3 scripts/aesthetics_history.py --report-only /path/to/print.gcode
```

See [analysis documentation](docs/aesthetics_history.md) for supported commands,
uncertainty and report schema 3. If used together, run diagnostics after the
behavior-changing processor so reports describe the modified file.

## Development

Python 3.10+. The new package has no runtime third-party dependencies.

- `src/toolpath_processors/`: parsers and processing passes.
- `scripts/`: checkout launchers usable without package installation.
- `tests/`: behavioral and file-integrity tests.
- `examples/`: fixtures and slicable experiment models.
- `docs/`: per-processor instructions, limits and evidence.

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

CI tests Python 3.10, 3.12 and 3.13. Optional `python3 -m pip install .` provides
package CLI entry points. Keep machine-specific profiles/configs in their own
repos and firmware modules in `klipper-addons`.

New processors must define the intended physical effect, compare existing Orca
functionality, preserve unrelated commands, test geometry/extrusion invariants,
and distinguish software verification from physical evidence. Do not expand the
viewer or analysis framework without a concrete requirement from a print test.
