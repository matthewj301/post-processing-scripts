# Experimental cosmetic-entry conditioning

This processor changes print behavior. It conditions the last portion of an
interior deposition path before a cosmetic entry, by matching its commanded
filament rate to the upcoming cosmetic path. The hypothesis is that making this
preceding flow history more consistent can reduce visible entry transients.
**No physical finish improvement has been verified.** This is an A/B experiment,
not a production recommendation or an inferred pressure-control model.

## What is different from Orca smoothing?

Orca already has extrusion-rate smoothing (PressureEqualizer). Source checked:
OrcaSlicer checkout `2ad6beed32`, `PrintConfig.cpp` and
`GCode/PressureEqualizer.cpp`. Its slope limiter is the existing baseline.

This experiment requests a constant-flow conditioning region of fixed deposition
length inside the preceding interior path while preserving cosmetic commands.
It does not impose a global speed cap or implement another general slope limiter.
It must earn its place by outperforming an equivalent Orca-only configuration.
The commanded plateau does not guarantee a physically steady pressure or flow:
acceleration, PA and travel still affect execution.

## Exact scope

- Default conditioning distance: 10mm (experimental parameter, not calibrated).
- Eligible preceding features: inner wall, internal infill, internal solid infill
  and their Prusa-style aliases. Feature comments are trusted as slicer labels;
  the processor does not prove that these paths are invisible in the final part.
- Eligible destinations: outer wall and top surface (plus aliases).
- Requires 5mm of continuous cosmetic G1 deposition whose commanded filament
  rate stays within 1% of the first segment's rate.
- Planar G1 interior deposition only; absolute XYZ; absolute or relative E.
- No retract/prime, dwell, unknown macro, layer/Z transition, or state change in
  between. M204/SET_VELOCITY_LIMIT are allowed, because commanded E/F is retained;
  those changes still affect real motion. Maximum intervening travel defaults
  to 2mm. A long non-extruding travel can negate the hypothesis, so it is bounded.
- Never speeds up an interior move. A transition is skipped if matching requires
  speedup or slowing below 25% of any selected original speed (configurable).
- Short interior runs and unsupported/missing state are skipped. Circular arcs
  are not transformed. Typical retracted transitions will receive no change.

For each selected segment, requested filament rate is `E_delta / length * speed`.
The new interior speed is `target_rate / (interior_E_delta / interior_length)`.
Same-tool constant speed/flow override factors cancel from this ratio; a change
in them invalidates the candidate. There is no filament-diameter assumption.

Only the conditioning boundary is split. Final XYZ endpoints and total commanded
E are preserved; interpolated boundary coordinates use nine decimal places.
The original feedrate is explicitly restored after each edited source move.
Cosmetic lines, temperature, fan and PA settings are not rewritten. Interior
timing does change and can also affect heat, bonding and print time.

## Create the physical A/B test

1. Import `examples/cosmetic_entry_coupon.stl` in Orca. It is a 60 × 20 × 12mm
   solid; use your known-good printer/filament profile, two walls, zero sparse
   infill, zero top layers, and three bottom layers to make an open wall coupon.
   Use inner/outer wall order and an aligned seam on a long face. Preserve your
   machine's normal temperatures, PA, cooling and safe speed limits.
2. Use an interior wall speed above your outer-wall speed within the profile's
   existing limits. This is necessary to test a flow drop. Do not invent higher
   speeds to force a result. Keep arc fitting off for this first linear test.
3. For the isolated first comparison, export one G-code with Orca extrusion-rate
   smoothing disabled. Keep that source untouched. If you already use smoothing,
   also export a separately labeled Orca-only baseline with your original setting.
4. Generate A and B from the same exported file:

```sh
python3 scripts/condition_cosmetic_entry.py /path/to/coupon.gcode \
  --ab-dir /path/to/coupon-ab --distance-mm 10
```

5. A is an exact copy of the input. B contains the conditioned interior tail.
   Inspect `B-conditioned.gcode.conditioning.json` for changed transitions and
   their source lines, length, before/after feedrates and nominal time cost.
   If no transitions change, the command exits 2 and writes no print files:
   check travel/retraction, feature ordering and explicit coordinate/E modes.
   Do not remove needed retractions or machine protections just to make it apply.
6. Inspect B in Orca before printing: paths/total extrusion should agree with A;
   speed changes should be limited to interior wall tails. Use Orca's execution
   preview to assess the speed actually reached. The report's time cost is only
   distance/feedrate arithmetic.
7. Print A and B separately at the same bed location, using the same spool,
   conditioning, warmup and cooling. Reverse order for a second pair. Photograph
   the seam/entry region with fixed lighting, angle, exposure and distance. Judge
   the samples without their A/B labels if possible.
8. Look for a repeatable reduction in entry streak/bulge/finish discontinuity
   with no new interior or wall defects. Include dimensional quality and time
   cost. Compare against your Orca-only smoothing baseline before accepting it.
   If the effect is absent, inconsistent or already achieved by Orca, stop using
   this processor. Do not tune unrelated settings between A and B.

The synthetic `cosmetic_entry_fixture.gcode` only verifies transformation behavior;
it is **not** a machine-ready print. The STL is intended to be sliced normally.

## Other output modes

```sh
python3 scripts/condition_cosmetic_entry.py input.gcode --output test.gcode
```

For intentional Orca integration after physical evaluation, use the executable
script path followed by `--in-place` in the post-processing scripts field. Orca
appends the file path. A `.control.gcode` backup is saved before replacement.
Existing output, backup or report files are never overwritten. Already processed
input is refused: start from the original control to change parameters. Run this
processor before optional diagnostic annotation. Disable by removing it from
Orca's post-processing field and reslicing from the original profile.

Available parameters: `--distance-mm`, `--max-travel-mm`, `--min-speed-ratio`.
All modes require Python 3.10+ and use no third-party dependencies. Files are
written individually; failure can leave backup/report files, but input is only
replaced after they succeed. Concurrent processing of the same path is unsupported.

## Verification status

Automated checks cover relative/absolute E conservation, original cosmetic
commands, feedrate restoration, flow ratios across different extrusion densities,
split/multi-segment conditioning, bounded slowdowns, excluded transitions, A/B
integrity and rerun refusal. These are software invariants, not physical evidence.
The analyzer/viewer is an optional diagnostic aid; Orca remains the print preview.
