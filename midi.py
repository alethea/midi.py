#!/usr/bin/env python3

import io
import binascii
import collections
import numbers

class Event:
    def __init__(self, **keywords):
        delta = keywords.get('delta', None)
        time_division = keywords.get('time_division', None)
        tempo = keywords.get('tempo', None)
        if isinstance(delta, Delta):
            self.delta = delta
        else:
            self.delta = Delta(delta, time_division, tempo)

    @staticmethod
    def parse(source):
        if not isinstance(source, collections.Iterator):
            source = iter(source)
        ticks = _var_int_parse(source)
        status = next(source)
        if status == 0xff:
            event = MetaEvent._parse(source)
        elif status == 0xf7 or status == 0xf0:
            event = SysExEvent._parse(source, status)
        else:
            event = ChannelEvent._parse(source, status)
        event.delta.ticks = ticks
        return event

    def __str__(self):
        return repr(self)

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

    def __repr__(self):
        parameters = self._parameters()
        if len(parameters) == 1:
            return '{name}({value})'.format(
                    name=type(self).__name__, value=parameters[0])
        else:
            return '{name}{parameters}'.format(
                    name=type(self).__name__, parameters=tuple(parameters))

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
            length = _var_int_parse(source)
            data = bytearray()
            for i in range(length):
                data.append(next(source))
            return cls(data)

    def __repr__(self):
        return '{name}({data!r})'.format(
                name=type(self).__name__, data=self._bytes())

    def __bytes__(self):
        array = bytearray()
        data = self._bytes()

        types = {
                SequenceNumber: 0x00,
                Text: 0x01,
                Copyright: 0x02,
                Name: 0x03,
                Instrument: 0x04,
                Lyrics: 0x05,
                Marker: 0x06,
                CuePoint: 0x07,
                ChannelPrefix: 0x20,
                EndTrack: 0x2f,
                SetTempo: 0x51,
                SMPTEOffset: 0x54,
                TimeSignature: 0x58,
                KeySignature: 0x59,
                ProprietaryEvent: 0x7f }

        array.extend(bytes(self.delta))
        array.append(0xff)
        array.append(types[type(self)])
        array.extend(_var_int_bytes(len(data)))
        array.extend(data)
        return bytes(array)

class TextMetaEvent(MetaEvent):
    def __init__(self, source=None, **keywords):
        super().__init__(**keywords)
        try:
            self.text = str(source, 'ascii')
        except TypeError:
            self.text = source

    def __repr__(self):
        return '{name}({text!r})'.format(
                name=type(self).__name__, text=self.text)

    def _bytes(self):
        return self.text.encode('ascii')

class SequenceNumber(MetaEvent):
    def __init__(self, source=None, **keywords):
        super().__init__(**keywords)
        try:
            self.number = int.from_bytes(source, 'big')
        except TypeError:
            self.number = source

    def __repr__(self):
        return '{name}({number})'.format(
                name=type(self).__name__, number=self.number)

    def _bytes(self):
        return self.number.to_bytes(2, 'big')

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

    def __repr__(self):
        return '{name}({channel})'.format(
                name=type(self).__name__, channel=self.channel)

    def _bytes(self):
        return self.channel.to_bytes(1, 'big')

class EndTrack(MetaEvent):
    def __init__(self, source=None, **keywords):
        super().__init__(**keywords)

    def __repr__(self):
        return '{name}()'.format(name=type(self).__name__)

    def _bytes(self):
        return bytes()

class SetTempo(MetaEvent):
    def __init__(self, source=None, **keywords):
        super().__init__(**keywords)
        try:
            mpqn = int.from_bytes(source, 'big')
        except TypeError:
            mpqn = source
        if isinstance(mpqn, numbers.Number):
            self.tempo = Tempo(mpqn=mpqn)
        else:
            self.tempo = source

    def __repr__(self):
        return '{name}({tempo!r})'.format(
                name=type(self).__name__, tempo=self.tempo)

    def _bytes(self):
        return self.tempo.mpqn.to_bytes(3, 'big')

class SMPTEOffset(MetaEvent):
    def __init__(self, source=None, **keywords):
        super().__init__(**keywords)
        self.data = source

    def _bytes(self):
        return self.data

class TimeSignature(MetaEvent):
    def __init__(self, source=None, **keywords):
        super().__init__(**keywords)
        self.data = source

    def _bytes(self):
        return self.data

class KeySignature(MetaEvent):
    def __init__(self, source=None, **keywords):
        super().__init__(**keywords)
        self.data = source

    def _bytes(self):
        return self.data

class ProprietaryEvent(MetaEvent):
    def __init__(self, source=None, **keywords):
        super().__init__(**keywords)
        self.data = source

    def _bytes(self):
        return self.data

class SysExEvent(Event):
    pass

class Tempo:
    def __init__(self, source=None, **keywords):
        if source == None:
            self.bpm = keywords.get('bpm', None)
            self.mpqn = keywords.get('mpqn', 500000)
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
        return str(self.bpm)

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
            return str(self.ppqn)
        else:
            return str(self.pps)

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
        self._time_division = time_division
        self._tempo = tempo
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
        return self._secs

    @secs.setter
    def secs(self, value):
        self._secs = value
        self._update_ticks()

    @secs.deleter
    def secs(self):
        del self._secs

    @property
    def tempo(self):
        return self._tempo

    @tempo.setter
    def tempo(self, value):
        self._tempo = value
        self._update_ticks()

    @tempo.deleter
    def tempo(self):
        del self._tempo

    @property
    def time_division(self):
        return self._time_division

    @time_division.setter
    def time_division(self, value):
        self._time_division = value
        self._update_ticks()

    @time_division.deleter
    def time_division(self):
        del self._time_division

    def _update_ticks(self):
        if self._secs != None and self._time_division != None:
            if self._time_division.mode == 'ppqn':
                if self._tempo != None:
                    self._ticks = int(self._secs * self._tempo.bps *
                            self._time_division.ppqn)
            else:
                self._ticks = int(self._secs * self._time_division.pps)
        elif self._secs == 0:
            self._ticks = 0
        elif self._ticks != None and self._secs == None:
            self._update_secs()

    def _update_secs(self):
        if self._ticks != None and self._time_division != None:
            if self._time_division.mode == 'ppqn':
                if self._tempo != None:
                    self._secs = self._ticks / self._time_division.ppqn / \
                            self._tempo.bps
            else:
                self._secs = self._ticks / self._time_division.pps
        elif self._ticks == 0:
            self._secs = 0
        elif self._secs != None and self._ticks == None:
            self._update_ticks()

    def __str__(self):
        return str(self.ticks)

    def __repr__(self):
        return 'Delta({ticks})'.format(ticks=self.ticks)

    def __bytes__(self):
        ticks = self.ticks
        if ticks == None:
            return bytes(1)
        else:
            return _var_int_bytes(ticks)

class Sequence(list):
    def __init__(self, header=None, tracks=list()):
        super().__init__(tracks)
        self.header=header

    @staticmethod
    def parse(source):
        sequence = Sequence()
        if not isinstance(source, collections.Iterator):
            source = iter(source)
        chunk = Chunk.parse(source, id='MThd')
        sequence.header = Header.parse(chunk)
        for i in range(sequence.header.tracks):
            chunk = Chunk.parse(source)
            if chunk.id == 'MTrk':
                track = Track.parse(chunk)
                sequence.append(track)
        return sequence

    def __bytes__(self):
        array = bytearray()
        chunk = Chunk('MThd', bytes(self.header))
        array.extend(bytes(chunk))
        for track in self:
            chunk = Chunk('MTrk', bytes(track))
            array.extend(bytes(chunk))
        return bytes(array)

class Track(list):

    @staticmethod
    def parse(source):
        track = Track()
        if not isinstance(source, collections.Iterator):
            source = iter(source)
        while True:
            item = Event.parse(source)
            if isinstance(item, EndTrack):
                break
            track.append(item)
        return track

    def abs(self, event):
        time = 0
        if isinstance(event, numbers.Number):
            for i in range(event + 1):
                time = time + self[i].delta.ticks
        else:
            for item in self:
                time = time + item.delta.ticks
                if item is event:
                    break
        return time

    def slice(self, start, end=None):
        if end == None:
            end = start
            start = 0
        track = Track()
        time = 0
        for event in self:
            time = time + event.delta.ticks
            if time >= end:
                break
            if time >= start:
                track.append(event)
        return track

    def __bytes__(self):
        array = bytearray()
        for item in self:
            array.extend(bytes(item))
        end_track = EndTrack()
        end_track.delta.ticks = 0
        array.extend(bytes(end_track))
        return bytes(array)

class Header:
    def __init__(self, format=None, tracks=None, time_division=None):
        self.format = format
        self.tracks = tracks
        self.time_division = time_division

    @staticmethod
    def parse(source):
        header = Header()
        if not isinstance(source, collections.Iterator):
            source = iter(source)
        array = bytearray()
        for i in range(6):
            array.append(next(source))
        header.format = int.from_bytes(array[0:2], 'big')
        header.tracks = int.from_bytes(array[2:4], 'big')
        header.time_division = TimeDivision(array[4:6])
        return header

    def __bytes__(self):
        array = bytearray()
        array.extend(self.format.to_bytes(2, 'big'))
        array.extend(self.tracks.to_bytes(2, 'big'))
        array.extend(bytes(self.time_division))
        return bytes(array)

class Chunk(bytearray):
    def __init__(self, id=None, data=bytearray()):
        super().__init__(data)
        self.id = id

    @staticmethod
    def parse(source, id=None):
        chunk = Chunk()
        if not isinstance(source, collections.Iterator):
            source = iter(source)
        length = 8
        mode = 'id'
        while True:
            item = next(source)
            if isinstance(item, int):
                chunk.append(item)
            else:
                chunk.extend(item)

            if mode == 'data' and len(chunk) >= length:
                del chunk[length:] 
                del chunk[:8]
                break
            elif mode == 'len' and len(chunk) >= 8:
                length = int.from_bytes(chunk[4:8], 'big') + 8
                mode = 'data'
            elif mode == 'id' and len(chunk) >= 4:
                chunk.id = chunk[0:4].decode('ascii')
                if id and id != chunk.id:
                    raise MIDIError('{id} chunk not found.'.format(id=id))
                mode = 'len'
        else:
            raise MIDIError('Incompete {id} chunk. Read {got}/{total} bytes.'\
                    .format(got=len(chunk), total=length, id=chunk.id))

        if isinstance(source, io.IOBase):
            source.seek(length + 8 - source.tell(), io.SEEK_CUR)
        return chunk

    @property
    def raw(self):
        value = bytearray(self.id, 'ascii')
        value.extend(len(self).to_bytes(4, 'big'))
        value.extend(self)
        return value
    
    @raw.setter
    def raw(self, value):
        self.id = str(value, 'ascii')
        self[:] = value[8:]

    def __bytes__(self):
        return bytes(self.raw)

    def __str__(self):
        return str(binascii.hexlify(self.raw), 'ascii')

    def __repr__(self):
        return 'Chunk({id}, {data})'.format(id=repr(self.id), 
                data=repr(bytes(self)[8:]))

def _var_int_parse(source):
    value = 0
    if not isinstance(source, collections.Iterator):
        source = iter(source)
    for i in range(4):
        byte = next(source)
        value = (value << 7) | (byte & 0x7f)
        if ~byte & 0x80:
            break
    else:
        raise MIDIError('Incomplete variable length integer.')
    return value

def _var_int_bytes(value):
    array = bytearray()
    for i in range(4):
        array.append((value & 0x7f) | 0x80)
        value = value >> 7
        if value == 0:
            break
    else:
        raise MIDIError('Too long to be a variable length integer.')
    array[0] = array[0] & 0x7f
    array = reversed(array)
    return bytes(array)

class MIDIError(Exception):
    pass

