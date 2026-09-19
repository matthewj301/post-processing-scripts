"""Distance-weighted rolling deposition history independent of segment count."""
from collections import deque
import math

class History:
    def __init__(self, window_mm):
        if not math.isfinite(window_mm) or window_mm <= 0:
            raise ValueError('History window must be finite and positive')
        self.window_mm = window_mm
        self.reset()

    def reset(self):
        self.moves = deque()
        self.total = 0.0
        self.feature = None
        self.gap = dict(travel_mm=0.0, retract_mm=0.0, prime_mm=0.0, dwell_s=0.0, unknown_wait=False)

    def snapshot(self):
        length = sum(item['length_mm'] for item in self.moves)
        effective = [item['effective_extrusion_mm'] for item in self.moves]
        times = [item['nominal_seconds'] for item in self.moves]
        return dict(window_mm=self.window_mm, covered_deposition_mm=length,
                    window_filled=length >= self.window_mm - 1e-8,
                    raw_extrusion_mm=sum(item['raw_extrusion_mm'] for item in self.moves),
                    effective_extrusion_mm=sum(effective) if effective and all(v is not None for v in effective) else None,
                    nominal_deposition_seconds=sum(times) if times and all(v is not None for v in times) else None,
                    preceding_feature=dict(self.feature) if self.feature else None,
                    **self.gap)

    def add(self, move):
        depositing = move.extrusion_mm is not None and move.extrusion_mm > 0 and move.length_mm is not None and move.length_mm > 0
        if not depositing:
            if move.extrusion_mm is None or move.length_mm is None:
                self.reset()
            else:
                self.gap['travel_mm'] += move.length_mm
                self.gap['retract_mm'] += max(0, -move.extrusion_mm)
                if move.length_mm == 0: self.gap['prime_mm'] += max(0, move.extrusion_mm)
            return
        speed = move.effective_requested_speed_mm_s
        entry = dict(length_mm=move.length_mm, raw_extrusion_mm=move.extrusion_mm,
                     effective_extrusion_mm=move.effective_extrusion_mm,
                     nominal_seconds=move.length_mm/speed if speed else None)
        key = (move.feature, move.layer)
        if self.feature is None or (self.feature['name'], self.feature['layer']) != key:
            self.feature = dict(name=move.feature, layer=move.layer, start_line=move.line,
                                end_line=move.line, deposition_mm=0.0, raw_extrusion_mm=0.0)
        self.feature['end_line'] = move.line
        self.feature['deposition_mm'] += move.length_mm
        self.feature['raw_extrusion_mm'] += move.extrusion_mm
        self.moves.append(entry)
        self.total += move.length_mm
        while self.total > self.window_mm + 1e-9:
            excess = self.total - self.window_mm
            first = self.moves[0]
            if first['length_mm'] <= excess + 1e-9:
                self.total -= first['length_mm']
                self.moves.popleft()
            else:
                fraction = (first['length_mm'] - excess) / first['length_mm']
                for field in first:
                    if first[field] is not None: first[field] *= fraction
                self.total = self.window_mm
        self.gap = dict(travel_mm=0.0, retract_mm=0.0, prime_mm=0.0, dwell_s=0.0, unknown_wait=False)

    def command(self, event):
        if event:
            if event['duration_s'] is None: self.gap['unknown_wait'] = True
            else: self.gap['dwell_s'] += event['duration_s']
