#!/usr/bin/env python3

"""
An object oriented interface to MIDI sequences.

Standard MIDI files store sequences as one or more tracks of MIDI events,
separated by integer relative times. The midi module provides classes for
parsing MIDI files and organizing MIDI events into a chronological sequence
with absolute times accessible through 'bar|beat|tick' notation. This allows
for easy modification of the sequence, and modified sequences can be exported
back to MIDI files.

Some MIDI events, such as SetTempo events, set a flag on future events, until
another event resets it. The midi module uses a simple node map to track these
flags. A setter event creates a flag object and subsequent event objects
contain references to the flag object.
"""

import io
import binascii
import collections
import numbers
import operator
import copy
import math


class Tempo:
    """Stores musical tempo and provides unit conversions."""

    def __init__(self, bpm=120, *, mpqn=None):
        """
        Create a new Tempo object.

        If called without arguments, the tempo defaults to 120 BPM.
        
        Otherwise, if passed a single number, assume it is the tempo in beats
        per minute. If passed a bytes object, assume it is the tempo 
        specification from a MIDI file in microseconds per quarter note.

        Beats per minute or microseconds per quarter note can be set
        explicitly with the bpm and mpqn keywords.
        """
        if isinstance(bpm, numbers.Number):
            self.bpm = bpm
        else:
            self.mpqn = int.from_bytes(bpm, 'big')
        if mpqn != None:
            self.mpqn = mpqn

    @property
    def mpqn(self):
        """The tempo in microseconds per quarter note."""
        return round(60000000 / self.bpm)

    @mpqn.setter
    def mpqn(self, value):
        self.bpm = round(60000000 / value)

    @property
    def bps(self):
        """The tempo in beats per second."""
        return self.bpm / 60

    @bps.setter
    def bps(self, value):
        self.bpm = value * 60

    def _comparison(self, other, comparison):
        if isinstance(other, Tempo):
            return comparison(self.bpm, other.bpm)
        return NotImplemented

    def __lt__(self, other):
        return self._comparison(other, operator.lt)

    def __le__(self, other):
        return self._comparison(other, operator.le)

    def __eq__(self, other):
        return self._comparison(other, operator.eq)

    def __ne__(self, other):
        return self._comparison(other, operator.ne)

    def __ge__(self, other):
        return self._comparison(other, operator.ge)

    def __gt__(self, other):
        return self._comparison(other, operator.gt)

    def __str__(self):
        return '{bpm} BPM'.format(bpm=round(self.bpm))

    def __repr__(self):
        return 'Tempo({bpm})'.format(bpm=self.bpm)

    def __bytes__(self):
        """
        Microseconds per quarter note in 3 bytes, for SetTempo events.
        """
        return self.mpqn.to_bytes(3, 'big')


class TimeDivision:
    """
    Represents the time division field from a MIDI file header.
    
    MIDI files will either express the time division in pulses per quarter
    note (PPQN) or pulses per second (PPS), based on SMPTE subframes. The mode
    attribute will either be 'ppqn' or 'pps'. In PPQN mode, the ppqn attribute
    will be defined. In PPS mode the frames, subframes, and pps attributes
    will be defined.
    """

    def __init__(self, ppqn=None, *, frames=None, subframes=None):
        """
        Creates a new TimeDivision object.

        If passed no arguments, create an empty TimeDivision object. If passed
        one numeric argument, create a PPQN TimeDivision with the specified
        PPQN. Otherwise, if keywords frames and subframes are specified,
        create a PPS TimeDivision.
        """
        self.mode = 'ppqn'
        self.pps = None
        self.ppqn = None
        if ppqn == None:
            self.frames = frames
            self.subframes = subframes
        elif isinstance(ppqn, numbers.Number):
            self.ppqn = ppqn
        else:
            bits = int.from_bytes(ppqn, 'big')
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
        """Return SMPTE frames per second in PPS mode"""
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
        """Return number of subframes per SMPTE frame in PPS mode."""
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
        """A 2 byte integer, suitable for MIDI file headers."""
        if self.mode == 'ppqn':
            return self.ppqn.to_bytes(2, 'big')
        else:
            value = 0x8000 | (self._frames << 8) | self._subframes
            return value.to_bytes(2, 'big')


class TimeSignature:
    """
    Represents a MIDI time signature.
    
    The numerator and denominator of a time signature, e.g.: 4/4, are
    available through the numerator and denominator attributes. 
    
    MIDI time signatures also store metronome information, accessible as
    fractional ticks per beat through the metronome attribute.

    Lastly, MIDI files also store the relationship between 32nd notes and MIDI
    clock ticks to synchronize with a synthesizer. This is not related to the
    file's clock or time division, and is usually 8, since there are usually
    24 clock ticks per quarter note, so 1/32 * 8 = 1/4. This number is
    available through the clock attribute.
    """

    def __init__(self, numerator=4, denominator=4, metronome=1.0, clock=8):
        """
        Create a new TimeSignature object.

        Arguments can be positional or keywords: numerator, denominator, 
        metronome, clock. If not specified defaults to 4, 4, 1.0, 8.

        If given a single bytes-like object, assume it's from the body of a
        SetTimeSignature event and parse it.
        """
        if isinstance(numerator, collections.Iterable):
            source = numerator
            self.numerator = source[0]
            self.denominator = int(2 ** source[1])
            self.metronome = source[2] / 24
            self.clock = source[3]
        else:
            self.numerator = numerator
            self.denominator = denominator
            self.metronome = metronome
            self.clock = clock
    
    def __eq__(self, other):
        if isinstance(other, TimeSignature):
            return (self.numerator == other.numerator and
                    self.denominator == other.denominator and
                    self.metronome == other.metronome and
                    self.clock == other.clock)
        return NotImplemented

    def __ne__(self, other):
        if isinstance(other, TimeSignature):
            return (self.numerator != other.numerator or
                    self.denominator != other.denominator or
                    self.metronome != other.metronome or
                    self.clock != other.clock)
        return NotImplemented

    def __str__(self):
        return '{numerator}/{denominator}'.format(
                numerator=self.numerator, denominator=self.denominator)

    def __repr__(self):
        return ('TimeSignature({num}, {denom}, {metro}, {clock})'
                .format(num=self.numerator, denom=self.denominator,
                        metro=self.metronome, clock=self.clock))

    def __bytes__(self):
        """4 bytes, suitable for the body of a SetTimeSignature event."""
        array = bytearray()
        array.append(self.numerator)
        array.append(round(math.log(self.denominator, 2)))
        array.append(round(self.metronome * 24))
        array.append(self.clock)
        return bytes(array)


class Program:
    """
    Represents a MIDI program.

    MIDI stores instrument information as a number 1-128. There is a standard
    set of instruments, but synthesizers may implement their own set. The
    descriptive name of the instrument, e.g.: 'Acoustic Grand Piano', is 
    accessible from the desc attribute. A unique string describing the 
    instrument, e.g.: 'AcousticGrandPiano', is accessible by the name
    attribute. Lists of valid strings are available through the names and
    descs attributes.
    """

    def __init__(self, source=None):
        """
        Create a new Program object.

        Can be initialized from an integer program number, a program byte from
        a MIDI file, a name string (in any capitalization scheme), or a 
        description string.
        """
        if source == None:
            self.number = 1
        elif isinstance(source, numbers.Number):
            self.number = int(source)
        elif isinstance(source, str):
            self.number = Program._lower_numbers.get(source.lower(), None)
            if self.number == None:
                self.number = Program._desc_numbers.get(source, None)
        else:
            self.number = int.from_bytes(source, 'big') + 1
        if self.number == None or self.number < 1 or self.number > 128:
            raise MIDIError('MIDI Program \'{source}\' is undefined.'.format(
                source=source))

    @property
    def name(self):
        """The string identifying the program."""
        return Program._names.get(self.number, None)

    @name.setter
    def name(self, value):
        self.number = Program._lower_numbers.get(value.lower(), 1)

    @property
    def desc(self):
        """The descriptive name of the program."""
        return Program._descs.get(self.number, None)

    @desc.setter
    def desc(self, value):
        self.number = Program._desc_numbers.get(value, 1)

    def _comparison(self, other, comparison):
        if isinstance(other, Program):
            return comparison(self.number, other.number)
        return NotImplemented

    def __eq__(self, other):
        return self._comparison(other, operator.eq)

    def __ne__(self, other):
        return self._comparison(other, operator.ne)

    def __str__(self):
        return Program._descs.get(self.number, '')

    def __repr__(self):
        return 'Program({name!r})'.format(name=self.name)

    def __bytes__(self):
        """Single byte integer of the program number."""
        return (self.number - 1).to_bytes(1, 'big')


class Time:
    def __init__(self, value=0, *, specification=None):
        self._node = None
        self._cumulative = None
        self._value = value
        self.specification = specification

    vpt = 16
    vpqn = vpt * 480
    vpn = vpqn * 4

    @property
    def value(self):
        if self._value == 0 and self._cumulative != None:
            self.cumulative = self._cumulative
        return self._value

    @value.setter
    def value(self, value):
        self._value = value

    @property
    def bar(self):
        node = self.node
        if node == None:
            return None
        value = self.value - node.value
        npm = node.signature.numerator / node.signature.denominator
        return math.floor(value / (self.vpn * npm)) + node.bar

    @bar.setter
    def bar(self, bar):
        self._node = self._node_error('bar')
        self.triple = (bar, self.beat, self.tick)
        self._node = None

    @property
    def beat(self):
        node = self.node
        if node == None:
            return None
        value = self.value - node.value
        vpm = self.vpn * node.signature.numerator / node.signature.denominator
        vpb = self.vpn / node.signature.denominator
        return math.floor((value % vpm) / vpb) + node.beat

    @beat.setter
    def beat(self, beat):
        self._node = self._node_error('beat')
        self.triple = (self.bar, beat, self.tick)
        self._node = None

    @property
    def tick(self):
        node = self.node
        if node == None:
            return None
        value = self.value - node.value
        mod = value % (self.vpn / node.signature.denominator)
        return round(mod / self.vpt) + node.tick

    @tick.setter
    def tick(self, tick):
        self._node = self._node_error('tick')
        self.triple = (self.bar, self.beat, tick)
        self._node = None

    @property
    def cumulative(self):
        node = self.node
        if node == None:
            return self._cumulative
        value = self.value - node.value
        return round(value / node.vpp + node.cumulative)

    @cumulative.setter
    def cumulative(self, cumulative):
        if self.specification == None:
            self._cumulative = cumulative
            return
        node = self.specification.cumulative(cumulative)
        if node == None:
            self._cumulative = cumulative
            return
        self._cumulative = None
        self._value = node.value 
        self._value += round((cumulative - node.cumulative) * node.vpp)

    @property
    def triple(self):
        self._node = self.specification.time(self)
        triple_tuple = (self.bar, self.beat, self.tick)
        self._node = None
        return triple_tuple

    @triple.setter
    def triple(self, value):
        bar, beat, tick = value
        error = 'Triple out of range: {bar}|{beat}|{tick:03}.'.format(
                bar=bar, beat=beat, tick=tick)
        if bar < 1 or beat < 1 or tick < 0:
            raise MIDIError(error)
        if self.specification == None:
            raise MIDIError('Cannot set triple without a time specification.')
        node = self.specification.triple(value)
        if beat > node.signature.numerator:
            raise MIDIError(error)
        if tick >= 1920 / node.signature.denominator:
            raise MIDIError(error)
        npm = self.vpn * node.signature.numerator / node.signature.denominator
        vpb = self.vpn / node.signature.denominator
        self._value = node.value
        self._value += round((bar - node.bar) * vpm)
        self._value += round((beat - node.beat) * vpb)
        self._value += (tick - node.tick) * self.vpt

    @property
    def node(self):
        if self._node != None:
            return self._node
        if self.specification == None:
            return None
        return self.specification.time(self)

    def _node_error(self, attribute):
        node = self.node
        if node != None:
            return node
        raise MIDIError(
                'Cannot set {attribute} without a time specification.'.format(
                attribute=attribute))

    def _comparison(self, other, comparison):
        if isinstance(other, Time):
            return comparison(self.value, other.value)
        elif isinstance(other, collections.Iterable):
            if len(other) == 3:
                for item in other:
                    if not isinstance(other, numbers.Number):
                        return NotImplemented
                time = Time(specification=self.specification)
                time.triple = other
                return comparison(self.value, time.value)
        return NotImplemented
    
    def _operation(self, other, operation):
        time = Time(specification=self.specification)
        if isinstance(other, Time):
            time.value = operation(self.value, other.value)
        elif isinstance(other, collections.Iterable):
            if len(other) == 3:
                for item in other:
                    if not isinstance(other, numbers.Number):
                        return NotImplemented
                time.triple = other
                time.value = operation(self.value, other.value)
        else:
            return NotImplemented
        return time
    
    def __lt__(self, other):
        return self._comparison(other, operator.lt)

    def __le__(self, other):
        return self._comparison(other, operator.le)

    def __eq__(self, other):
        return self._comparison(other, operator.eq)

    def __ne__(self, other):
        return self._comparison(other, operator.ne)

    def __ge__(self, other):
        return self._comparison(other, operator.ge)

    def __gt__(self, other):
        return self._comparison(other, operator.gt)

    def __add__(self, other):
        return self._operation(other, operator.add)

    def __sub__(self, other):
        return self._operation(other, operator.sub)

    def __repr__(self):
        return 'Time({value})'.format(value=self.value)

    def __str__(self):
        self._node = self.specification.time(self)
        string = '{bar}|{beat}|{tick:03}'.format(bar=self.bar,
                beat=self.beat, tick=self.tick)
        self._node = None
        return string

class TimeNode:
    def __init__(self, value=0, *, bar=1, beat=1, tick=0, time=None, 
            triple=None, cumulative=0, signature=None, tempo=None,
            specification=None):
        self.specification = specification
        self.value = value
        self.signature = signature
        self.tempo = tempo
        self.bar = bar
        self.beat = beat
        self.tick = tick
        if triple != None:
            self.triple = triple
        self.cumulative = cumulative
        if time != None:
            self.value = time.value
            self.cumulative = time.cumulative
            self.triple = time.triple

    @property
    def triple(self):
        return (self.bar, self.beat, self.tick)

    @triple.setter
    def triple(self, value):
        self.bar, self.beat, self.tick = value

    @property
    def vpp(self):
        if self.specification.division.mode == 'ppqn':
            return Time.vpqn / self.specification.division.ppqn
        else:
            return Time.vpqn / (self.specification.division.pps / 
                    self.tempo.bps)

    def __repr__(self):
        return 'TimeNode({value})'.format(value=self.value)


class TimeSpecification(list):
    def __init__(self, *, division=None, sequence=None):
        super().__init__()
        self._division = division
        self.sequence = sequence
        self._default_tempo = Tempo()
        self._default_signature = TimeSignature()
    
    @property
    def division(self):
        if self.sequence == None:
            return self._division
        else:
            return self.sequence.division

    @division.setter
    def division(self, value):
        self._division = value

    def update(self, events=list()):
        if len(events) < 1 and self.sequence != None:
            events = self.sequence
        del self[:]
        tempo = self._default_tempo
        signature = self._default_signature
        self.append(TimeNode(tempo=tempo, signature=signature, 
            specification=self))
        for event in events:
            if event.tempo != tempo or event.signature != signature:
                self.append(TimeNode(time=event.time, tempo=event.tempo,
                    signature=event.signature, specification=self))
                tempo = event.tempo
                signature = event.signature

    def events(self, *, track=None):
        events = list()
        for node in self:
            events.append(SetTempo(tempo=node.tempo, signature=node.signature,
                track=track, time=Time(node.value, specification=self)))
            events.append(SetTimeSignature(tempo=node.tempo,
                signature=node.signature, track=track,
                time=Time(node.value, specification=self)))
        return events

    def time(self, value):
        return self._lookup(value.value, 'value')

    def cumulative(self, value):
        return self._lookup(value, 'cumulative')

    def triple(self, iterable):
        bar, beat, tick = iterable
        for node in reversed(self):
            if node.bar < bar:
                return node
            elif node.bar == bar:
                if node.beat < beat:
                    return node
                elif node.beat == beat:
                    if node.tick <= tick:
                        return node
        return None

    def _lookup(self, value, key):
        for node in reversed(self):
            if node.__dict__[key] <= value:
                return node
        return None


class Event:
    """Base class for MIDI events."""

    def __init__(self, *, time=None, track=None, sequence=None, 
            tempo=None, signature=None):
        """
        Create a new Event object.

        Since Event inherits Delta for storing its time information, any
        keyword arguments Delta supports can be passed to the constructor,
        in addition to the time and track keywords.
        """
        if time == None:
            time = Time()
        self.time = time
        self.track = track
        self.sequence = sequence
        self.tempo = tempo
        self.signature = signature

    @staticmethod
    def parse(source):
        """
        Create a new Event object of the appropriate type from a bytes.

        This is the primary method from creating Event objects from a Chunk.
        It will raise a MIDIError if it encounters an unknown or malformed
        event.

        A common method of calling parse is to create an iterator from a Chunk
        and call parse repeatedly.
        """
        if not isinstance(source, collections.Iterator):
            source = iter(source)
        status = next(source)
        if status == MetaEvent.status:
            event = MetaEvent._parse(source)
        elif status == 0xf7 or status == 0xf0:
            event = SysExEvent._parse(source, status)
        else:
            event = ChannelEvent._parse(source, status)
        return event

    def __str__(self):
        return _name_to_desc(type(self).__name__)


class ChannelEvent(Event):
    """
    Base class for channel events.

    Channel events make up the bulk of a MIDI file. Each track has 16 channels
    available for audio events. Channel events contain a track nibble in
    their status byte that dictates what channel the event acts on.
    """

    def __init__(self, **keywords):
        """
        Create a new ChannelEvent object.

        In addition to the keywords inherited from Event, ChannelEvents also
        accept the channel and program keywords.
        """
        self.channel = keywords.pop('channel', None)
        self.program = keywords.pop('program', None)
        super().__init__(**keywords)
    
    @classmethod
    def _parse(cls, source=None, status=None):
        """Delegate parser method. Called by Event.parse."""
        if cls == ChannelEvent:
            channel = status & 0x0f
            type = status & 0xf0
            if type not in ChannelEvent._events:
                raise MIDIError(
                        'Encountered an unknown event: {status:X}.'.format(
                        status=status))
            event = ChannelEvent._events[type]._parse(source)
            event.channel = channel
            return event
        else:
            return cls(next(source), next(source))

    @property
    def type(self):
        """Get the type number 0x80-0x30. Immutable."""
        return ChannelEvent._types[type(self)]

    @property
    def status(self):
        """Get the status byte, type | channel. Immutable."""
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
        """Bytes, including delta time, for writing to a MIDI file."""
        array = bytearray()
        array.append(self.status)
        array.extend(self._parameters())
        return bytes(array)


class NoteOff(ChannelEvent):
    """
    Indicates a key release.
    
    Available attributes are note and velocity.
    """

    def __init__(self, note=None, velocity=None, **keywords):
        """
        Create a NoteOff object. Accepts note and velocity arguments.
        """
        super().__init__(**keywords)
        self.note = note
        self.velocity = velocity

    def _parameters(self):
        return (self.note, self.velocity)


class NoteOn(ChannelEvent):
    """
    Indicates a key press.
    
    Available attributes are note and velocity.
    """

    def __init__(self, note=None, velocity=None, **keywords):
        """
        Create a NoteOn object. Accepts note and velocity arguments.
        """
        super().__init__(**keywords)
        self.note = note
        self.velocity = velocity

    def _parameters(self):
        return (self.note, self.velocity)


class NoteAftertouch(ChannelEvent):
    """
    Indicates a change in pressure on a pressed key.
    
    Available attributes are note and amount.
    """

    def __init__(self, note=None, amount=None, **keywords):
        """
        Create a NoteAftertouch object. Accepts note and amount arguments.
        """
        super().__init__(**keywords)
        self.note = note
        self.amount = amount

    def _parameters(self):
        return (self.note, self.amount)


class ControlChange(ChannelEvent):
    """
    Indicates a change in a controller on a channel.

    Available attributes are controller and value.
    """

    def __init__(self, controller=None, value=None, **keywords):
        """
        Create a ControlChange object. Accepts controller and value arguments.
        """
        super().__init__(**keywords)
        self.controller = controller
        self.value = value

    def _parameters(self):
        return (self.controller, self.value)
    

class ProgramChange(ChannelEvent):
    """
    Indicates a change in the program (instrument) active on a channel.

    The associated Program object can be accessed through the program
    attribute.
    """

    def __init__(self, program=None, **keywords):
        """
        Create a ProgramChange object. 

        Accepts a program number, a Program object, or bytes as an argument.
        """
        super().__init__(**keywords)
        if isinstance(program, Program) or program == None:
            self.program = program
        elif isinstance(program, numbers.Number):
            self.program = Program(program + 1)
        else:
            self.program = Program(program)

    @classmethod
    def _parse(cls, source):
        """Delegate parser method. Called by ChannelEvent._parse."""
        return cls(next(source))

    def _parameters(self):
        return (self.program.number - 1,)

    def __repr__(self):
        return '{type}({program!r})'.format(type=type(self).__name__, 
                program=self.program)


class ChannelAftertouch(ChannelEvent):
    """
    Indicates a change in pressure on all pressed keys in a channel.

    The pressure is accessible by the amount attribute.
    """

    def __init__(self, amount=None, **keywords):
        """Create a ChannelAftertouch object. Accepts an amount argument."""
        super().__init__(**keywords)
        self.amount = amount

    @classmethod
    def _parse(cls, source):
        """Delegate parser method. Called by ChannelEvent._parse."""
        return cls(next(source))

    def _parameters(self):
        return (self.amount,)


class PitchBend(ChannelEvent):
    """
    Indicates a shift in pitch of a channel.

    The value parameter is a floating point number between -1 and 1.
    """

    def __init__(self, value=None, **keywords):
        """Create a PitchBend object. Accepts a value argument."""
        super().__init__(**keywords)
        self.value = value

    @classmethod
    def _parse(cls, source):
        """Delegate parser method. Called by ChannelEvent._parse."""
        value = (next(source) & 0x7f) | ((next(source) & 0x7f) << 7)
        value = (value / 0x2000) - 1
        return cls(value)

    def _parameters(self):
        value = round((self.vale + 1) * 0x2000)
        return (value & 0x7f, (value >> 7) & 0x7f)

    def __repr__(self):
        return '{type}({value})'.format(type=type(self).__name__, 
                vale=self.value)


class MetaEvent(Event):
    """
    Base class for meta events.

    Meta events contain data not sent to a synthesizer, such as text
    descriptions or timing information for the controlling computer. They may
    occur at any point in a file, but are mostly on track 1 of common format 1
    files.
    """

    @classmethod
    def _parse(cls, source):
        """Delegate parser method. Called by Event.parse."""
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
        """Get the meta event's type byte."""
        return MetaEvent._types[type(self)]

    def __repr__(self):
        return '{name}({data!r})'.format(
                name=type(self).__name__, data=self._bytes())

    def __bytes__(self):
        """Bytes, including delta time, for writing to a MIDI file."""
        array = bytearray()
        data = self._bytes()
        array.append(self.status)
        array.append(self.type)
        array.extend(_var_int_bytes(len(data)))
        array.extend(data)
        return bytes(array)


class TextMetaEvent(MetaEvent):
    """
    Base class for meta events with a text payload.

    The text is available through the text attribute. Characters should not
    exceed the ASCII range, but can include ISO 8859-1 characters.
    """

    def __init__(self, text=None, **keywords):
        """Create a TextMetaEvent from a string argument, if present."""
        super().__init__(**keywords)
        try:
            self.text = str(text, 'iso8859-1')
        except TypeError:
            self.text = text

    def __repr__(self):
        return '{name}({text!r})'.format(
                name=type(self).__name__, text=self.text)

    def _bytes(self):
        """Delegate bytes method, called by MetaEvent.__bytes__."""
        return self.text.encode('iso8859-1')


class SequenceNumber(MetaEvent):
    """
    The pattern number of a format 2 track or a format 0 or 1 sequence.
    """

    def __init__(self, number=None, **keywords):
        """Create a SequenceNumber from a numeric argument or bytes."""
        super().__init__(**keywords)
        try:
            self.number = int.from_bytes(number, 'big')
        except TypeError:
            self.number = number

    def __repr__(self):
        return '{name}({number})'.format(
                name=type(self).__name__, number=self.number)

    def _bytes(self):
        """Delegate bytes method, called by MetaEvent.__bytes__."""
        return self.number.to_bytes(2, 'big')


class Text(TextMetaEvent):
    """Arbitrary text for comments or description."""


class Copyright(TextMetaEvent):
    """Stores a copyright notice. Can include '©' (0xa9)."""


class Name(TextMetaEvent):
    """Defines sequence name or a track name."""


class ProgramName(TextMetaEvent):
    """A descriptive string of the instrument being used."""


class Lyrics(TextMetaEvent):
    """Defines lyrics for sheet music or a karaoke system."""


class Marker(TextMetaEvent):
    """Marks a significant point in the sequence."""


class CuePoint(TextMetaEvent):
    """Marks the start of a new sound or action."""


class ChannelPrefix(MetaEvent):
    """
    Indicate that the following meta events affect a specific channel.
    
    Used primarily with ProgramName meta events. The channel is available by
    the channel attribute.
    """

    def __init__(self, channel=None, **keywords):
        """
        Create a ChannelPrefix from an optional number or bytes argument.
        """
        super().__init__(**keywords)
        try:
            self.channel = int.from_bytes(channel, 'big')
        except TypeError:
            self.channel = channel

    def __repr__(self):
        return '{name}({channel})'.format(
                name=type(self).__name__, channel=self.channel)

    def _bytes(self):
        """Delegate bytes method, called by MetaEvent.__bytes__."""
        return self.channel.to_bytes(1, 'big')


class EndTrack(MetaEvent):
    """
    Indicates the end of a track.
    
    Sequence automatically tracks EndTrack events, so most applications will
    never need to interact with them.
    """

    def __init__(self, source=None, **keywords):
        """Create an EndTrack object."""
        super().__init__(**keywords)

    def __repr__(self):
        return '{name}()'.format(name=type(self).__name__)

    def _bytes(self):
        """Delegate bytes method, called by MetaEvent.__bytes__."""
        return bytes()


class SetTempo(MetaEvent):
    """
    Sets the tempo for the sequence until the next SetTempo event.

    The associated Tempo object is accessible from the tempo attribute.
    """

    def __init__(self, tempo=None, **keywords):
        """
        Create a SetTempo object.

        Accepts an optional number (in MPQN), bytes, or a Tempo object
        argument.
        """
        super().__init__(**keywords)
        try:
            mpqn = int.from_bytes(tempo, 'big')
        except TypeError:
            mpqn = tempo
        if isinstance(mpqn, numbers.Number):
            self.tempo = Tempo(mpqn=mpqn)
        else:
            self.tempo = tempo

    def __repr__(self):
        return '{name}({tempo!r})'.format(
                name=type(self).__name__, tempo=self.tempo)

    def _bytes(self):
        """Delegate bytes method, called by MetaEvent.__bytes__."""
        return self.tempo.mpqn.to_bytes(3, 'big')


class SMPTEOffset(MetaEvent):
    """
    Indicates an absolute time offset at the start of a track.

    Internal parsing of event parameters is not currently implemented, but
    SMPTEOffsets can be used in a pass-through fashion.
    """

    def __init__(self, data=None, **keywords):
        """Create a SMPTEOffset. Accepts a bytes argument."""
        super().__init__(**keywords)
        self.data = data

    def _bytes(self):
        """Delegate bytes method, called by MetaEvent.__bytes__."""
        return self.data


class SetTimeSignature(MetaEvent):
    """
    Sets the time signature for the sequence until the next SetTimeSignature.

    The associated TimeSignature object is accessible from the signature
    attribute.
    """

    def __init__(self, signature=None, **keywords):
        """
        Create a SetTempo object.

        Accepts an optional TimeSignature argument or any object accepted by
        TimeSignature.__init__.
        """
        super().__init__(**keywords)
        if isinstance(signature, TimeSignature):
            self.signature = signature
        else:
            self.signature = TimeSignature(signature, **keywords)

    def __repr__(self):
        return '{name}({signature!r})'.format(
                name=type(self).__name__, signature=self.signature)

    def _bytes(self):
        """Delegate bytes method, called by MetaEvent.__bytes__."""
        return bytes(self.signature)


class SetKeySignature(MetaEvent):
    """
    Sets the key signature for the track until the next SetKeySignature event.

    The key and scale can be accessed by the key and scale attributes.
    """

    def __init__(self, key=None, scale=None, **keywords):
        """
        Create a SetKeySignature from bytes or number key and scale arguments.
        """
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
        """Delegate bytes method, called by MetaEvent.__bytes__."""
        return (self.key.to_bytes(1, 'big', signed=True) +
                self.scale.to_bytes(1, 'big'))


class ProprietaryEvent(MetaEvent):
    """
    A manufacturer-specific meta event.

    The binary payload is accessible through the data attribute.
    """

    def __init__(self, data=None, **keywords):
        """Create a ProprietaryEvent from an optional bytes argument."""
        super().__init__(**keywords)
        self.data = data

    def _bytes(self):
        """Delegate bytes method, called by MetaEvent.__bytes__."""
        return self.data


class SysExEvent(Event):
    """
    A system exclusive event is a manufacturer-specific event.

    Currently unsupported. Attempting to parse SysExEvent will raise a
    MIDIError.
    """

    @classmethod
    def _parse(cls, source):
        """Delegate parser method. Called by Event.parse."""
        raise MIDIError('System exclusive events are unsupported.')


class Sequence(list):
    """
    Represents a MIDI sequence as a chronological list of events.
    
    Instead of using the internal organization of a MIDI file as a set of
    tracks with delta times in between events, the Sequence object organizes
    events in chronological order, making the track an attribute of the event
    objects.
    """

    def __init__(self, events=list(), *, format=None, division=None):
        """
        Create a Sequence.

        Accepts a list of events or another sequence as an optional argument.
        The format and time division of a sequence can be specified with the
        optional format and division keywords.
        """
        super().__init__(events)
        self.specification = TimeSpecification(sequence=self)
        self._format = None
        self.format = format
        self.division = division

    @staticmethod
    def parse(source):
        """
        Create a new Sequence object from a file or bytes.

        Corrupt, truncated, or malformed sources will raise a MIDIError.
        """
        if not isinstance(source, collections.Iterator):
            source = iter(source)

        sequence = Sequence()
        chunk = Chunk.parse(source, id='MThd')
        sequence.format = int.from_bytes(chunk[0:2], 'big')
        tracks = int.from_bytes(chunk[2:4], 'big')
        sequence.division = TimeDivision(chunk[4:6])
        track = 0
        for index in range(tracks):
            chunk = Chunk.parse(source)
            if chunk.id == 'MTrk':
                data = iter(chunk)
                cumulative = 0
                while True:
                    delta = _var_int_parse(data)
                    try:
                        event = Event.parse(data)
                    except StopIteration:
                        raise MIDIError(
                            'Incomplete track. End Track event not found.')
                    cumulative += delta
                    event.time.specification = sequence.specification
                    event.time.cumulative = cumulative
                    event.track = track
                    sequence.append(event)
                    if isinstance(event, EndTrack):
                        break
                track += 1

        sequence.sort(key=sequence._meta_sort_key)
        sequence.sort(key=sequence._cumulative_sort_key)
        sequence.update()
        return sequence

    @property
    def format(self):
        """
        Access the format of the sequence.

        Setting the format of a sequence will attempt to convert it. If the 
        conversion fails, it will raise a MIDIError. Currently, the only
        supported conversion is 0 to 1.
        """
        return self._format

    @format.setter
    def format(self, value):
        if self._format == None or len(self) == 0:
            self._format = value
        elif self._format == 0 and value == 1:
            if self.tracks != 1:
                raise MIDIError(
                        'Invalid format 0 sequence, contains {n} tracks.'\
                        .format(n=len(self)))
            self._format = 1
            for event in self:
                if isinstance(event, MetaEvent):
                    event.track = 0
                else:
                    event.track = 1
        elif self._format != value:
            raise MIDIError(
                    'Cannot convert a format {0} sequence to format {1}.'\
                    .format(self._format, value))

    @format.deleter
    def format(self):
        del self._format

    @property
    def tracks(self):
        """
        Get the number of tracks in the sequence.

        Note: May be slow, since finding the number of tracks requires
        iterating through the entire sequence.
        """
        def track(event):
            return event.track
        return track(max(self, key=track)) + 1

    def track(self, track):
        """
        Get a list of all the events associated with a track number.

        If the track number is not present in the sequence, returns an empty
        list.
        """
        events = list()
        for event in self:
            if event.track == track:
                events.append(event)
        return events

    def offset(self, time):
        for event in self:
            event.time += time
        self.specification.offset(time)

    def update(self):
        to_delete = list()
        programs = dict()
        tempo = Tempo()
        signature = TimeSignature()
        for index in range(len(self)):
            event = self[index]
            if isinstance(event, SetTempo):
                to_delete.append(index)
                tempo = event.tempo
            else:
                event.tempo = tempo
            if isinstance(event, SetTimeSignature):
                to_delete.append(index)
                signature = event.signature
            else:
                event.signature = signature

            if isinstance(event, EndTrack):
                to_delete.append(index)
            elif isinstance(event, ProgramChange):
                to_delete.append(index)
                programs[(event.track, event.channel)] = event.program
            elif isinstance(event, ChannelEvent):
                try:
                    event.program = programs[(event.track, event.channel)]
                except KeyError:
                    event.program = Program()
                    programs[(event.track, event.channel)] = event.program
        self.specification.update()
        for index in reversed(to_delete):
            del self[index]

        to_add = list()
        programs = dict()
        for event in self:
            if isinstance(event, ChannelEvent):
                program = programs.get((event.track, event.channel), None)
                if event.program != program:
                    programs[(event.track, event.channel)] = event.program
                    to_add.append(ProgramChange(time=event.time, 
                            program=event.program, track=event.track,
                            channel=event.channel))
        self.extend(to_add)
        self.extend(self.specification.events(track=0))
        self.sort(key=self._time_sort_key)
        to_add = list()
        for track in range(self.tracks):
            events = self.track(track)
            if len(events) < 1:
                to_add.append(EndTrack(time=Time(
                    specification=self.specification), track=track))
            else:
                to_add.append(EndTrack(time=events[-1].time, track=track))
        self.extend(to_add)
        self.sort()
        tempo = Tempo()
        signature = TimeSignature()
        for event in self:
            if isinstance(event, SetTempo):
                tempo = event.tempo
            else:
                event.tempo = tempo
            if isinstance(event, SetTimeSignature):
                signature = event.signature
            else:
                event.signature = signature


    def sort(self, *, key=None, reverse=False):
        if key == None:
            super().sort(key=self._meta_sort_key, reverse=reverse)
            super().sort(key=self._track_sort_key, reverse=reverse)
            super().sort(key=self._time_sort_key, reverse=reverse)
        else:
            super().sort(key=key, reverse=False)

    def append(self, event):
        if isinstance(event, Event):
            event.sequence = self
            super().append(event)
        else:
            raise TypeError('Cannot append \'{type}\' to \'Sequence\''.format(
                type=type(event).__name__))

    def extend(self, events):
        for event in events:
            self.append(event)

    @staticmethod
    def _meta_sort_key(event):
        if isinstance(event, SetTempo):
            return 0
        elif isinstance(event, SetTimeSignature):
            return 1
        elif isinstance(event, ProgramChange):
            return 2
        elif isinstance(event, EndTrack):
            return 4
        else:
            return 3

    @staticmethod
    def _track_sort_key(event):
        return event.track

    @staticmethod
    def _time_sort_key(event):
        return event.time

    @staticmethod
    def _cumulative_sort_key(event):
        return event.time.cumulative

    def __bytes__(self):
        """Bytes for writing to a MIDI file."""
        array = bytearray()
        header = bytearray()
        tracks = self.tracks
        header.extend(self.format.to_bytes(2, 'big'))
        header.extend(tracks.to_bytes(2, 'big'))
        header.extend(bytes(self.specification.division))
        chunk = Chunk(header, id='MThd')
        array.extend(chunk.raw)
        
        sequence = type(self)(self, division=self.division)
        sequence.sort()
        sequence.update()
        for track in range(tracks):
            events = sequence.track(track)
            chunk = Chunk(id='MTrk')
            cumulative = 0
            for event in events:
                delta = event.time.cumulative - cumulative
                chunk.extend(_var_int_bytes(delta))
                chunk.extend(bytes(event))
                cumulative = event.time.cumulative
            array.extend(chunk.raw)
        return bytes(array)


class Chunk(bytearray):
    """
    Represents a chunk of a MIDI file, accessible as a bytearray.

    MIDI files group data into chunks. Generally a file consists of one header
    chunk followed by one or more track chunks.
    """

    def __init__(self, data=bytearray(), *, id=None):
        """
        Create a Chunk object.
        
        Can be initialized from a bytes object, and the chunk ID can be 
        specified with the optional id keyword.
        """
        super().__init__(data)
        self.id = id

    @staticmethod
    def parse(source, id=None):
        chunk = Chunk()
        if isinstance(source, io.IOBase):
            if hasattr(source, 'mode'):
                if 'b' not in source.mode:
                    raise MIDIError('Cannot parse text mode file.')
            start = source.tell()
        if not isinstance(source, collections.Iterator):
            source = iter(source)
        length = 8
        mode = 'id'
        while True:
            try:
                item = next(source)
            except StopIteration:
                if mode != 'data':
                    raise MIDIError(
                            'Incomplete chunk header. Read {got}/8 bytes.'\
                            .format(got=len(chunk)))
                raise MIDIError(
                        'Incomplete {id} chunk. Read {got}/{total} bytes.'\
                        .format(got=len(chunk), total=length, id=chunk.id))

            if isinstance(item, int):
                chunk.append(item)
            else:
                chunk.extend(item)

            if mode == 'id' and len(chunk) >= 4:
                try:
                    chunk.id = chunk[0:4].decode('iso8859-1')
                except UnicodeError:
                    raise MIDIError('Unable to parse chunk ID.')
                if id and id != chunk.id:
                    raise MIDIError('{id} chunk not found.'.format(id=id))
                mode = 'len'
            if mode == 'len' and len(chunk) >= 8:
                length = int.from_bytes(chunk[4:8], 'big') + 8
                mode = 'data'
            if mode == 'data' and len(chunk) >= length:
                if isinstance(source, io.IOBase):
                    source.seek(start + length)
                del chunk[length:] 
                del chunk[:8]
                return chunk

    @property
    def raw(self):
        """Access the raw data, including ID and length bytes."""
        value = bytearray(self.id, 'iso8859-1')
        value.extend(len(self).to_bytes(4, 'big'))
        value.extend(self)
        return value
    
    @raw.setter
    def raw(self, value):
        self.id = str(value, 'iso8859-1')
        self[:] = value[8:]

    def __bytes__(self):
        """Bytes for writing to a MIDI file."""
        return bytes(self.raw)

    def __str__(self):
        """A hex string of the chunk."""
        return str(binascii.hexlify(self.raw), 'ascii')

    def __repr__(self):
        return 'Chunk({id}, {data})'.format(id=repr(self.id), 
                data=repr(bytes(self)[8:]))


def _var_int_parse(source):
    """Converts the bytes of a MIDI variable length integer to an int."""
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
    """Convent an int to the bytes of a MIDI variable length integer."""
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
            

def _name_to_desc(name):
    """Convert a name (e.g.: 'NoteOn') to a description (e.g.: 'Note On')."""
    if len(name) < 1:
        return ''
    desc = list()
    desc.append(name[0])
    for index in range(1, len(name)):
        if name[index].isupper():
            desc.append(' ')
        desc.append(name[index])
    return ''.join(desc)


class MIDIError(Exception):
    """
    An exception raised when parsing fails or at an illegal operation.
    
    MIDIError is a thin wrapper for Exception. A MIDIError raised by the midi
    module will contain one argument: a string explaining what went wrong.
    """


ChannelEvent._events = {
        0x80: NoteOff,
        0x90: NoteOn,
        0xa0: NoteAftertouch,
        0xb0: ControlChange,
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
        0x04: ProgramName,
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
del key, value

Program.names = Program._names.values()
Program.descs = Program._descs.values()

