#!/usr/bin/env python3

import numbers
import collections
from .error import MIDIError
from . import time, io

class Event:
    def __init__(self, **keywords):
        delta = keywords.get('delta', None)
        time_division = keywords.get('time_division', None)
        tempo = keywords.get('tempo', None)
        if isinstance(delta, time.Delta):
            self.delta = delta
        else:
            self.delta = time.Delta(delta, time_division, tempo)

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
        event.delta.ticks = ticks
        return event

class ChannelEvent(Event):
    def __init__(self, **keywords):
        super().__init__(**keywords)
        self.channel = keywords.get('channel', None)
    
    @classmethod
    def _parse(cls, source=None, status=None):
        if cls == ChannelEvent:
            channel = status & 0x0f
            type = status & 0xf0
            events = {
                    0x80: NoteOff,
                    0x90: NoteOn,
                    0xa0: NoteAftertouch,
                    0xb0: Controller,
                    0xc0: ProgramChange,
                    0xd0: ChannelAftertouch,
                    0xe0: PitchBend }
            if type not in events:
                raise MIDIError('Encountered an unkown event: {status:X}.'\
                        .format(status=status))
            event = events[type]._parse(source)
            event.channel = channel
            return event
        else:
            return cls(next(source), next(source))

    def __bytes__(self):
        array = bytearray()
        
        statuses = {
                NoteOff: 0x80,
                NoteOn: 0x90,
                NoteAftertouch: 0xa0,
                Controller: 0xb0,
                ProgramChange: 0xc0,
                ChannelAftertouch: 0xd0,
                PitchBend: 0xe0 }

        array.extend(bytes(self.delta))
        array.append(statuses[type(self)] | self.channel)
        array.extend(self._parameters())
        return bytes(array)

class NoteOff(ChannelEvent):
    def __init__(self, note=None, velocity=None, **keywords):
        super().__init__(**keywords)
        self.note = note
        self.velocity = velocity

    def _parameters(self):
        return (self.note, self.velocity)

class NoteOn(ChannelEvent):
    def __init__(self, note=None, velocity=None, **keywords):
        super().__init__(**keywords)
        self.note = note
        self.velocity = velocity

    def _parameters(self):
        return (self.note, self.velocity)

class NoteAftertouch(ChannelEvent):
    def __init__(self, note=None, value=None, **keywords):
        super().__init__(**keywords)
        self.note = note
        self.value = value

    def _parameters(self):
        return (self.note, self.value)

class Controller(ChannelEvent):
    def __init__(self, type=None, value=None, **keywords):
        super().__init__(**keywords)
        self.type = type
        self.value = value

    def _parameters(self):
        return (self.type, self.value)
    
class ProgramChange(ChannelEvent):
    def __init__(self, program=None, **keywords):
        super().__init__(**keywords)
        self.program = program

    @classmethod
    def _parse(cls, source):
        return cls(next(source))

    def _parameters(self):
        return (self.program,)

class ChannelAftertouch(ChannelEvent):
    def __init__(self, amount=None, **keywords):
        super().__init__(**keywords)
        self.amount = amount

    @classmethod
    def _parse(cls, source):
        return cls(next(source))

    def _parameters(self):
        return (self.amount,)

class PitchBend(ChannelEvent):
    def __init__(self, value=None, **keywords):
        super().__init__(**keywords)
        self.value = value

    @classmethod
    def _parse(cls, source):
        value = (next(source) & 0x7f) | ((next(source) & 0x7f) << 7)
        return cls(value)

    def _parameters(self):
        return(self.value & 0x7f, (self.value >> 7) & 0x7f )

class MetaEvent(Event):

    @classmethod
    def _parse(cls, source):
        if cls == MetaEvent:
            type = next(source)

            events = {
                    0x00: SequenceNumber,
                    0x01: Text,
                    0x02: Copyright,
                    0x03: Name,
                    0x04: Instrument,
                    0x05: Lyrics,
                    0x06: Marker,
                    0x07: CuePoint,
                    0x20: ChannelPrefix,
                    0x2f: EndTrack,
                    0x51: SetTempo,
                    0x54: SMPTEOffset,
                    0x58: TimeSignature,
                    0x59: KeySignature,
                    0x7f: ProprietaryEvent }

            return events[type]._parse(source)
        else:
            length = io._var_int_parse(source)
            data = bytearray()
            for i in range(length):
                data.append(next(source))
            return cls(data)

class TextMetaEvent(MetaEvent):
    def __init__(self, source=None, **keywords):
        super().__init__(**keywords)
        try:
            self.text = str(source, 'ascii')
        except TypeError:
            self.text = source

class SequenceNumber(MetaEvent):
    def __init__(self, source=None, **keywords):
        super().__init__(**keywords)
        try:
            self.number = int.from_bytes(source, 'big')
        except TypeError:
            self.number = source

class Text(TextMetaEvent):
    pass

class Copyright(TextMetaEvent):
    pass

class Name(TextMetaEvent):
    pass

class Instrument(TextMetaEvent):
    pass

class Lyrics(TextMetaEvent):
    pass

class Marker(TextMetaEvent):
    pass

class CuePoint(TextMetaEvent):
    pass

class ChannelPrefix(MetaEvent):
    def __init__(self, source=None, **keywords):
        super().__init__(**keywords)
        try:
            self.channel = int.from_bytes(source, 'big')
        except TypeError:
            self.channel = source

class EndTrack(MetaEvent):
    def __init__(self, source=None, **keywords):
        super().__init__(**keywords)

class SetTempo(MetaEvent):
    def __init__(self, source=None, **keywords):
        super().__init(**keywords)
        try:
            mpqn = int.from_bytes(source, 'big')
        except TypeError:
            mpqn = source
        if isinstance(mpqn, numbers.Number):
            self.tempo = Tempo(mpqn=mpqn)
        else:
            self.tempo = None

class SMPTEOffset(MetaEvent):
    def __init__(self, source=None, **keywords):
        super().__init__(**keywords)
        self.data = source

class TimeSignature(MetaEvent):
    def __init__(self, source=None, **keywords):
        super().__init__(**keywords)
        self.data = source

class KeySignature(MetaEvent):
    def __init__(self, source=None, **keywords):
        super().__init__(**keywords)
        self.data = source

class ProprietaryEvent(MetaEvent):
    def __init__(self, source=None, **keywords):
        super().__init__(**keywords)
        self.data = source

class SysExEvent(Event):
    pass
