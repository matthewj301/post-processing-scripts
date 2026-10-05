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

## Quality optimizer — foundation

`scripts/quality_optimizer.py` begins the architecture in the optimizer handoff.
It reuses the conservative modal parser, builds typed path segments, and reports
nominal flow, adjacent deposition flow changes, tiny segments, state uncertainty,
and optional velocity/flow limit violations. Analysis is the default. An explicit experimental VFA pass is available below.

```sh
python3 scripts/quality_optimizer.py /path/to/print.gcode \
  --report /path/to/quality.json --output /path/to/unchanged-copy.gcode
```

The optional output is byte-identical UTF-8 G-code, including line endings and
unknown commands. The default schema-2 report is compact: coverage totals,
feature/layer counts, grouped warnings, and up to 20 sample lines per diagnostic.
Add `--details` for every segment and diagnostic line; this can produce large files. All destinations must be new files. Without `--report`, JSON
goes to stdout. Exit status is 0 for completed analysis (which may have unknown
state), 2 for detected limit violations, and 1 for input/output errors.

Optional `--profile profile.json` accepts this initial flat schema; omitted
machine limits are not checked. This is not yet the full handoff profile schema:

```json
{
  "filament_diameter_mm": 1.75,
  "max_velocity_mm_s": 300,
  "max_flow_mm3_s": 25,
  "tiny_segment_mm": 0.05
}
```

These numbers illustrate configuration, not recommended printer settings.
Verified flow assumes filament-length E and applies known M220/M221 overrides.
The separate `slicer_intent` section estimates source XYZ/E/F under the explicit
assumption that custom macros and tool selections preserve the slicer's modes.
It discards coordinates and feed at those barriers and waits for the file to
re-establish them. It excludes override factors and hidden macro motion,
extrusion, and timing. These estimates never populate verified flow or limit
validation and are marked unusable for optimization. Absolute E also needs its
baseline re-established after a barrier; missing modes are never guessed. Durations
exclude acceleration and firmware look-ahead. Width/height comments are metadata,
not a substitute for extrusion-derived flow. Standard object definitions and
start/end markers, M73 progress, and SET_PRINT_STATS_INFO preserve motion state
under [Klipper's documented command meanings](https://www.klipper3d.org/G-Codes.html).
Runtime object exclusions are not simulated. Targeted M104/M109 and indexed
M106/M107 retain device-specific values without inferring the active device;
unknown extensions and malformed parameters remain barriers.
Unsupported commands, including
macros/tool changes, clear inferred state; unsupported arcs are preserved and
reported as barriers. Supported arcs are absolute XY-plane I/J arcs. An
`incomplete` validation result is not print approval. The CLI does not validate
firmware macro behavior or certify a file safe to print.

### Audited startup state

`--startup-contract contract.json` supplies two narrowly scoped facts established
by inspecting the actual printer: the speed and extrusion multipliers after one
exact `PRINT_START` invocation. It does not skip the macro, invent coordinates,
restore modes, or authorize later unknown commands. The file SHA-256, source
line, and command must all match; editing or reslicing the input invalidates it.
The recorded config fingerprint and firmware revision identify the audit evidence,
but are not an automatic live check. Re-audit after firmware/config changes and
when reusing an export on another printer. The CLI never contacts a printer.

Contract fields are `input_sha256`, `line`, `command`, `config_sha256`,
`firmware_revision`, `evidence`, `speed_factor`, and `extrusion_factor`.
Coordinates, E origin, and modal feed remain unknown until the source establishes
them. This optional contract is shared by parsing and VFA replay validation;
default behavior remains conservative. See the
[K3 live audit](docs/k3_optimizer_audit.md) for the first verified case.

## Experimental VFA avoidance

`--apply-vfa` enables a slowdown-only pass on verified, planar outer-wall G1
extrusions after the first layer. It requires a separate new output file and a
profile containing explicit velocity/flow limits and measured Cartesian X/Y
velocity bands. It never uses conditional `slicer_intent` estimates.

The nested `vfa` profile fields are `x` and `y` (lists of `[low, high]` axis-speed
bands in mm/s), `min_segment_mm`, `max_slowdown_fraction`, `clearance_mm_s`,
`hysteresis_mm_s`, and `transition_weight`. Defaults are 5 mm, 0.15, 1 mm/s,
1 mm/s, and 1 respectively. Bands are toolhead-axis components, not CoreXY motor
speeds. Supply empirical bands for the actual printer/material before printing.

Run the synthetic software fixture to exercise the pass:

```sh
python3 scripts/quality_optimizer.py examples/vfa_fixture.gcode \
  --profile examples/vfa_profile.synthetic.json --apply-vfa \
  --report /tmp/vfa-test.json --output /tmp/vfa-test.gcode
```

**The fixture and profile are software-test data, not printable G-code or machine
recommendations.** Omitting `--apply-vfa` always produces the unchanged copy,
even with VFA bands configured. There are no calibrated bands bundled for the U1.

The pass scores candidate speeds against both axes, bounded slowdown, and the
previous adjacent edit. Hysteresis reduces switching near a band edge. Every
edit changes only F and immediately restores the original modal feed before
another command. A replay checks motion/extrusion equivalence and modal-state
restoration. Input that already exceeds configured speed/flow limits, short
segments, arcs, relative XYZ, bridges, and unknown state are skipped. Each edit
records source line, reason, before/after speed and flow, and nominal added time.
Reports describe input analysis and edit validation separately. Already processed
input is refused; always start an A/B experiment from the untouched original.

This targets commanded steady-state speeds. Firmware acceleration may still
traverse an avoided band; there is no measured surface-quality benefit yet.
The real U1 export remains ineligible after its unresolved vendor-state barriers.
The [vendor state audit](docs/vendor_state_contracts.md) records the source trace
and why the optimizer does not silently ignore those commands.

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

### Extrusion dynamics diagnostics

Analysis reports now include `extrusion_dynamics`; this is read-only and does
not require nonlinear PA or a particular Kalico branch. It reports nominal
adjacent flow jumps, commanded PA/acceleration/smoothing coverage, and moves
whose nominal duration is shorter than the commanded smoothing window.
`--details` includes every eligible extrusion move; summary samples are bounded.

Straight-path ramp scenarios report zero-to-requested-speed time, the distance
needed to reach that speed and stop, and unsmoothed linear-PA extra filament
speed (`PA × E/path × acceleration`). These are analytical scenarios, not
firmware trajectory predictions or calibrated hardware limits. Missing settings
remain unknown; no firmware defaults are assumed. Flow differences are not
reported as flow slew rates because actual transition timing is unknown.

Next validation: capture the target printer's firmware revision, PA, smoothing,
input shaper and motion settings; analyze a representative export; then compare
controlled coupons across flow and acceleration at fixed material/temperature.
Separate model mismatch from extruder saturation before scheduling PA changes
or altering extrusion. Keep firmware responsible for real-time PA execution;
nonlinear PA remains optional. Sensor diameter correction and any future
postprocessor compensation need explicit ownership to avoid double correction.
