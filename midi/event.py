#!/usr/bin/env python3

import collections
from .error import MIDIError
from . import time

class Event(time.Delta):
    def __init__(self, **keywords):
        delta = keywords.get('delta', None)
        time_division = keywords.get('time_division', None)
        tempo = keywords.get('tempo', None)
        super().__init__(delta, time_division, tempo)
    
    @staticmethod
    def parse(source):
        if not isinstance(source, collections.Iterator):
            source = iter(source)
        ticks = io._var_int_parse(source)
        status = next(source)
        if status == 0xff:
            event = MetaEvent._parse(source)
        elif status == 0xf7 or status == 0xf0:
            event = SysExEvent._parse(source, status)
        else:
            event = ChannelEvent._parse(source, status)
        event.ticks = ticks
        return event

