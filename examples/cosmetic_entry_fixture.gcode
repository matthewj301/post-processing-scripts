; Synthetic transformation fixture, not a machine-ready print.
G21
G90
M83
G1 X0 Y0 Z0.2 F6000
;LAYER_CHANGE
;TYPE:Inner wall
G1 X40 E2 F6000
G1 Y1 F6000
;TYPE:Outer wall
G1 X0 E2 F3000
G1 Y2 E0.05
