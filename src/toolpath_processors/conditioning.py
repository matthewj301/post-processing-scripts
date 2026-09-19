"""Experimental interior-flow conditioning. No measured finish benefit is claimed."""
from dataclasses import dataclass
from decimal import Decimal
from copy import deepcopy
import hashlib
import math
import re
from .gcode import State, WORD

MARKER = '; COSMETIC_ENTRY_CONDITIONING_V1'
INTERIOR = {'inner wall', 'internal infill', 'internal solid infill', 'perimeter', 'solid infill'}
COSMETIC = {'outer wall', 'top surface', 'external perimeter', 'top solid infill'}

@dataclass
class ConditioningResult:
    output: str
    report: dict

def number(value):
    return f'{value:.9f}'.rstrip('0').rstrip('.') or '0'

def changed_line(record, tail_fraction, feed):
    """Split only the conditioning boundary; restore modal F after each edit."""
    raw, move, absolute_e, start_e = record
    ending = '\r\n' if raw.endswith('\r\n') else '\n'
    body = raw.rstrip('\r\n')
    code, separator, comment = body.partition(';')
    words = list(WORD.finditer(code))
    values = {m[1].upper(): m[2] for m in words[1:]}
    prefix = ''
    e_tail = values['E']
    if tail_fraction < 1 - 1e-10:
        fraction = 1 - tail_fraction
        point = [a + (b-a)*fraction for a,b in zip(move.start_xyz, move.end_xyz)]
        e_prefix = Decimal(number((start_e if absolute_e else 0) + move.extrusion_mm*fraction))
        if not absolute_e:
            e_tail = format(Decimal(values['E']) - e_prefix, 'f')
        prefix = f'G1 X{number(point[0])} Y{number(point[1])} Z{number(point[2])} E{format(e_prefix, "f")} F{number(move.requested_speed_mm_s*60)}{ending}'
    # Retain original endpoint tokens; only relative E must be split.
    def substitute(match):
        letter = match[1].upper()
        if letter == 'F': return ''
        if letter == 'E': return 'E' + e_tail
        return match[0]
    tail = WORD.sub(substitute, code).rstrip()
    tail += f' F{number(feed)}'
    if separator: tail += ' ;' + comment
    return prefix + tail + ending + f'G1 F{number(move.requested_speed_mm_s*60)} ; restore original feedrate{ending}'

def stable_entry(lines, current_line, current_move, state, target_rate):
    """Require 5mm of uninterrupted cosmetic deposition at a consistent rate."""
    distance=current_move.length_mm
    lookahead=deepcopy(state)
    for n in range(current_line,len(lines)):
        if distance >= 5: return True
        move,barrier=lookahead.consume(lines[n],n+1)
        if barrier or lookahead.event: return False
        if move is None:
            if lines[n].split(';',1)[0].strip(): return False
            continue
        if (move.command!='G1' or move.feature!=current_move.feature or move.layer!=current_move.layer
            or move.length_mm is None or move.length_mm<=0 or move.extrusion_mm is None or move.extrusion_mm<=0
            or move.requested_speed_mm_s is None or move.start_xyz[2]!=move.end_xyz[2]): return False
        rate=move.extrusion_mm/move.length_mm*move.requested_speed_mm_s
        if abs(rate-target_rate)>target_rate*.01: return False
        distance+=move.length_mm
    return distance>=5

def condition(text, *, distance_mm=10.0, max_travel_mm=2.0, min_speed_ratio=0.25):
    for name,value in (('distance',distance_mm),('max travel',max_travel_mm),('minimum speed ratio',min_speed_ratio)):
        if not math.isfinite(value): raise ValueError(f'{name} must be finite')
    if distance_mm <= 0 or max_travel_mm < 0 or not 0 < min_speed_ratio <= 1:
        raise ValueError('Distance must be positive, travel nonnegative, and speed ratio in (0,1]')
    if MARKER in text: raise ValueError('Already conditioned; start again from the untouched control file')
    if '\0' in text: raise ValueError('Binary G-code is unsupported')
    lines = text.splitlines(keepends=True)
    state, tail, edits, changes, skipped = State(), [], {}, [], []
    travel = 0.0
    for line_number, raw in enumerate(lines, 1):
        code = raw.split(';',1)[0].strip()
        start_e = state.position['E']
        move, barrier = state.consume(raw, line_number)
        if barrier:
            tail.clear(); travel=0.0
            continue
        if move is None:
            # A setting change invalidates the flow comparison. Acceleration can
            # differ between features without changing commanded E/F ratios.
            if code and not (state.event and state.event['command'] in ('M204','SET_VELOCITY_LIMIT')):
                tail.clear(); travel=0.0
            continue
        valid = (move.command == 'G1' and state.absolute_xyz is True
                 and state.absolute_e is not None and move.length_mm is not None
                 and move.requested_speed_mm_s is not None and move.requested_speed_mm_s > 0
                 and all(v is not None for p in (move.start_xyz,move.end_xyz) for v in p)
                 and move.start_xyz[2] == move.end_xyz[2])
        depositing = move.extrusion_mm is not None and move.extrusion_mm > 0 and move.length_mm is not None and move.length_mm > 0
        if valid and depositing and move.feature in INTERIOR:
            if travel: tail.clear()
            travel=0.0
            if tail and (tail[-1][1].feature,tail[-1][1].layer) != (move.feature,move.layer): tail.clear()
            tail.append((raw,move,state.absolute_e,start_e))
            # Keep enough of the contiguous interior path for the requested tail.
            while len(tail)>1 and sum(r[1].length_mm for r in tail[1:]) >= distance_mm:
                tail.pop(0)
            continue
        if valid and depositing and move.feature in COSMETIC and tail:
            reason=None
            if travel > max_travel_mm: reason='travel exceeds limit'
            elif sum(r[1].length_mm for r in tail) < distance_mm - 1e-8: reason='insufficient contiguous interior deposition'
            elif tail[-1][1].end_xyz[2] != move.start_xyz[2]: reason='different Z plane'
            target_rate=move.extrusion_mm/move.length_mm*move.requested_speed_mm_s
            if not stable_entry(lines,line_number,move,state,target_rate): reason=reason or 'entry has less than 5mm of stable commanded flow'
            planned=[]; remaining=distance_mm
            for record in reversed(tail):
                m=record[1]
                portion=min(remaining,m.length_mm)
                speed=target_rate/(m.extrusion_mm/m.length_mm)
                ratio=speed/m.requested_speed_mm_s
                if speed > m.requested_speed_mm_s*(1+1e-8): reason=reason or 'matching flow would require speeding up interior'
                if ratio < min_speed_ratio: reason=reason or 'slowdown exceeds configured bound'
                planned.append((record,portion/m.length_mm,speed*60,portion))
                remaining-=portion
                if remaining <= 1e-8: break
            if reason is None and all(abs(feed-r[1].requested_speed_mm_s*60)<1e-7 for r,_,feed,_ in planned):
                reason='interior flow already matches entry'
            if reason:
                skipped.append(dict(cosmetic_line=line_number,reason=reason))
            else:
                for record,fraction,feed,portion in planned:
                    edits[record[1].line]=changed_line(record,fraction,feed)
                changes.append(dict(cosmetic_line=line_number,cosmetic_feature=move.feature,
                                    interior_feature=tail[-1][1].feature,
                                    conditioning_distance_mm=distance_mm,travel_mm=travel,
                                    target_raw_filament_speed_mm_s=target_rate,
                                    cosmetic_feedrate_mm_min=move.requested_speed_mm_s*60,
                                    nominal_added_seconds=sum(portion/(feed/60)-portion/r[1].requested_speed_mm_s for r,_,feed,portion in planned),
                                    edits=[dict(line=r[1].line,conditioned_length_mm=portion,
                                                original_feedrate_mm_min=r[1].requested_speed_mm_s*60,
                                                new_feedrate_mm_min=feed) for r,_,feed,portion in reversed(planned)]))
            tail.clear();travel=0.0
            continue
        # Accept only known, non-extruding planar travel between the two features.
        if (move.command in ('G0','G1') and move.extrusion_mm == 0
            and move.length_mm is not None and move.start_xyz is not None
            and move.start_xyz[2] == move.end_xyz[2]):
            travel+=move.length_mm
        else:
            tail.clear();travel=0.0
    output=''.join(edits.get(n,line) for n,line in enumerate(lines,1))
    if edits:
        ending='\r\n' if '\r\n' in text else '\n'
        output=MARKER+' experimental interior conditioning; retain original for comparison'+ending+output
    report=dict(processor='cosmetic-entry-conditioning',schema_version=1,status='experimental; physical benefit unverified',
                input_sha256=hashlib.sha256(text.encode()).hexdigest(),
                output_sha256=hashlib.sha256(output.encode()).hexdigest(),
                parameters=dict(distance_mm=distance_mm,max_travel_mm=max_travel_mm,min_speed_ratio=min_speed_ratio),
                changed_transitions=len(changes),changes=changes,skipped_candidates=skipped,
                limitations=['Matches commanded filament rate, not actual nozzle flow or pressure.',
                             'Interior speed only; visible geometry, extrusion and feed remain unchanged.',
                             'Candidates require contiguous planar interior G1 deposition without retraction.',
                             'No benefit is established until a matched physical A/B print.'])
    return ConditioningResult(output,report)
