; Synthetic history comparison fixture, not a machine-ready print.
G21
G90
M83
G1 X0 Y0 Z0.2 F6000
;LAYER_CHANGE
;TYPE:Internal infill
G1 X20 E1 F6000
G1 E-0.5 F1800
G1 Y10 F6000
G1 E0.5 F1800
;TYPE:Top surface
G1 X0 E1 F3000
G1 Y11 F6000
G1 X20 E1 F3000
