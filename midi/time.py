#!/usr/bin/env python3

import numbers
from .io import _var_int_parse, _var_int_bytes

class Tempo:
    def __init__(self, source=None, **keywords):
        if source == None:
            self.mpqn = keywords.get('mpqn', 500000)
            self.bpm = keywords.get('bpm', 120)
        elif isinstance(source, numbers.Number):
            self.bpm = source
        else:
            self.mpqn = int.from_bytes(source, 'big')

    @property
    def mpqn(self):
        return int(60000000 // self.bpm)

    @mpqn.setter
    def mpqn(self, value):
        self.bpm = 60000000 / value

    @property
    def bps(self):
        return self.bpm / 60

    @mpqn.setter
    def bps(self, value):
        self.bpm = value * 60

    def __str__(self):
        return '{bpm} BPM'.format(bpm=self.bpm)

    def __repr__(self):
        return 'Tempo({bpm})'.format(bpm=self.bpm)

    def __bytes__(self):
        return self.mpqn.to_bytes(3, 'big')

class TimeDivision:
    def __init__(self, source=None, **keywords):
        self.mode = 'ppqn'
        self.pps = None
        self.ppqn = None
        if source == None:
            self.ppqn = keywords.get('ppqn', None)
            self.frames = keywords.get('frames', None)
            self.subframes = keywords.get('subframes', None)
            if self.ppqn == None:
                self.mode = 'pps'
        elif isinstance(source, numbers.Number):
            self.mode = 'ppqn'
            self.ppqn = source
        else:
            bits = int.from_bytes(source, 'big')
            if bits & 0x8000:
                self.mode = 'pps'
                self.frames = (bits & 0x7f00) >> 8
                if self.frames == 29:
                    self.frames = 29.97
                self.subframes = bits & 0x00ff
                self.pps = self.frames * self.subframes
            else:
                self.ppqn = bits & 0x7fff

    @property
    def frames(self):
        if hasattr(self, '_frames'):
            if self._frames == 29:
                return 29.97
            else:
                return self._frames
        else:
            return None

    @frames.setter
    def frames(self, value):
        if value == 29.97:
            self._frames = 29
        else:
            self._frames = value
        if self.subframes != None:
            self.pps = value * self.subframes
            self.mode = 'pps'

    @frames.deleter
    def frames(self):
        del self._frames
        self.mode = 'ppqn'

    @property
    def subframes(self):
        if hasattr(self, '_subframes'):
            return self._subframes
        else:
            return None

    @subframes.setter
    def subframes(self, value):
        self._subframes = value
        if self.frames != None:
            self.pps = value * self.frames
            self.mode = 'pps'

    @subframes.deleter
    def subframes(self):
        del self._subframes
        self.mode = 'ppqn'

    def __str__(self):
        if self.mode == 'ppqn':
            return '{ppqn] PPQN'.format(ppqn=self.ppqn)
        else:
            return '{pps} PPS'.format(pps=self.pps)

    def __repr__(self):
        if self.mode == 'ppqn':
            return 'TimeDivision({ppqn})'.format(ppqn=self.ppqn)
        else:
            return 'TimeDivision(frames={frames}, subframes={subframes})'\
                    .format(frames=self.frames, subframes=self.subframes)

    def __bytes__(self):
        if self.mode == 'ppqn':
            return self.ppqn.to_bytes(2, 'big')
        else:
            value = 0x8000 | (self._frames << 8) | self._subframes
            return value.to_bytes(2, 'big')

class Delta:
    def __init__(self, source=None, time_division=None, tempo=None):
        self.time_division = time_division
        if tempo == None:
            self.tempo = Tempo()
        else:
            self.tempo = tempo
        if source == None:
            self.secs = None
        elif isinstance(source, numbers.Number):
            self.ticks = source
        else:
            self.ticks = _var_int_parse(source)

    @property
    def ticks(self):
        if self.secs != None and self.tempo != None and \
                self.time_division != None:
            if self.time_division.mode == 'ppqn':
                return int(self.secs * self.tempo.bps * 
                        self.time_division.ppqn)
            else:
                return int(self.time_division.pps * self.secs)
        elif self.secs == 0:
            return 0
        else:
            return None

    @ticks.setter
    def ticks(self, value):
        if self.tempo != None and self.time_division != None:
            if self.time_division.mode == 'ppqn':
                self.secs = value / self.time_division.ppqn / self.tempo.bps
            else:
                self.secs = value / self.time_division.pps
        elif value == 0:
            self.secs = 0
        else:
            self.secs = None

    def __str__(self):
        return '{secs} s'.format(secs=self.secs)

    def __bytes__(self):
        ticks = self.ticks
        if ticks == None:
            return bytes(1)
        else:
            return _var_int_bytes(ticks)

