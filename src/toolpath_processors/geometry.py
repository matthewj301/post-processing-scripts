"""Geometry estimates, deliberately independent of firmware motion timing."""
import math

TAU = 2 * math.pi

def arc_geometry(start, end, i, j, clockwise):
    center = (start[0] + i, start[1] + j)
    radius = math.hypot(i, j)
    end_radius = math.hypot(end[0] - center[0], end[1] - center[1])
    if radius <= 0 or abs(radius - end_radius) > max(0.01, radius * 1e-4):
        return None
    a = math.atan2(start[1] - center[1], start[0] - center[0])
    b = math.atan2(end[1] - center[1], end[0] - center[0])
    sweep = ((a - b) if clockwise else (b - a)) % TAU
    if start[:2] == end[:2]:
        sweep = TAU
    dz = end[2] - start[2]
    return dict(radius_mm=radius, diameter_mm=2 * radius, center_xy_mm=list(center),
                sweep_degrees=math.degrees(sweep), direction='cw' if clockwise else 'ccw',
                planar_arc_length_mm=radius * sweep,
                helical_length_mm=math.hypot(radius * sweep, dz),
                z_travel_mm=dz, endpoint_radius_error_mm=abs(radius - end_radius))

def fit_circle(points, tolerance):
    """Three spread points define a candidate; every vertex validates the fit."""
    if len(points) < 5 or any(abs(p[2] - points[0][2]) > 1e-6 for p in points):
        return None
    a = points[0]
    b = max(points[1:], key=lambda p: math.dist(a[:2], p[:2]))
    def cross(p):
        return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
    c = max(points, key=lambda p: abs(cross(p)))
    # Translate to avoid loss of precision with large coordinate origins.
    bx, by = b[0] - a[0], b[1] - a[1]
    cx, cy = c[0] - a[0], c[1] - a[1]
    det = 2 * (bx * cy - by * cx)
    if abs(det) < 1e-10:
        return None
    ux = ((bx * bx + by * by) * cy - (cx * cx + cy * cy) * by) / det
    uy = (bx * (cx * cx + cy * cy) - cx * (bx * bx + by * by)) / det
    center = (a[0] + ux, a[1] + uy)
    radius = math.hypot(ux, uy)
    residuals = [abs(math.dist(p[:2], center) - radius) for p in points]
    if max(residuals) > tolerance:
        return None
    angles = [math.atan2(p[1] - center[1], p[0] - center[0]) for p in points]
    steps = [(q - p + math.pi) % TAU - math.pi for p, q in zip(angles, angles[1:])]
    # Reject reversals and polygon corners; at least four segments and 5° sweep.
    if any(abs(s) < 1e-8 or abs(s) > math.pi / 4 + 1e-8 for s in steps):
        return None
    if not (all(s > 0 for s in steps) or all(s < 0 for s in steps)):
        return None
    sweep = abs(sum(steps))
    if not math.radians(5) <= sweep <= TAU + 1e-6:
        return None
    sagitta = radius * (1 - math.cos(max(map(abs, steps)) / 2))
    return dict(radius_mm=radius, diameter_mm=2 * radius, center_xy_mm=list(center),
                sweep_degrees=math.degrees(sweep), arc_length_mm=radius * sweep,
                segment_count=len(steps), direction='ccw' if steps[0] > 0 else 'cw',
                max_radial_residual_mm=max(residuals),
                rms_radial_residual_mm=math.sqrt(sum(v * v for v in residuals) / len(residuals)),
                max_chord_error_estimate_mm=sagitta + max(residuals),
                fit_tolerance_mm=tolerance,
                fit_confidence='high' if max(residuals) <= tolerance / 4 and sweep >= math.radians(15) else 'limited',
                confidence_basis='Geometric heuristic, not probability or proof of intended CAD geometry.')
