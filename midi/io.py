#!/usr/bin/env python3

import io
import binascii
import collections
from .error import MIDIError

class Chunk(bytearray):
    def __init__(self, id=None, data=bytearray()):
        self.id = id
        self[:] = bytearray(data)

    @staticmethod
    def parse(source, id=None):
        chunk = Chunk()
        length = 8
        mode = 'id'
        for item in source:
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

def _var_int_parse(iterable):
    value = 0
    if not isinstance(iterable, collections.Iterator):
        iterable = iter(iterable)
    for i in range(4):
        byte = next(iterable)
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

