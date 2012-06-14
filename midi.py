#!/usr/bin/env python3

"""
A simple library for maniplating MIDI data as Python data structures and
reading and writing data to Standard MIDI Format files.

Note that this library was constructed without the official MIDI
specification, and some structures may use a different name than the
specification.
"""

import io
import binascii

class MIDIError(Exception):
    pass

class Chunk(bytearray):

    @staticmethod
    def parse(source, id=None):
        chunk = Chunk()
        length = 9
        for item in source:
            if isinstance(item, int):
                chunk.append(item)
            else:
                chunk.extend(item)

            if len(chunk) >= 4:
                chunk.id = chunk[0:4].decode('ascii')
                if id and id != chunk.id:
                    raise MIDIError('{id} chunk not found.'.format(id=id))
            if len(chunk) >= 8:
                length = int.from_bytes(chunk[4:8], 'big') + 8
            if len(chunk) >= length:
                del chunk[length:] 
                del chunk[:8]
                break
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
        self = value[8:]

    def __bytes__(self):
        return bytes(self.raw)

    def __str__(self):
        return str(binascii.hexlify(self), 'ascii')

