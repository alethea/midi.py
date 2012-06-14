#!/usr/bin/env python3

import numbers

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

    def __str__(self):
        return '{bpm} BPM'.format(bpm=self.bpm)

    def __repr__(self):
        return 'Tempo({bpm})'.format(bpm=self.bpm)

    def __bytes__(self):
        return self.mpqn.to_bytes(3, 'big')

