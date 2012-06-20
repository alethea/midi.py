#!/usr/bin/env python3

import collections
from . import event

class Track(list):

    @staticmethod
    def parse(source):
        if not isinstance(source, collections.Iterator):
            source = iter(source)
        track = Track()
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

