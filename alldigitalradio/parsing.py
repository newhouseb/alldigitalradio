from collections import OrderedDict 

def o(*args, lsb=None):
  out = []
  for arg in args:
    if lsb:
      for i in range(8):
        out.append(1 if (1 << i) & arg else 0)
    else:
      for i in reversed(range(8)):
        out.append(1 if (1 << i) & arg else 0)

  return out

class Chunk(object):
  def __init__(self, **parts):
    self.parts = parts
    for k, v in parts.items():
      setattr(self, k, v)

  def bits(self):
    out = []
    for key, _ in self.parts.items():
      values = getattr(self, key)
      if type(values) == Chunk:
        out += values.bits()
      else:
        out += values
    return out

  def json(self):
    parts = OrderedDict()
    for key, _ in self.parts.items():
      values = getattr(self, key)
      if type(values) == Chunk:
        parts[key] = values.json()
      else:
        parts[key] = values
    return parts

def chunk(**chunks):
  out = []
  for _, values in chunks.items():
    out += values
  return out

def flip(bits):
  return list(reversed(bits))

def num(n, bits=8, lsb=None, msb=None):
  out = []
  if lsb:
    for i in reversed(range(bits)):
      out.append(1 if (1 << i) & n else 0)
    return out
  if msb:
    for i in range(bits):
      out.append(1 if (1 << i) & n else 0)
    return out
  raise Exception("Need to specify lsb or msb")

class Format(object):
  def __init__(self, **parts):
    self.parts = parts

  def parse(self, bits):
    parsed = {}
    read = 0
    for k,v in self.parts.items():
      if type(v) == Format:
        r, chunk = v.parse(bits[read:])
        read += r
        parsed[k] = chunk
      else:
        parsed[k] = bits[read:read + v]
        read += v
    return read, Chunk(**parsed)

def lsb_num(b):
  return sum([1 << i if b[i] else 0  for i in range(len(b))])
