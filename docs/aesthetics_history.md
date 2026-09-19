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
distance and retracted filament since that move. The original preceding-segment fields remain available. Schema 3 also adds a
distance-weighted history window, preceding-feature totals and commanded machine
state. None of these fields infer actual pressure or temperature.

Requested speed is modal F / 60. Nominal duration is length / requested speed:
firmware acceleration and look-ahead make actual duration different. Filament
speed is commanded filament length per nominal second, not volumetric flow.

The intended experiment compares identical visible paths after differing
extrusion histories, with controlled material, lighting and camera position.
Use this report to identify contexts to reproduce; differences in the report
alone do not establish the cause of an aesthetic defect. No speed cap is applied.

## Supported subset and uncertainty

G0/G1, G90/G91, M82/M83, G92 XYZE, G21 and plane selection are interpreted.
G2/G3 XY arcs with relative I/J center offsets and absolute XYZ are supported;
helical Z motion is included. R-format, G18/G19 arcs and invalid arc geometry
remain state barriers. G17 is assumed initially and must be re-established after
an unknown command before arc analysis can resume. Coordinates begin
unknown; XYZ and E modes must be established explicitly. Missing-axis deltas are
zero. Relative moves can have known length without known absolute position.
Units initially follow the Orca millimeter convention; G20 disables move analysis
until G21. Support targets Klipper-style independent XYZ/extrusion modes.

Orca `;TYPE:` and `; FEATURE:` comments identify features; both layer marker
formats are supported. Layer numbers are zero-based marker counts, not guaranteed
slicer display numbers. Source line numbers exclude this processor's comments.

Unknown executable commands (including tool changes, unsupported arcs, custom macros
and firmware retraction) conservatively clear positions,
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


## Resolution and curve geometry (report schema 2)

`resolution.linear_deposition_paths` covers all known positive-extrusion linear
paths, not just cosmetic entries. Travel, retraction/prime, feature/layer changes,
coordinate resets, arcs and state barriers separate paths. Each path records:

- Source start/end line, feature and layer.
- Move count, total length and moves per millimeter.
- Segment lengths: minimum, p10, median, p90, maximum and mean (millimeters).
- Heading-change distribution in degrees between known adjacent 3D segments.
- Fitted planar XY curve candidates, with segment count, radius, diameter,
  center, direction, sweep, fitted arc length and actual polyline length.

Fits use three spatially spread vertices to define a candidate circle and check
all vertices against a radial tolerance (default 0.02mm). They require at least
four segments, 5 degrees of sweep, consistent turning direction, no step over
45 degrees and constant Z. Greedy candidates are capped at 256 segments and
flagged when capped; a long circle can appear as multiple candidates. This is
not a general CAD reconstruction or proof that a polygon was intended as an arc.
Very shallow, short, noisy or nonplanar curves may remain unclassified.

`max_chord_error_estimate_mm` is the largest angular-step sagitta plus maximum
vertex radial residual relative to the fitted circle, not error against the
original CAD. RMS/max radial residual and fit tolerance are reported separately.
`fit_confidence` is a documented geometric heuristic: high means residual no more
than a quarter of tolerance and at least 15 degrees of sweep; otherwise limited.
It is not statistical confidence or a guarantee of surface quality.

`resolution.explicit_arcs` records each supported G2/G3 command, including travel
arcs: source line, feature, layer, extrusion, radius, diameter, center, sweep,
direction, planar length, helical length and endpoint radial mismatch. Mismatch
above max(0.01mm, radius * 0.0001) is treated as unsupported instead of inventing a
circle. The original G-code is preserved even when analysis rejects it.

Firmware subdivision is optional:

```sh
python3 scripts/aesthetics_history.py --report-only \
  --arc-resolution-mm 1.0 --fit-tolerance-mm 0.02 /path/to/print.gcode
```

Use your actual `[gcode_arcs] resolution`, not the example value by default.
The estimate is `max(1, floor(helical_length / resolution))`, matching the local
Kalico gcode_arcs implementation inspected during development. Firmware variants
may differ. Without the argument, estimated segment count is null. Counts for
fitted curves are actual input G1/G0 move counts; counts for explicit arcs are
firmware estimates. Neither is a measured executed trajectory.


## Commanded state, history and viewer (report schema 3)

Supported non-motion commands now preserve geometry while recording commanded
state: M104/M109/M140/M190 S, M106 S (default part fan only), M107, M204 S or P+T,
M220/M221 S, SET_PRESSURE_ADVANCE ADVANCE/SMOOTH_TIME, and SET_VELOCITY_LIMIT
ACCEL/VELOCITY/SQUARE_CORNER_VELOCITY/MINIMUM_CRUISE_RATIO. Commands with unsupported
parameters remain barriers; per-tool temperature/fan control and named extruders
are not assumed. Settings are targets, not sensor readings or proof of runtime
firmware state. Fan speed is a fraction from 0 to 1.

Raw speed and extrusion remain available. Effective requested values apply known
M220/M221 multipliers. Initial factors assume a fresh 100% override state; unknown
commands clear them to null until explicitly set again. Velocity limits are
recorded, but effective requested speed is not capped by them: the report does not
simulate firmware planning. Absolute E coordinates are kept in commanded units,
so changing M221 does not fabricate a retract or prime.

Each cosmetic entry has `history`, covering the preceding 50mm of deposition by
default (`--history-window-mm`). The oldest segment is proportionally clipped to
the distance window. Raw/effective extrusion and nominal deposition time are
weighted by retained length, so subdividing an identical path does not change
these totals. Time uses requested speed times its known override, not acceleration.
`window_filled` distinguishes a full window from partial/unknown history.

`preceding_feature` aggregates deposition length and raw extrusion over the
most recent run of the same feature/layer, including separate lines joined by
travel. It does not infer a geometric island; adjacent same-feature islands may
be combined. Its name can match the current feature on a later path entry.
Travel, retract, E-only prime, explicit G4 P dwell and unknown-duration wait flags
cover the gap since the preceding deposition. Retraction and prime are raw
commanded filament lengths. M109/M190 and M400 flag unknown wait duration. Thermal
waits do not discard geometry. Unknown executable commands clear all history;
layer markers preserve rolling history but establish a new feature run at the
next deposition. No hidden macro motion is guessed.

`spatial_moves` records parsed moves, endpoints, raw/effective values and commanded
state snapshots. `coverage` counts known endpoints and unsupported commands;
`unsupported_commands` lists source lines and commands to explain missing data.
This is G-code coordinate space, not a calibrated mapping to machine coordinates.

Generate a self-contained local viewer:

```sh
python3 scripts/aesthetics_history.py --report-only /path/to/print.gcode \
  --history-window-mm 50 --viewer /path/to/print-viewer.html
```

Open the HTML file in a browser. Choose a layer and color by segment length,
requested speed with override, nominal filament speed, curvature, fan or hotend
target. Select a path by clicking or with the slider/Previous/Next controls;
arrow keys work when the canvas is focused. Circled cosmetic entries expose
history. Unknown values use gray dashes; exact selected values appear in the
inspector. Colors scale per layer, so identical colors across layers need not
mean identical values. Curvature is fitted or commanded, never measured.

The plot is an XY projection. Explicit arcs are tessellated only for display,
independently of firmware subdivision. The file is fully local and embeds its
report without network requests. JSON saving is available inside the viewer.
Viewer/report/input paths must be distinct. A viewer write failure prevents
G-code replacement, but the JSON report may already have been updated.

Large files are read into memory and spatial data is retained for every parsed
move. Report generation and viewer size grow with the input; streaming and
large-print rendering optimization are not implemented. The synthetic
`examples/aesthetics_context.gcode` demonstrates two layers and varied state,
not a runnable calibration print. Motion estimation, adjacent-line timing,
cross-layer artifact alignment and physical matched experiments remain future
work.
