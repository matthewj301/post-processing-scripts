"""Explicit, file-bound startup facts established by a firmware/config audit."""
from dataclasses import dataclass
import hashlib
import json
import math
import re


@dataclass(frozen=True)
class StartupContract:
    input_sha256: str
    line: int
    command: str
    config_sha256: str
    firmware_revision: str
    evidence: str
    speed_factor: float
    extrusion_factor: float

    def __post_init__(self):
        for key in ('input_sha256', 'config_sha256'):
            if not isinstance(getattr(self, key), str) or not re.fullmatch('[0-9a-f]{64}', getattr(self, key)):
                raise ValueError(f'Invalid contract {key}')
        if type(self.line) is not int or self.line < 1:
            raise ValueError('Contract line must be a positive integer')
        if (not isinstance(self.command, str) or not self.command.startswith('PRINT_START ')
                or any(c in self.command for c in '\n\r;')):
            raise ValueError('Contract must match one exact PRINT_START invocation')
        for key in ('firmware_revision', 'evidence'):
            if not isinstance(getattr(self, key), str) or not getattr(self, key).strip():
                raise ValueError(f'Contract {key} is required')
        for value in (self.speed_factor, self.extrusion_factor):
            if type(value) not in (float, int) or not math.isfinite(value) or value <= 0:
                raise ValueError('Contract multipliers must be finite and positive')

    @classmethod
    def from_json(cls, text):
        values = json.loads(text)
        if not isinstance(values, dict) or set(values) != set(cls.__dataclass_fields__):
            raise ValueError('Startup contract must contain exactly the documented fields')
        return cls(**values)

    def verify_source(self, text):
        lines = text.splitlines()
        if (hashlib.sha256(text.encode('utf-8')).hexdigest() != self.input_sha256
                or self.line > len(lines)
                or lines[self.line-1].split(';', 1)[0].strip() != self.command):
            raise ValueError('Startup contract does not match this input file and command')

    def apply(self, state, number):
        if number == self.line:
            # No coordinates, modes, E origin, feed, or thermal state are invented.
            state.context['speed_factor'] = self.speed_factor
            state.context['extrusion_factor'] = self.extrusion_factor
