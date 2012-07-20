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
        self.bpm = 60000000 / value

    @property
    def bps(self):
        """The tempo in beats per second."""
        return self.bpm / 60

    @bps.setter
    def bps(self, value):
        self.bpm = value * 60

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

    def __str__(self):
        return Program._descs.get(self.number, '')

    def __repr__(self):
        return 'Program({name!r})'.format(name=self.name)

    def __bytes__(self):
        """Single byte integer of the program number."""
        return (self.number - 1).to_bytes(1, 'big')


class TimeSpecificationNode:
    def __init__(self):
        self.note = 0.0
        self.bar = 1
        self.beat = 1
        self.tick = 1
        self.cumulative = 0
        self.signature = TimeSignature()
        self.division = TimeDivision(256)
        self.tempo = Tempo(84)

    @property
    def ppn(self):
        if self.division.mode == 'ppqn':
            return self.division.ppqn * 4
        else:
            return self.division.pps / self.tempo.bps * 4


class TimeSpecification(list):

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

    def time(self, time_object):
        return self._lookup(time_object.note, 'note')

    def note(self, value):
        return self._lookup(value, 'note')
    
    def cumulative(self, value):
        return self._lookup(value, 'cumulative')
    
    def _lookup(self, value, key):
        for node in reversed(self):
            if node.__dict__[key] <= value:
                return node
        return None


class TimeAbsolute:
    def __init__(self, note=0.0, *, specification=None):
        self._node = None
        self._cumulative = None
        self._note = note
        self.specification = specification

    @property
    def note(self):
        if self._note == 0 and self._cumulative != None:
            self.cumulative = self._cumulative
        return self._note

    @note.setter
    def note(self, value):
        self._note = value

    @property
    def bar(self):
        node = self.node
        if node == None:
            return None
        note = self.note - node.note
        npm = node.signature.numerator / node.signature.denominator
        return math.floor(note / npm) + node.bar

    @bar.setter
    def bar(self, value):
        self._node = self._node_error('bar')
        self.triple = (value, self.beat, self.tick)
        self._node = None

    @property
    def beat(self):
        node = self.node
        if node == None:
            return None
        note = self.note - node.note
        npm = node.signature.numerator / node.signature.denominator
        npb = node.signature.denominator
        return math.floor((note % npm) * npb) + node.beat

    @beat.setter
    def beat(self, value):
        self._node = self._node_error('beat')
        self.triple = (self.bar, value, self.tick)
        self._node = None

    @property
    def tick(self):
        node = self.node
        if node == None:
            return None
        note = self.note - node.note
        mod = note % (1 / node.signature.denominator)
        return math.floor(mod * 1920) + node.tick

    @tick.setter
    def tick(self, value):
        self._node = self._node_error('tick')
        self.triple = (self.bar, self.beat, value)
        self._node = None

    @property
    def cumulative(self):
        node = self.node
        if node == None:
            return self._cumulative
        note = self.note - node.note
        return round(note * node.ppn + node.cumulative)

    @cumulative.setter
    def cumulative(self, value):
        if self.specification == None:
            self._cumulative = value
            return
        node = self.specification.cumulative(value)
        if node == None:
            self._cumulative = value
            return
        self._cumulative = None
        self._note = node.note + (value - node.cumulative) / node.ppn

    @property
    def triple(self):
        self._node = self.specification.time(self)
        triple_tuple = (self.bar, self.beat, self.tick)
        self._node = None
        return triple_tuple

    @triple.setter
    def triple(self, value):
        bar, beat, tick = value
        error = 'Triple out of range: {bar}|{beat}|{tick}.'.format(
                bar=bar, beat=beat, tick=tick)
        if bar < 1 or beat < 1 or tick < 1:
            raise MIDIError(error)
        if self.specification == None:
            raise MIDIError('Cannot set triple without a time specification.')
        node = self.specification.triple(value)
        if node == None:
            raise MIDIError('Cannot set triple without a time specification.')
        if beat > node.signature.numerator:
            raise MIDIError(error)
        if tick > 1920 / node.signature.denominator:
            raise MIDIError(error)
        npm = node.signature.numerator / node.signature.denominator
        self._note = (bar - 1) * npm
        self._note += (beat - 1) / node.signature.denominator
        self._note += (tick - 1) / 1920

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

    def __repr__(self):
        return str(self)

    def __str__(self):
        self._node = self.specification.time(self)
        string = '{bar}|{beat}|{tick}'.format(bar=self.bar,
                beat=self.beat, tick=self.tick)
        self._node = None
        return string


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
    """Base class for MIDI events."""

    def __init__(self, **keywords):
        """
        Create a new Event object.

        Since Event inherits Delta for storing its time information, any
        keyword arguments Delta supports can be passed to the constructor,
        in addition to the time and track keywords.
        """
        self.time = keywords.pop('time', Time())
        self.track = keywords.pop('track', None)
        super().__init__(**keywords)

    track = None
    time = None

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
        accept the channel keyword.
        """
        self.channel = keywords.pop('channel', None)
        super().__init__(**keywords)
    
    @classmethod
    def _parse(cls, source=None, status=None):
        """Delegate parser method. Called by Event.parse."""
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
        array.extend(Delta.__bytes__(self))
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


class Controller(ChannelEvent):
    """
    Indicates a change in a controller on a channel.

    Available attributes are controller and value.
    """

    def __init__(self, controller=None, value=None, **keywords):
        """
        Create a Controller object. Accepts controller and value arguments.
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
        array.extend(Delta.__bytes__(self))
        array.append(self.status)
        array.append(self.type)
        array.extend(_var_int_bytes(len(data)))
        array.extend(data)
        return bytes(array)


class TextMetaEvent(MetaEvent):
    """
    Base class for meta events with a text payload.

    The text is available through the text attribute. Characters should not
    exceed the ASCII range.
    """

    def __init__(self, text=None, **keywords):
        """Create a TextMetaEvent from a string argument, if present."""
        super().__init__(**keywords)
        try:
            self.text = str(text, 'ascii')
        except TypeError:
            self.text = text

    def __repr__(self):
        return '{name}({text!r})'.format(
                name=type(self).__name__, text=self.text)

    def _bytes(self):
        """Delegate bytes method, called by MetaEvent.__bytes__."""
        return self.text.encode('ascii')


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
        if isinstance(signatue, TimeSignature):
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
        sequence._division = TimeDivision(chunk[4:6])
        track = 0
        for index in range(tracks):
            chunk = Chunk.parse(source)
            if chunk.id == 'MTrk':
                data = iter(chunk)
                cumulative = 0
                while True:
                    try:
                        event = Event.parse(data)
                    except StopIteration:
                        raise MIDIError(
                            'Incomplete track. End Track event not found.')
                    if isinstance(event, EndTrack):
                        break
                    cumulative += event.ticks
                    event.cumulative = cumulative
                    event.track = track
                    event.division = sequence._division
                    sequence.append(event)
                track += 1

        def cumulative(event):
            return event.cumulative
        sequence.sort(key=cumulative)
        tracks = sequence.tracks
        times = list()
        for track in range(tracks):
            times.append(Time())
        tempo = Tempo()
        signature = TimeSignature()
        for event in sequence:
            del event.cumulative
            if isinstance(event, SetTempo):
                tempo = event.tempo
            else:
                event.tempo = tempo
            if isinstance(event, SetTimeSignature):
                signature = event.signature
            else:
                event.signature = signature
            times[event.track] += event
            event.time = times[event.track]

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
    def division(self):
        """
        Access the time division of the sequence.
        
        Setting the time division of a sequence will update all events to
        reference the new time division.
        """
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

    def __bytes__(self):
        """Bytes for writing to a MIDI file."""
        array = bytearray()
        header = bytearray()
        tracks = self.tracks
        header.extend(self.format.to_bytes(2, 'big'))
        header.extend(tracks.to_bytes(2, 'big'))
        header.extend(bytes(self.division))
        chunk = Chunk(header, id='MThd')
        array.extend(chunk.raw)
        for track in range(tracks):
            events = self.track(track)
            events.append(EndTrack())
            chunk = Chunk(id='MTrk')
            for event in events:
                chunk.extend(bytes(event))
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
                    chunk.id = chunk[0:4].decode('ascii')
                except UnicodeError:
                    raise MIDIError( 'Encountered a non-ASCII chunk ID.')
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
        value = bytearray(self.id, 'ascii')
        value.extend(len(self).to_bytes(4, 'big'))
        value.extend(self)
        return value
    
    @raw.setter
    def raw(self, value):
        self.id = str(value, 'ascii')
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

