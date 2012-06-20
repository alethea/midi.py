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

    @bps.setter
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
        elif isinstance(source, numbers.Number):
            self.ppqn = source
        else:
            bits = int.from_bytes(source, 'big')
            if bits & 0x8000:
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
            return '{ppqn} PPQN'.format(ppqn=self.ppqn)
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
        self.tempo = tempo
        self._secs = None
        self._ticks = None
        if source == None:
            self.ticks = None
        elif isinstance(source, numbers.Number):
            self.ticks = source
        else:
            self.ticks = _var_int_parse(source)

    @property
    def ticks(self):
        self._update_ticks()
        return self._ticks

    @ticks.setter
    def ticks(self, value):
        self._ticks = value
        self._update_secs()

    @ticks.deleter
    def ticks(self):
        del self._ticks

    @property
    def secs(self):
        self._update_ticks()
        return self._secs

    @secs.setter
    def secs(self, value):
        self._secs = value
        self._update_ticks()

    @secs.deleter
    def secs(self):
        del self._secs

    def _update_ticks(self):
        if self._secs != None and self.time_division != None:
            if self.time_division.mode == 'ppqn':
                if self.tempo != None:
                    self._ticks = int(self._secs * self.tempo.bps *
                            self.time_division.ppqn)
            else:
                self._ticks = int(self._secs * self.time_division.pps)
        elif self._secs == 0:
            self._ticks = 0
        elif self._ticks != None and self._secs == None:
            self._update_secs()

    def _update_secs(self):
        if self._ticks != None and self.time_division != None:
            if self.time_division.mode == 'ppqn':
                if self.tempo != None:
                    self._secs = self._ticks / self.time_division.ppqn / \
                            self.tempo.bps
            else:
                self._secs = self._ticks / self.time_division.pps
        elif self._ticks == 0:
            self._secs = 0
        elif self._secs != None and self._ticks == None:
            self._update_ticks()

    def __str__(self):
        return '{secs} s'.format(secs=self.secs)

    def __repr__(self):
        return 'Delta({ticks})'.format(ticks=self.ticks)

    def __bytes__(self):
        ticks = self.ticks
        if ticks == None:
            return bytes(1)
        else:
            return _var_int_bytes(ticks)

