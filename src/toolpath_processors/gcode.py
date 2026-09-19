"""Small modal parser. Unknown executable commands invalidate inferred state."""
from dataclasses import dataclass, field
import math
import re

WORD = re.compile(r'([A-Za-z])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))')

@dataclass
class Move:
    line: int
    feature: str
    layer: int | None
    length_mm: float | None
    extrusion_mm: float | None
    requested_speed_mm_s: float | None

    @property
    def nominal_seconds(self):
        if self.length_mm is not None and self.requested_speed_mm_s:
            return self.length_mm / self.requested_speed_mm_s
        return None

@dataclass
class State:
    position: dict = field(default_factory=lambda: dict.fromkeys('XYZE'))
    absolute_xyz: bool | None = None
    absolute_e: bool | None = None
    feed: float | None = None
    millimeters: bool = True
    feature: str = 'unknown'
    layer: int | None = None

    def invalidate(self):
        self.position = dict.fromkeys('XYZE')
        self.absolute_xyz = self.absolute_e = None
        self.feed = None
        self.feature = 'unknown'

    def consume(self, raw, number):
        """Return (move, barrier). Source text is never rewritten."""
        stripped = raw.strip()
        for prefix in (';TYPE:', '; FEATURE:'):
            if stripped.startswith(prefix):
                self.feature = stripped[len(prefix):].strip().lower()
                return None, False
        if stripped in (';LAYER_CHANGE', '; CHANGE_LAYER'):
            self.layer = 0 if self.layer is None else self.layer + 1
            return None, True
        code = raw.split(';', 1)[0].strip()
        if not code:
            return None, False
        words = list(WORD.finditer(code))
        if not words or WORD.sub('', code).strip():
            self.invalidate()
            return None, True
        pairs = [(m[1].upper(), float(m[2])) for m in words]
        if len({k for k, _ in pairs}) != len(pairs) or not all(math.isfinite(v) for _, v in pairs):
            self.invalidate()
            return None, True
        letter, value = pairs[0]
        command = f'{letter}{value:g}'
        args = dict(pairs[1:])
        if command in ('G90', 'G91') and not args:
            self.absolute_xyz = command == 'G90'
        elif command in ('M82', 'M83') and not args:
            self.absolute_e = command == 'M82'
        elif command == 'G21' and not args:
            self.millimeters = True
        elif command == 'G92' and args and set(args) <= set('XYZE') and self.millimeters:
            self.position.update(args)
        elif command in ('G0', 'G1') and set(args) <= set('XYZEF') and self.millimeters:
            if 'F' in args:
                self.feed = args['F'] / 60 if args['F'] > 0 else None
            delta = {}
            for axis in 'XYZE':
                old = self.position[axis]
                mode = self.absolute_e if axis == 'E' else self.absolute_xyz
                if axis not in args:
                    delta[axis] = 0.0
                elif mode is None:
                    self.position[axis] = None
                    delta[axis] = None
                elif mode:
                    delta[axis] = args[axis] - old if old is not None else None
                    self.position[axis] = args[axis]
                else:
                    delta[axis] = args[axis]
                    self.position[axis] = old + args[axis] if old is not None else None
            length = math.sqrt(sum(delta[a] ** 2 for a in 'XYZ')) if all(delta[a] is not None for a in 'XYZ') else None
            return Move(number, self.feature, self.layer, length, delta['E'], self.feed), False
        else:
            self.invalidate()
            if command == 'G20':
                self.millimeters = False
            return None, True
        return None, False
