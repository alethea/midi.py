#!/usr/bin/env python3

class Tempo:
    def __init__(self, bpm=120):
        self.bpmb = bpm

    @property
    def mpqn(self):
        return 60000000 // self.bpm

    @mpqn.setter
    def mpqn(self, value):
        self.bpm = 60000000 / value

    def __str__(self):
        return '{bpm} BPM'.format(bpm=self.bpm)

    def __repr__(self):
        return 'Tempo({bmp})'.format(bpm=self.bpm)

