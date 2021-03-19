
from nmigen import *

class MagnitudeApproximator(Elaboratable):
    def __init__(self):
        self.inputI = Signal(signed(32))
        self.inputQ = Signal(signed(32))

        self.magnitude = Signal(unsigned(32))

    def inputs(self):
        return [self.inputI, self.inputQ]

    def outputs(self):
        return [self.magnitude]

    def elaborate(self, platform):
        m = Module()
        # m.d.comb += self.magnitude.eq(abs(self.inputI) + abs(self.inputQ))

        Iabs = Signal(unsigned(32))
        Qabs = Signal(unsigned(32))
        m.d.comb += [
            Iabs.eq(abs(self.inputI)),
            Qabs.eq(abs(self.inputQ)),
        ]

        maxs = lambda a, b: Mux(a > b, a, b)
        mins = lambda a, b: Mux(a < b, a, b)

        a = Signal(signed(32))
        b = Signal(signed(32))
        m.d.comb += [
            a.eq(maxs(Iabs, Qabs)),
            b.eq(mins(Iabs, Qabs)),
        ]

        m.d.comb += self.magnitude.eq(maxs((a - (a >> 8)) + (b >> 1), a))

        return m
