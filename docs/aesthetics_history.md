# Aesthetics history processor

The first processor measures commanded context at cosmetic path entries. It adds
stable comments before recognized outer-wall and top-surface deposition entries
and writes INPUT.gcode.aesthetics.json. It does not change executable commands,
speeds, extrusion, path order, or geometry and does not claim to improve finish.

## Run with OrcaSlicer

In the process profile's Post-processing scripts field, use the absolute path to
the executable checkout launcher, for example:

```text
/Users/mjohnson/git/post-processing-scripts/scripts/aesthetics_history.py
```

Orca supplies the exported G-code filename. The launcher requires Python 3.10+
on PATH. No package installation or third-party libraries are needed. If using
an explicit Python executable, use its full path followed by the quoted script
path. Run it after any processor that changes motion. Export plain text G-code.

Manual analysis without changing the input:

```sh
python3 scripts/aesthetics_history.py --report-only /path/to/print.gcode
```

The sidecar stays beside the processed file, which may be in Orca's temporary
export directory. Use `--report /persistent/path/report.json` when retention is
needed; each run overwrites that report. To disable, remove the post-processing
entry. No printer configuration or firmware plugin is required.

## What an entry means

An entry is the first known positive-extrusion spatial move after travel,
retraction/prime, a feature change, or a layer boundary, within a cosmetic feature.
The JSON records the entry move, immediately preceding deposition move, travel
distance and retracted filament since that move. This is segment history, not a
whole-feature average or an inferred pressure/temperature state. Prime amount,
fan settings, temperature, acceleration and actual timing are not modeled yet.

Requested speed is modal F / 60. Nominal duration is length / requested speed:
firmware acceleration and look-ahead make actual duration different. Filament
speed is commanded filament length per nominal second, not volumetric flow.

The intended experiment compares identical visible paths after differing
extrusion histories, with controlled material, lighting and camera position.
Use this report to identify contexts to reproduce; differences in the report
alone do not establish the cause of an aesthetic defect. No speed cap is applied.

## Supported subset and uncertainty

G0/G1, G90/G91, M82/M83, G92 XYZE, and G21 are interpreted. Coordinates begin
unknown; XYZ and E modes must be established explicitly. Missing-axis deltas are
zero. Relative moves can have known length without known absolute position.
Units initially follow the Orca millimeter convention; G20 disables move analysis
until G21. Support targets Klipper-style independent XYZ/extrusion modes.

Orca `;TYPE:` and `; FEATURE:` comments identify features; both layer marker
formats are supported. Layer numbers are zero-based marker counts, not guaranteed
slicer display numbers. Source line numbers exclude this processor's comments.

Unknown executable commands (including tool changes, arcs, custom macros, heaters,
fans, firmware retraction, overrides and dwell) conservatively clear positions,
modes, feed and feature/history. Reports list those barrier lines. Analysis resumes
only when enough state and feature information is re-established. Missing history
is null/false, never a guessed default. This intentionally sacrifices coverage;
inspect barriers before relying on comparisons. It does not parse arbitrary
firmware macro bodies or binary G-code.

## File integrity

Existing bytes are preserved for valid UTF-8 input except inserted comments.
CRLF and missing trailing newline are supported. Reruns replace this processor's
reserved `; TOOLPATH_AESTHETICS_V1 ` comments, so they do not accumulate. Don't
use that prefix for handwritten comments. Input SHA-256 excludes those comments.

The report is written atomically before G-code replacement, and a failed report
write leaves G-code untouched. Files are individually atomic, not a transactional
pair. A failure between writes can leave a new report with the old G-code.
Concurrent processing of the same path is unsupported. Input permissions persist.

## Extend

`gcode.py` owns modal state and Move records; `aesthetics.py` owns the pass and
Result; `cli.py` owns file I/O. Add independent passes with explicit assumptions,
then regression fixtures for supported state, unknown-command boundaries, and
output invariants. Any future command-changing pass must prove bounded geometry
and extrusion changes separately. Keep the two legacy strip scripts independent.

Run: `PYTHONPATH=src python3 -m unittest discover -s tests -v`.
The example file is a synthetic parser fixture, not a machine-ready test print.
