import numpy as np

def pack_mem(bits: np.ndarray, width: int):
    out = []
    for word in np.reshape(bits, (len(bits)//width, width)):
        out.append(int(sum([1 << i for i in range(width) if word[i] > 0])))
    return out

def unpack_mem(words: np.ndarray, width: int):
    out = []
    for word in words:
        for i in range(width):
            out.append(1 if word & (1 << i) else 0)
    return np.array(out)

def make_carrier(freq: float=None, sample_rate: float=None, samples: int=None, phase: float=0):
    t = (1/sample_rate)*np.arange(samples)
    return np.real(np.exp(1j*(2*np.pi*freq*t - phase)))

def binarize(a: np.ndarray):
    return np.sign(a)
    return (np.sign(a)*0.5 + 0.5).astype(np.uint8)

GHz = 1e9
MHz = 1e6
KHz = 1e3
Hz = 1