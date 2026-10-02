# Annex K3 optimizer audit — 2026-10-02

Read-only SSH to `pi@k3.local` succeeded. Moonraker reported hostname `k3`,
Kalico `v2026.05.00-4-g29e8ef41`, ready, with the previous print complete.
Installed source revision: `29e8ef4123377b94b0748d7810ae2d79905eda2e`.
No G-code was submitted and no printer settings or files were changed.

The active configuration is associated with the user's `K3D` repository. The
separate `K3` checkout has a different PRINT_START interface and was not used
as evidence of the installed macro behavior.

## Verified startup facts

The loaded PRINT_START accepts the exported HOTEND_TEMP, BED_TEMP,
TARGET_CHAMBER_TEMP, and MATERIAL parameters. It invokes RESET_MULTIPLIERS,
which issues M220 S100 and M221 S100. Its later helpers do not set different
multipliers. LINE_PURGE, SMART_PARK, and the wipe routines save/restore state
after this reset. Loaded macro overrides do not replace M220 or M221.

The contract records only speed_factor=1 and extrusion_factor=1 on successful
startup, assuming no external override changes. It makes no claim about startup
coordinates, E origin, feed, temperature readings, or homing success. Source G90,
G21, M83 and subsequent motion establish the state used in analysis.

Loaded config fingerprint (SHA-256 of sorted compact JSON of the Moonraker
`configfile.config` mapping):
`09645abfd69ddafe4ea512702ebc9b3afc8e7d6c8e411f9e00d913f366c3cba7`.

Input file:
`UHP-200(221208)_DC - Back Exit - Mirrored_UHP-200 DC Cover (1)_0.3mm_ABS_Generic Klipper Printer_14m16s.gcode`.
Input SHA-256: `045a8e2b0e656e6264fa54362ef7b289a45850d8c6889884d814410ab86e9b22`. Contract applies at line 215 only.

## Software results

- 23 layers; 71,722 motion records.
- With audited startup multipliers: 71,719 fully reconstructed motion records,
  52,898 deposition flow estimates. Three initial moves have unknown start state.
- 216 outer-wall deposition segments at least 5 mm long after the first layer.
- No-op emission is byte-identical to the provided source.
- No physical quality claim or print qualification follows from these checks.

No VFA bands or hotend flow capacity have been calibrated in this task. Exported
long-wall speeds include 130, approximately 379.862, and 400 mm/s. The peak
commanded deposition-flow estimate is approximately 86.59 mm³/s across the file;
this is a nominal E/F calculation, not measured melt flow or firmware-planned
speed. Establish measured limits and bands before preparing a changed print.

The audit is a dated snapshot, not an enduring assertion about printer state.
New files require a new file-bound contract; changed configuration or firmware
requires a fresh audit. No generic PRINT_START allowlist has been introduced.
