; SYNTHETIC SOFTWARE TEST. Not a printable job or calibration recommendation.
G90
M83
G92 X0 Y0 Z0.4 E0
;LAYER_CHANGE
;LAYER_CHANGE
;TYPE:Outer wall
G1 X20 E1 F6600 ; X component intersects synthetic band
G1 X40 E1
G1 Y20 E1 ; Y has no configured band
;TYPE:Sparse infill
G1 X60 E1
