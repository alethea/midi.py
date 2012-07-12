#!/usr/bin/env python3

import io
import binascii
import collections
import numbers
import copy
import math

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
        return round(60000000 // self.bpm)

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
        return '{bpm} BPM'.format(bpm=round(self.bpm))

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
            return ('TimeDivision(frames={frames}, subframes={subframes})'
                    .format(frames=self.frames, subframes=self.subframes))

    def __bytes__(self):
        if self.mode == 'ppqn':
            return self.ppqn.to_bytes(2, 'big')
        else:
            value = 0x8000 | (self._frames << 8) | self._subframes
            return value.to_bytes(2, 'big')

class TimeSignature:
    def __init__(self, numerator=4, denominator=4, metronome=24,
            quarter=8):
        if isinstance(numerator, collections.Iterable):
            source = numerator
            self.numerator = source[0]
            self.denominator = int(2 ** source[1])
            self.metronome = source[2]
            self.quarter = source[3]
        else:
            if numerator == None:
                self.numerator = 4
            else:
                self.numerator = numerator
            self.denominator = denominator
            self.metronome = metronome
            self.quarter = quarter

    def __str__(self):
        return '{numerator}/{denominator}'.format(
                numerator=self.numerator, denominator=self.denominator)

    def __repr__(self):
        return ('TimeSignature({num}, {denom}, {metro}, {quarter})'
                .format(num=self.numerator, denom=self.denominator,
                        metro=self.metronome, quarter=self.quarter))

    def __bytes__(self):
        array = bytearray()
        array.append(self.numerator)
        array.append(int(math.log(self.denominator, 2)))
        array.append(self.metronome)
        array.append(self.quarter)
        return bytes(array)

class Program:
    def __init__(self, source=None):
        if source == None:
            self.number = 1
        elif isinstance(source, numbers.Number):
            self.number = int(source)
        elif isinstance(source, str):
            self.number = Program._lower_numbers.get(source.lower(), None)
            if self.number == None:
                self.number = Progam._desc_numbers.get(sources, None)
        else:
            self.number = int.from_bytes(source, 'big') + 1

    @property
    def name(self):
        return Program._names.get(self.number, None)

    @property
    def desc(self):
        return Program._descs.get(self.number, None)

    def __str__(self):
        return Program._descs.get(self.number, '')

    def __repr__(self):
        return 'Program({name!r})'.format(name=self.name)

    def __bytes__(self):
        return (self.number - 1).to_bytes(1, 'big')

class Delta:
    def __init__(self, source=None, division=None, tempo=None, 
            signature=None):
        self._division = division
        self._old_division = division
        self._tempo = tempo
        self._old_tempo = tempo
        self._ticks = None
        self.signature = signature
        if source == None:
            self.ticks = 0
        elif isinstance(source, numbers.Number):
            self.ticks = source
        elif isinstance(source, Delta):
            self._division = source._division
            self._tempo = source._tempo
            if isinstance(source, Time):
                self.signature = source._signature
                self._ticks = source._total_ticks()
            else:
                source._update_division()
                source._update_tempo()
                self.signature = source.signature
                self._ticks = source._ticks
        else:
            self.ticks = _var_int_parse(source)
        self._update_tempo()
        self._update_division()

    @property
    def ticks(self):
        self._update_division()
        self._update_tempo()
        return round(self._ticks)

    @ticks.setter
    def ticks(self, value):
        self._ticks = value

    @ticks.deleter
    def ticks(self):
        del self._ticks

    @property
    def secs(self):
        if self._division != None:
            if self._division.mode == 'ppqn':
                if self._tempo != None:
                    return self.ticks / self._division.ppqn / self._tempo.bps
            else:
                return self.ticks / self._division.pps
        return None

    @secs.setter
    def secs(self, value):
        if self._division != None:
            if self._division.mode == 'ppqn':
                if self._tempo != None:
                    self.ticks = self._division.ppqn * self._tempo.bps * value
            else:
                self.ticks = self._division.pps * value

    @property
    def division(self):
        return self._division

    @division.setter
    def division(self, value):
        self._division = value
        self._update_division()

    @division.deleter
    def division(self):
        del self._division
        del self._old_division

    @property
    def tempo(self):
        return self._tempo

    @tempo.setter
    def tempo(self, value):
        self._tempo = value
        self._update_tempo()

    @tempo.deleter
    def tempo(self):
        del self._tempo
        del self._old_tempo

    def _update_division(self):
        if self._division != None and self._ticks != None:
            if self._old_division != None:
                if self._division.mode == self._old_division.mode:
                    if self._division.mode == 'ppqn':
                        ratio = self._division.ppqn / self._old_division.ppqn
                    else:
                        ratio = self._division.pps / self._old_division.pps
                    self._ticks *= ratio
                elif self._tempo != None:
                    if self._division.mode == 'ppqn':
                        ratio = (self._division.ppqn /
                                (self._old_division.pps / self._tempo.bps))
                    else:
                        ratio = (self._division.pps /
                                (self._tempo.bps / self._old_division.ppqn))
                    self._ticks *= ratio
            self._old_division = copy.deepcopy(self._division)

    def _update_tempo(self):
        if self._tempo != None and self._ticks != None:
            if (self._old_tempo != None and self._division != None and 
                    self._division.mode == 'pps'):
                self._ticks *= self._tempo.bpm / self._old_tempo.bpm
            self._old_tempo = copy.deepcopy(self._tempo)
    
    def __add__(self, other):
        try:
            delta = self._prepare_operator(other)
        except AttributeError:
            return NotImplemented
        delta._ticks = self._ticks + delta._ticks
        return delta

    def __sub__(self, other):
        try:
            delta = self._prepare_operator(other)
        except AttributeError:
            return NotImplemented
        delta._ticks = self._ticks - delta._ticks
        return delta

    def __lt__(self, other):
        try:
            delta = self._prepare_operator(other)
        except AttributeError:
            return NotImplemented
        return round(self._ticks) < round(delta._ticks)

    def __le__(self, other):
        try:
            delta = self._prepare_operator(other)
        except AttributeError:
            return NotImplemented
        return round(self._ticks) <= round(delta._ticks)

    def __eq__(self, other):
        if other == None:
            return False
        try:
            delta = self._prepare_operator(other)
        except AttributeError:
            return NotImplemented
        return round(self._ticks) == round(delta._ticks)

    def __ne__(self, other):
        if other == None:
            return True
        try:
            delta = self._prepare_operator(other)
        except AttributeError:
            return NotImplemented
        return round(self._ticks) != round(delta._ticks)

    def __gt__(self, other):
        try:
            delta = self._prepare_operator(other)
        except AttributeError:
            return NotImplemented
        return round(self._ticks) > round(delta._ticks)

    def __ge__(self, other):
        try:
            delta = self._prepare_operator(other)
        except AttributeError:
            return NotImplemented
        return round(self._ticks) >= round(delta._ticks)

    def _prepare_operator(self, other):
        self._update_division()
        self._update_tempo()
        delta = Delta(other)
        delta.division = self._division
        delta.tempo = self._tempo
        return delta

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

class Time(Delta):
    def __init__(self, source=None, **keywords):
        division = keywords.get('division', TimeDivision(480))
        tempo = keywords.get('tempo', None)
        signature = keywords.get('signature', None)
        self._division = division
        self._old_division = division
        self._tempo = tempo
        self._old_tempo = tempo
        self._ticks = None
        if isinstance(source, collections.Iterable):
            if isinstance(source, str):
                source = source.split('|')
            self._bars = int(source[0]) - 1
            self._beats = int(source[1]) - 1
            self._ticks = int(source[2])
        elif isinstance(source, Delta):
            self._tempo = source.tempo
            self._old_division = source.division
            if isinstance(source, Time):
                signature = source._signature
                source._update_signature()
                self._bars = source._bars
                self._beats = source._beats
            else:
                signature = source.signature
                self._bars = 0
                self._beats = 0
            self._ticks = source._ticks
        else:
            self._bars = keywords.get('bars', 0)
            self._beats = keywords.get('beats', 0)
            self._ticks = keywords.get('ticks', 0)
        self._division = division
        self._signature = signature
        self._update_division()
        self._update_tempo()
        self._update_signature()
    
    @property
    def bars(self):
        self._update_signature()
        return self._bars + 1

    @bars.setter
    def bars(self, value):
        self._bars = value - 1
        self._update_signature()

    @bars.deleter
    def bars(self):
        del self._bars

    @property
    def beats(self):
        self._update_signature()
        return self._beats + 1

    @beats.setter
    def beats(self, value):
        self._beats = value -1
        self._update_signature()

    @beats.deleter
    def beats(self):
        del self._beats

    @property
    def ticks(self):
        self._update_division()
        self._update_tempo()
        self._update_signature()
        return round(self._ticks)

    @ticks.setter
    def ticks(self, value):
        self._ticks = value
        self._update_signature()

    @ticks.deleter
    def ticks(self):
        del self._ticks

    @property
    def signature(self):
        return self._signature

    @signature.setter
    def signature(self, value):
        self._signature = value
        self._update_signature()

    @signature.deleter
    def signature(self):
        del self._signature

    def _total_ticks(self):
        self._update_division()
        self._update_tempo()
        self._update_signature()
        if (self._tempo != None and self._signature != None and 
                self._division != None):
            if self._division.mode == 'ppqn':
                ppqn = self._division.ppqn
            else:
                ppqn = self._division.pps / self._tempo.bps
            ppb = 4 / self._signature.denominator * ppqn
            beats = self._beats
            beats += self._bars * self._signature.numerator
            ticks = self._ticks
            ticks += beats * ppb
            return ticks
        else:
            return None

    def _update_signature(self):
        if (self._tempo != None and self._signature != None and 
                self._division != None):
            if self._division.mode == 'ppqn':
                ppqn = self._division.ppqn
            else:
                ppqn = self._division.pps / self._tempo.bps
            ppb = 4 / self._signature.denominator * ppqn
            self._beats += math.floor(self._ticks / ppb)
            self._ticks = self._ticks % ppb
            self._bars += self._beats // self._signature.numerator
            self._beats = self._beats % self._signature.numerator
    
    def __add__(self, other):
        try:
            time = self._prepare_operator(other)
        except AttributeError:
            return NotImplemented
        time._bars += self._bars
        time._beats += self._beats
        time._ticks += self._ticks
        time._update_signature()
        return time

    def __sub__(self, other):
        try:
            time = self._prepare_operator(other)
        except AttributeError:
            return NotImplemented
        time._bars = self._bars - time._bars
        time._beats = self._beats - time._beats
        time._ticks = self._ticks - time._ticks
        time._update_signature()
        return time

    def __lt__(self, other):
        try:
            time = self._prepare_operator(other)
        except AttributeError:
            return NotImplemented
        if self._bars < time._bars:
            return True
        elif self._bars == time._bars:
            if self._beats < time._beats:
                return True
            elif self._beats == time._beats:
                if round(self._ticks) < round(time._ticks):
                    return True
        return False

    def __le__(self, other):
        try:
            time = self._prepare_operator(other)
        except AttributeError:
            return NotImplemented
        if self._bars < time._bars:
            return True
        elif self._bars == time._bars:
            if self._beats < time._beats:
                return True
            elif self._beats == time._beats:
                if round(self._ticks) <= round(time._ticks):
                    return True
        return False

    def __eq__(self, other):
        if other == None:
            return False
        try:
            time = self._prepare_operator(other)
        except AttributeError:
            return NotImplemented
        return (self._bars == time._bars and
                self._beats == time._beats and
                round(self._ticks) == round(time._ticks))

    def __ne__(self, other):
        if other == None:
            return True
        try:
            time = self._prepare_operator(other)
        except AttributeError:
            return NotImplemented
        return (self._bars != time._bars or
                self._beats != time._beats or
                round(self._ticks) != round(time._ticks))

    def __gt__(self, other):
        try:
            time = self._prepare_operator(other)
        except AttributeError:
            return NotImplemented
        if self._bars > time._bars:
            return True
        elif self._bars == time._bars:
            if self._beats > time._beats:
                return True
            elif self._beats == time._beats:
                if round(self._ticks) > round(time._ticks):
                    return True
        return False

    def __ge__(self, other):
        try:
            time = self._prepare_operator(other)
        except AttributeError:
            return NotImplemented
        if self._bars > time._bars:
            return True
        elif self._bars == time._bars:
            if self._beats > time._beats:
                return True
            elif self._beats == time._beats:
                if round(self._ticks) >= round(time._ticks):
                    return True
        return False

    def _prepare_operator(self, other):
        self._update_division()
        self._update_tempo()
        self._update_signature()
        time = Time(other)
        time.division = self._division
        return time

    def __str__(self):
        return '{bars}|{beats}|{ticks}'.format(bars=self.bars,
                beats=self.beats, ticks=self.ticks)

    def __repr__(self):
        return '{name}(({bars}, {beats}, {ticks}))'.format(
                name=type(self).__name__, bars=self.bars, beats=self.beats,
                ticks=self.ticks)


class Event(Delta):
    def __init__(self, **keywords):
        super().__init__(**keywords)
        self.time = None

    @staticmethod
    def parse(source):
        if not isinstance(source, collections.Iterator):
            source = iter(source)
        ticks = _var_int_parse(source)
        status = next(source)
        if status == MetaEvent.status:
            event = MetaEvent._parse(source)
        elif status == 0xf7 or status == 0xf0:
            event = SysExEvent._parse(source, status)
        else:
            event = ChannelEvent._parse(source, status)
        event.ticks = ticks
        return event

    def __str__(self):
        return type(self).__name__

class ChannelEvent(Event):
    def __init__(self, **keywords):
        super().__init__(**keywords)
        self.channel = keywords.get('channel', None)
    
    @classmethod
    def _parse(cls, source=None, status=None):
        if cls == ChannelEvent:
            channel = status & 0x0f
            type = status & 0xf0
            if type not in ChannelEvent._events:
                raise MIDIError(
                        'Encountered an unkown event: {status:X}.'.format(
                        status=status))
            event = ChannelEvent._events[type]._parse(source)
            event.channel = channel
            return event
        else:
            return cls(next(source), next(source))

    @property
    def type(self):
        return ChannelEvent._types[type(self)]

    @property
    def status(self):
        return self.type | self.channel

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
        array.extend(Delta.__bytes__(self))
        array.append(self.status)
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
    def __init__(self, controller=None, value=None, **keywords):
        super().__init__(**keywords)
        self.controller = controller
        self.value = value

    def _parameters(self):
        return (self.controller, self.value)
    
class ProgramChange(ChannelEvent):
    def __init__(self, program=None, **keywords):
        super().__init__(**keywords)
        self.program = Program(program + 1)

    @classmethod
    def _parse(cls, source):
        return cls(next(source))

    def _parameters(self):
        return (self.program.number - 1,)

    def __repr__(self):
        return '{type}({program!r})'.format(type=type(self).__name__, 
                program=self.program)


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
            return cls._events[type]._parse(source)
        else:
            length = _var_int_parse(source)
            data = bytearray()
            for i in range(length):
                data.append(next(source))
            return cls(data)
    
    status = 0xff

    @property
    def type(self):
        return MetaEvent._types[type(self)]

    def __repr__(self):
        return '{name}({data!r})'.format(
                name=type(self).__name__, data=self._bytes())

    def __bytes__(self):
        array = bytearray()
        data = self._bytes()
        array.extend(Delta.__bytes__(self))
        array.append(self.status)
        array.append(self.type)
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

class SetTimeSignature(MetaEvent):
    def __init__(self, source=None, **keywords):
        super().__init__(**keywords)
        if isinstance(source, TimeSignature):
            self.signature = source
        else:
            self.signature = TimeSignature(source, **keywords)

    def __repr__(self):
        return '{name}({signature!r})'.format(
                name=type(self).__name__, signature=self.signature)

    def _bytes(self):
        return bytes(self.signature)

class SetKeySignature(MetaEvent):
    def __init__(self, key=None, scale=None, **keywords):
        super().__init__(**keywords)
        if isinstance(key, collections.Iterable):
            self.key = key[0]
            self.scale = key[1]
        else:
            self.key = key
            self.scale = scale
        if self.key > 0x7f:
            self.key = -((self.key ^ 0xff) + 1)

    def __repr__(self):
        return '{name}({key}, {scale})'.format(
                name=type(self).__name__, key=self.key, scale=self.scale)

    def _bytes(self):
        return (self.key.to_bytes(1, 'big', signed=True) +
                self.scale.to_bytes(1, 'big'))

class ProprietaryEvent(MetaEvent):
    def __init__(self, source=None, **keywords):
        super().__init__(**keywords)
        self.data = source

    def _bytes(self):
        return self.data

class SysExEvent(Event):
    pass

class Track(list):
    def __init__(self, events=list(), division=None, tempo=None):
        super().__init__(events)
        self.division = division
        self.tempo = tempo

    @staticmethod
    def parse(source):
        track = Track()
        if not isinstance(source, collections.Iterator):
            source = iter(source)
        while True:
            event = Event.parse(source)
            if isinstance(event, EndTrack):
                break
            track.append(event)
        return track

    def slice(self, start, end=None):
        if end == None:
            end = start
            start = 0
        if start < 0:
            start = len(self) + start
        if end < 0:
            end = len(self) + end
        track = Track()
        time = 0
        for event in self:
            time = time + event.ticks
            if time >= end:
                break
            if time >= start:
                track.append(event)
        return track
    
    def update_times(self):
        time = Time()
        for event in self:
            time += event
            event.time = time

    @property
    def division(self):
        return self._division

    @division.setter
    def division(self, value):
        self._division = value
        for event in self:
            event.division = self._division

    @division.deleter
    def division(self):
        del self._division

    @property
    def tempo(self):
        return self._tempo

    @tempo.setter
    def tempo(self, value):
        self._tempo = value
        for event in self:
            event.tempo = self._tempo

    @tempo.deleter
    def tempo(self):
        del self._tempo

    def __bytes__(self):
        array = bytearray()
        for item in self:
            array.extend(bytes(item))
        end_track = EndTrack()
        end_track.ticks = 0
        array.extend(bytes(end_track))
        return bytes(array)

class Sequence(list):
    def __init__(self, tracks=list(), format=None, division=None):
        super().__init__(tracks)
        self._format = None
        self.format = format
        self.division = division

    @staticmethod
    def parse(source):
        sequence = Sequence()
        if not isinstance(source, collections.Iterator):
            source = iter(source)
        chunk = Chunk.parse(source, id='MThd')
        sequence.format = int.from_bytes(chunk[0:2], 'big')
        tracks = int.from_bytes(chunk[2:4], 'big')
        division = TimeDivision(chunk[4:6])
        for i in range(tracks):
            chunk = Chunk.parse(source)
            if chunk.id == 'MTrk':
                sequence.append(Track.parse(chunk))
        sequence._division = division
        sequence.link()
        for track in sequence:
            track.update_times()
        return sequence

    def link(self):
        tempo = Tempo()
        signature = TimeSignature()
        tracks = list()
        def duration(track):
            return track['duration']
        for track in self:
            tracks.append({
                'duration': 0, 
                'track': iter(track), 
                'next': Event()})
        while len(tracks) > 0:
            track = min(tracks, key=duration)
            track['next'].division = self._division
            if isinstance(track['next'], SetTempo):
                tempo = track['next'].tempo
            else:
                track['next'].tempo = tempo
            if isinstance(track['next'], SetTimeSignature):
                signature = track['next'].signature
            else:
                track['next'].signature = signature
            try:
                event = next(track['track'])
            except StopIteration:
                tracks.remove(track)
            else:
                track['duration'] += event.ticks
                track['next'] = event
    
    @property
    def format(self):
        return self._format

    @format.setter
    def format(self, value):
        if self._format == None or len(self) == 0:
            self._format = value
        elif self._format == 0 and value == 1:
            if len(self) != 1:
                raise MIDIError(
                        'Invalid format 0 sequence, contains {n} tracks.'\
                        .format(n=len(self)))
            self._format = value
            mixed = self.pop()
            ticks = 0
            tracks = list()
            for i in range(2):
                tracks.append([0, Track()])
            for event in mixed:
                ticks += event.ticks
                if isinstance(event, MetaEvent):
                    track = 0
                else:
                    track = 1
                event.ticks = ticks - tracks[track][0]
                tracks[track][1].append(event)
                tracks[track][0] = ticks
            for track in tracks:
                self.append(track[1])
        elif self._format != value:
            raise MIDIError(
                    'Cannot convert a format {0} sequence to format {1}.'\
                    .format(self._format, value))

    @format.deleter
    def format(self):
        del self._format

    @property
    def division(self):
        return self._division

    @division.setter
    def division(self, value):
        self._division = value
        for track in self:
            track.division = self._division

    @division.deleter
    def division(self):
        del self._division

    def __bytes__(self):
        array = bytearray()
        header = bytearray()
        header.extend(self.format.to_bytes(2, 'big'))
        header.extend(len(self).to_bytes(2, 'big'))
        header.extend(bytes(self.division))
        chunk = Chunk('MThd', header)
        array.extend(bytes(chunk))
        for track in self:
            chunk = Chunk('MTrk', bytes(track))
            array.extend(bytes(chunk))
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
            raise MIDIError(
                    'Incompete {id} chunk. Read {got}/{total} bytes.'.format(
                    got=len(chunk), total=length, id=chunk.id))

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

ChannelEvent._events = {
        0x80: NoteOff,
        0x90: NoteOn,
        0xa0: NoteAftertouch,
        0xb0: Controller,
        0xc0: ProgramChange,
        0xd0: ChannelAftertouch,
        0xe0: PitchBend }
ChannelEvent._types = {
        value: key for key, value in ChannelEvent._events.items()}

MetaEvent._events = {
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
        0x58: SetTimeSignature,
        0x59: SetKeySignature,
        0x7f: ProprietaryEvent }
MetaEvent._types = {value: key for key, value in MetaEvent._events.items()}

Program._descs = {
        1: 'Acoustic Grand Piano',
        2: 'Bright Acoustic Piano',
        3: 'Electric Grand Piano',
        4: 'Honky Tonk Piano',
        5: 'Electric Piano 1',
        6: 'Electric Piano 2',
        7: 'Harpsicord',
        8: 'Clavient',
        9: 'Celesta',
        10: 'Glockenspiel',
        11: 'Music Box',
        12: 'Vibraphone',
        13: 'Marimba',
        14: 'Xylophone',
        15: 'Tubular Bells',
        16: 'Dulcimer',
        17: 'Drawbar Organ',
        18: 'Precussive Organ',
        19: 'Rock Organ',
        20: 'Church Organ',
        21: 'Reed Organ',
        22: 'Accordion',
        23: 'Harmonica',
        24: 'Tango Accordion',
        25: 'Acoustic Guitar (Nylon)',
        26: 'Acoustic Guitar (Steel)',
        27: 'Electric Guitar (Jazz)',
        28: 'Electric Guitar (Clean)',
        29: 'Electric Guitar (Muted)',
        30: 'Overdriven Guitar',
        31: 'Distortion Guitat',
        32: 'Guitar Harmonics',
        33: 'Acoustic Bass',
        34: 'Electric Bass (Finger)',
        35: 'Electric Bass (Pick)',
        36: 'Fretless Bass',
        37: 'Slap Bass 1',
        38: 'Slap Bass 2',
        39: 'Synth Bass 1',
        40: 'Synth Bass 2',
        41: 'Violin',
        42: 'Viola',
        43: 'Cello',
        44: 'Contrabass',
        45: 'Tremolo Strings',
        46: 'Pizzicato Strings',
        47: 'Orchestral Harp',
        48: 'Timpani',
        49: 'String Ensemble 1',
        50: 'String Ensemble 2',
        51: 'Synth Strings 1',
        52: 'Synth Strings 2',
        53: 'Choir Aahs',
        54: 'Choir Oohs',
        55: 'Synth Choir',
        56: 'Orchestra Hit',
        57: 'Trumpet',
        58: 'Trombone',
        59: 'Tuba',
        60: 'Muted Trumpet',
        61: 'French Horn',
        62: 'Brass Section',
        63: 'Synth Brass 1',
        64: 'Synth Brass 2',
        65: 'Soprano Sax',
        66: 'Alto Sax',
        67: 'Tenor Sax',
        68: 'Baritone Sax',
        69: 'Oboe',
        70: 'English Horn',
        71: 'Bassoon',
        72: 'Clarinet',
        73: 'Piccolo',
        74: 'Flute',
        75: 'Recorder',
        76: 'Pan Flute',
        77: 'Brown Bottle',
        78: 'Sakuhachi',
        79: 'Whistle',
        80: 'Ocarina',
        81: 'Square Lead',
        82: 'Sawtooth Lead',
        83: 'Calliope Lead',
        84: 'Chiff Lead',
        85: 'Charang Lead',
        86: 'Voice Lead',
        87: 'Fifths Lead',
        88: 'Bass Lead',
        89: 'New Age Pad',
        90: 'Warm Pad',
        91: 'Polysynth Pad',
        92: 'Choir Pad',
        93: 'Bowed Glass Pad',
        94: 'Metallic Pad',
        95: 'Halo Pad',
        96: 'Sweep Pad',
        97: 'Rain',
        98: 'Soundtrack',
        99: 'Crystal',
        100: 'Atmosphere',
        101: 'Brightness',
        102: 'Goblin',
        103: 'Echo',
        104: 'Sci-Fi',
        105: 'Sitar',
        106: 'Banjo',
        107: 'Shamisen',
        108: 'Koto',
        109: 'Kalimba',
        110: 'Bagpipe',
        111: 'Fiddle',
        112: 'Shanai',
        113: 'Tinkle Bell',
        114: 'Agogo',
        115: 'Steel Drums',
        116: 'Woodblock',
        117: 'Taiko Drum',
        118: 'Melodic Tom',
        119: 'Synth Drum',
        120: 'Reverse Cymbal',
        121: 'Guitar Fret Noise',
        122: 'Breath Noise',
        123: 'Seahorse',
        124: 'Bird Tweet',
        125: 'Telephone',
        126: 'Helicopter',
        127: 'Applause',
        128: 'Gunshot'}

Program._names = dict()
for key, value in Program._descs.items():
    Program._names[key] = ''.join(filter(lambda x: x not in ' ()-', value))

Program._desc_numbers = {value: key for key, value in Program._descs.items()}
Program._lower_numbers = {
        value.lower(): key for key, value in Program._names.items()}

