from nmigen import *
from nmigen.sim import Simulator
import numpy as np

class Matcher(Elaboratable):
    def __init__(self, pattern, interval, domain="sync"):
        self.pattern = pattern
        self.interval = interval
        self.domain = domain

        self.input = Signal()
        self.shiftreg = Signal((len(pattern) - 1)*(interval + 1) + 1)
        self.match = Signal()

        self.view = Signal(len(pattern))

    def inputs(self):
        return [self.input]

    def outputs(self):
        return [self.match, self.view]

    def elaborate(self, platform):
        m = Module()

        domain = getattr(m.d, self.domain)
        domain += self.shiftreg.eq(Cat(self.shiftreg[1:], self.input))

        m.d.comb += self.view.eq(Cat([self.shiftreg[i*(self.interval + 1)] for i in range(len(self.pattern))]))
        m.d.comb += self.match.eq(Cat([self.pattern[i] == self.shiftreg[i*(self.interval + 1)] for i in range(len(self.pattern))]).all())

        return m

class CorrelativeSynchronizer(Elaboratable):
    def __init__(self, pattern, samples_per_symbol, domain="sync"):
        self.samples_per_symbol = samples_per_symbol
        self.matcher = Matcher(pattern, samples_per_symbol - 1, domain=domain)
        self.domain = domain

        self.reset = Signal()
        self.input = Signal()
        self.sample_strobe = Signal()

    def inputs(self):
        return [self.input]

    def outputs(self):
        return [self.sample_strobe]

    def elaborate(self, platform):
        m = Module()

        eye_width = Signal(range(self.samples_per_symbol + 1))
        domain = getattr(m.d, self.domain)
        counter = Signal(range(self.samples_per_symbol + 1))

        m.submodules.matcher = self.matcher
        m.d.comb += self.matcher.input.eq(self.input)

        with m.FSM(domain=self.domain):
            with m.State('SEARCHING'):
                with m.If(self.matcher.match):
                    domain += eye_width.eq(0)
                    m.next = "MEASURING"
            with m.State('MEASURING'):
                with m.If(self.matcher.match):
                    # TODO: Handle eye width that's wider than a symbol
                    domain += eye_width.eq(eye_width + 1)
                with m.Else():
                    # The +1 comes from the fact that it takes a clock
                    # cycle for us to find the match
                    domain += counter.eq((eye_width >> 1) + 1)
                    m.next = "SAMPLING"
            with m.State('SAMPLING'):
                with m.If(self.reset):
                    m.next = "SEARCHING"
                with m.Else():
                    with m.If(counter == self.samples_per_symbol - 1):
                        domain += [
                            counter.eq(0),
                            self.sample_strobe.eq(1)
                        ]
                    with m.Else():
                        domain += [
                            counter.eq(counter + 1),
                            self.sample_strobe.eq(0)
                        ]
        return m

def test_pattern_matching():
    m = Matcher(pattern=[0,1,1,0], interval=1)
    sim = Simulator(m)
    sim.add_clock(1e-6, domain="sync")

    haystack = [0,0,1,0,0,1,1,1,0,1,1,1,1,0,0,0,0,0,0,0]

    def process():
        matchcount = 0
        for i in range(len(haystack)):
            yield
            yield m.input.eq(haystack[i])
            matchcount += yield m.match
        assert(matchcount == 1)

    sim.add_sync_process(process)
    
    with sim.write_vcd("matching.vcd"):
        sim.run()