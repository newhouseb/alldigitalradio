from nmigen import *

class RunningBoxcarFilter(Elaboratable):
    def __init__(self, filter_width, max_val=20, domain="sync"):
        self.domain = domain
        self.memory = Memory(width=8, depth=filter_width, init=[0]*filter_width)
        self.input = Signal(signed(8))
        self.output = Signal(signed(14))
        self.filter_width = filter_width
        self.running_sum = Signal(signed(14))

        self.debug = Signal(signed(14))
        self.debug1 = Signal(signed(14))
        self.debug2 = Signal(signed(14))
        self.debugen = Signal()

        self.memout = Signal(signed(8))
        self.addr = Signal(12)

    def elaborate(self, platform):
        m = Module()

        m.submodules.rport = rport = self.memory.read_port(domain=self.domain)
        m.submodules.wport = wport = self.memory.write_port(domain=self.domain)

        running_sum = self.running_sum

        domain = getattr(m.d, self.domain)

        addr = Signal(range(self.filter_width))

        domain += [
            rport.addr.eq(addr + 1),
            wport.addr.eq(addr), # TODO: handle underflow
            wport.data.eq(self.input),
            self.memout.eq(rport.data),
        ]

            # self.addr.eq(addr),
        m.d.comb += [
            wport.en.eq(1),
            self.output.eq(running_sum)
        ]

        cycles = Signal(range(self.filter_width + 1))
        with m.If(cycles <= self.filter_width):
            domain += cycles.eq(cycles + 1)
            domain += running_sum.eq(running_sum + self.input)
        with m.Else():
            pass

        m.d.comb += self.debug.eq(self.input - self.memout.as_signed())

        domain += running_sum.eq(running_sum + self.input - self.memout.as_signed())

        domain += self.debug1.eq(self.input)
        domain += self.debug2.eq(self.memout.as_signed())

        with m.If(addr == self.filter_width - 1):
            domain += addr.eq(0)
        with m.Else():
            domain += addr.eq(addr + 1)

        return m

class SimpleDecimator(Elaboratable):
    def __init__(self, decimation_factor=None, max_val=20, domain="sync"):
        self.decimation_factor = decimation_factor
        self.domain = domain

        self.input = Signal(signed(14))
        self.output = Signal(signed(20))

        self.running_sum = Signal(signed(20))
        self.counter = Signal(signed(8))

    def elaborate(self, platform):
        m = Module()

        domain = getattr(m.d, self.domain)
        with m.If(self.counter == self.decimation_factor - 1):
            domain += [
                self.counter.eq(0),
                self.output.eq(self.running_sum + self.input),
                self.running_sum.eq(0)
            ]
        with m.Else():
            domain += [
                self.counter.eq(self.counter + 1),
                self.running_sum.eq(self.running_sum + self.input)
            ]

        return m