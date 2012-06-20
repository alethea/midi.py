#!/usr/bin/env python3

import collections
from . import event, time, io

class Track(list):

    @staticmethod
    def parse(source):
        track = Track()
        if not isinstance(source, collections.Iterator):
            source = iter(source)
        while True:
            item = event.Event.parse(source)
            if isinstance(item, event.EndTrack):
                break
            track.append(item)
        return track

    def __bytes__(self):
        array = bytearray()
        for item in self:
            array.extend(bytes(item))
        end_track = event.EndTrack()
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
        header.time_division = time.TimeDivision(array[4:6])
        return header

    def __bytes__(self):
        array = bytearray()
        array.extend(self.format.to_bytes(2, 'big'))
        array.extend(self.tracks.to_bytes(2, 'big'))
        array.extend(bytes(self.time_division))
        return bytes(array)


class Sequence(list):
    def __init__(self, header=None, tracks=list()):
        super().__init__(tracks)
        self.header=header

    @staticmethod
    def parse(source):
        sequence = Sequence()
        if not isinstance(source, collections.Iterator):
            source = iter(source)
        chunk = io.Chunk.parse(source, id='MThd')
        sequence.header = Header.parse(chunk)
        for i in range(sequence.header.tracks):
            chunk = io.Chunk.parse(source)
            if chunk.id == 'MTrk':
                track = Track.parse(chunk)
                sequence.append(track)
        return sequence

    def __bytes__(self):
        array = bytearray()
        chunk = io.Chunk('MThd', bytes(self.header))
        array.extend(bytes(chunk))
        for track in self:
            chunk = io.Chunk('MTrk', bytes(track))
            array.extend(bytes(chunk))
        return bytes(array)

