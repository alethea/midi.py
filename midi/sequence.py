#!/usr/bin/env python3

import collections
from . import event
from . import time

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


