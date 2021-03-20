from nmigen import *
from nmigen.sim import Simulator
import numpy as np

class LinearFeedbackShiftRegister(Elaboratable):
    def __init__(self, taps=[0, 4, 7], init=(37 | (1 << 6))):
        self.width = max(taps)
        self.taps = taps
        self.init = init

        self.reset = Signal()
        self.output = Signal()
        self.run_strobe = Signal()
        self.register = Signal(self.width, reset=init)

    def elaborate(self, platform):
        m = Module()

        skipfirst = Signal()

        with m.If(self.run_strobe | (skipfirst == 0)):
            m.d.sync += skipfirst.eq(1)
            for i in range(0, self.width - 1):
                if (self.width - i - 1) in self.taps:
                    m.d.sync += self.register[i].eq(self.register[i + 1] ^ self.register[0])
                else:
                    m.d.sync += self.register[i].eq(self.register[i + 1])
            m.d.sync += self.register[-1].eq(self.register[0])
        with m.Else():
            with m.If(self.reset):
                m.d.sync += [
                    self.register.eq(self.init),
                    skipfirst.eq(0)
                ]

        m.d.comb += self.output.eq(self.register[-1])

        return m

class GaloisCRC(Elaboratable):
    def __init__(self, width=24, taps=[1, 3, 4, 6, 9, 10, 24], init=0x555555, domain="sync"):
        self.crc = Signal(width, reset=init)
        self.reset = Signal()
        self.en = Signal()
        self.input = Signal()
        self.domain = domain
        self.taps = taps

    def elaborate(self, platform):
        m = Module()

        taps = [i for i in self.taps]

        feedback = Signal()
        m.d.comb += feedback.eq(self.input ^ self.crc[-1])

        domain = getattr(m.d, self.domain)
        with m.If(self.reset):
            domain += self.crc.eq(0x555555)
        with m.Else():
            with m.If(self.en):
                for i in range(1,24):
                    if i in taps:
                        domain += self.crc[i].eq(self.crc[i-1] ^ feedback)
                    else:
                        domain += self.crc[i].eq(self.crc[i-1])
                domain += self.crc[0].eq(feedback)

        return m

def py_crc(data):
    state = 0x555555
    for i in range(data.size):
        ni = (0x1 & (state >> 23)) ^ data[i]
        state = (((state << 1) | ni) ^ ni*0b11001011010) & 0xFFFFFF
    return state

def test_crc():

    m = GaloisCRC()
    sim = Simulator(m)
    sim.add_clock(1e-6, domain="sync")

    data = [0, 1, 0, 0, 1, 0, 1, 1, 1, 0]
    def process():
        for bit in data:
            yield m.input.eq(bit)
            yield m.en.eq(1)
            yield
        yield
        crc = yield m.crc
        assert(crc == py_crc(np.array(data)))

    sim.add_sync_process(process)
    
    with sim.write_vcd("crc.vcd"):
        sim.run()

def prbs(n=0, taps=[]):
    state = [1]*n
    shift = lambda s: [sum([s[i] for i in taps]) % 2] + s[0:-1]
    out = []
    for i in range(2**n - 1):
        out.append(state[-1])
        state = shift(state)
    return out

prbs4 = lambda: prbs(n=4, taps=[2,3])
prbs9 = lambda: prbs(n=9, taps=[4,8])
prbs15 = lambda: prbs(n=15, taps=[13,14])
prbs23 = lambda: prbs(n=23, taps=[17,22])