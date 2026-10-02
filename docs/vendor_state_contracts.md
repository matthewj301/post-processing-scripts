# Vendor state audit — Snapmaker U1

This audit informs parser boundaries. It does **not** authorize bypassing them.

Inspected upstream commit `10f2f69714c059f1dee0423db4f515b8a01f5388` on
2026-10-02. The installed printer could not be compared: SSH rejected a changed
host key. No trust settings, firmware, or printer configuration were changed.
An upstream implementation is not proof of the installed implementation or its
custom hooks.

## Findings

- `TIMELAPSE_TAKE_FRAME`: the inspected handler checks enable/rate-limit state and
  requests `camera.take_a_photo`. No direct G-code motion/state changes occur in
  that handler. External camera service behavior and installed overrides were
  not established. Keep the generic barrier until a versioned installed contract
  is available.
  [Handler](https://github.com/Snapmaker/u1-klipper/blob/10f2f69714c059f1dee0423db4f515b8a01f5388/klippy/extras/timelapse.py#L183)
- `DEFECT_DETECTION_DETECT`: calls `request_detect`, which sends an asynchronous
  camera request with a response callback. The detection path can raise an
  exception and invoke `PAUSE`; it is not unconditional metadata. The pause and
  resume path depends on firmware/configuration. Keep the barrier.
  [Handler](https://github.com/Snapmaker/u1-klipper/blob/10f2f69714c059f1dee0423db4f515b8a01f5388/klippy/extras/defect_detection.py#L719),
  [request](https://github.com/Snapmaker/u1-klipper/blob/10f2f69714c059f1dee0423db4f515b8a01f5388/klippy/extras/defect_detection.py#L374),
  [pause path](https://github.com/Snapmaker/u1-klipper/blob/10f2f69714c059f1dee0423db4f515b8a01f5388/klippy/extras/defect_detection.py#L590).
- `T0`–`T3`: extruder registration dispatches to the advanced switch handler,
  which can remap the requested tool, park/pick, retry, and pause on errors.
  The switch implementation saves modal state and restores selected fields on
  particular paths, including extrusion base compensation and offset handling.
  That is not equivalent to ignoring the command or merely updating an active
  tool index. Keep the barrier until all applicable paths and tool-specific
  state have explicit contracts.
  [Registration](https://github.com/Snapmaker/u1-klipper/blob/10f2f69714c059f1dee0423db4f515b8a01f5388/klippy/kinematics/extruder.py#L544),
  [dispatch](https://github.com/Snapmaker/u1-klipper/blob/10f2f69714c059f1dee0423db4f515b8a01f5388/klippy/kinematics/extruder.py#L1330),
  [restoration](https://github.com/Snapmaker/u1-klipper/blob/10f2f69714c059f1dee0423db4f515b8a01f5388/klippy/kinematics/extruder.py#L1778).
- `PRINT_START`: the upstream macro applies per-extruder flow calibration,
  resets E, and sets the speed override. The local extended firmware adds
  configurable print hooks. Startup cannot be treated as a comment or assumed
  to establish every field needed by a transform.
  [Upstream macro](https://github.com/Snapmaker/u1-klipper/blob/10f2f69714c059f1dee0423db4f515b8a01f5388/lava/fluidd.cfg#L193).

## Consequence for the optimizer

The conditional `slicer_intent` track remains diagnostic only. VFA transforms
read the strict IR, never conditional estimates. Explicit source commands can
re-establish supported modal state after a barrier; no command is inserted to
force the printer into an assumed state.

A future installed-firmware contract needs a source/config fingerprint, exact
commands and accepted parameters, state effects, asynchronous side effects,
and regression cases covering normal and failure paths. There is deliberately
no blanket macro allowlist or CLI switch to ignore unknown commands.
