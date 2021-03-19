import numpy as np

from nmigen import *
from nmigen.sim import Simulator
from alldigitalradio.oscillator import OneBitFixedOscillator

class SummingMixer(Elaboratable):
    def __init__(self, sample_rate=None, frequency=None, max_error=None, width=20, domain='sync', slowdomain="rxdiv4"):
        self.width = width
        self.domain = domain
        self.slowdomain = slowdomain

        self.oscillatorI = OneBitFixedOscillator(
                sample_rate=sample_rate, 
                frequency=frequency, 
                max_error=max_error, 
                width=width, 
                domain=domain)

        self.oscillatorQ = OneBitFixedOscillator(
                sample_rate=sample_rate, 
                frequency=frequency, 
                max_error=max_error, 
                width=width, 
                phase=np.pi/2,
                domain=domain)

        self.input = Signal(width)
        self.outputI = Signal(signed(7)) #range(-2*width, 2*width))
        self.outputQ = Signal(signed(7)) #range(-2*width, 2*width))

        self.outputIshift = Signal(unsigned(7*4))
        self.outputQshift = Signal(unsigned(7*4))

        self.outputIsum = Signal(signed(9))
        self.outputQsum = Signal(signed(9))

    def inputs(self):
        return [self.input]

    def outputs(self):
        return [self.outputIsum, self.outputQsum]
        
    def elaborate(self, platform):
        m = Module()

        m.submodules.oscillatorI = self.oscillatorI
        m.submodules.oscillatorQ = self.oscillatorQ

        ipsum = Signal(signed(5))
        ipsumA = Signal(signed(5))
        ipsumB = Signal(signed(5))

        insum = Signal(signed(5))
        insumA = Signal(signed(5))
        insumB = Signal(signed(5))

        qpsum = Signal(signed(5))
        qpsumA = Signal(signed(5))
        qpsumB = Signal(signed(5))

        qnsum = Signal(signed(5))
        qnsumA = Signal(signed(5))
        qnsumB = Signal(signed(5))

        domain = getattr(m.d, self.domain)

        domain += [
            ipsumA.eq(sum(self.oscillatorI.output[0:10] & self.input[0:10])),
            ipsumB.eq(sum(self.oscillatorI.output[10:20] & self.input[10:20])),
            ipsum.eq(ipsumA + ipsumB),

            insumA.eq(sum((~self.oscillatorI.output[0:10]) & self.input[0:10])),
            insumB.eq(sum((~self.oscillatorI.output[10:20]) & self.input[10:20])),
            insum.eq(insumA + insumB),

            self.outputI.eq((ipsum - insum)),

            qpsumA.eq(sum(self.oscillatorQ.output[0:10] & self.input[0:10])),
            qpsumB.eq(sum(self.oscillatorQ.output[10:20] & self.input[10:20])),
            qpsum.eq(qpsumA + qpsumB),

            qnsumA.eq(sum((~self.oscillatorQ.output[0:10]) & self.input[0:10])),
            qnsumB.eq(sum((~self.oscillatorQ.output[10:20]) & self.input[10:20])),
            qnsum.eq(qnsumA + qnsumB),

            self.outputQ.eq((qpsum - qnsum)),

            self.outputIshift.eq(Cat(self.outputI, self.outputIshift[0:7*3])),
            self.outputIsum.eq(
                self.outputIshift[7*0:7*1].as_signed() +
                self.outputIshift[7*1:7*2].as_signed() +
                self.outputIshift[7*2:7*3].as_signed() +
                self.outputIshift[7*3:7*4].as_signed()
            ),
            self.outputQshift.eq(Cat(self.outputQ, self.outputQshift[0:7*3])),
            self.outputQsum.eq(
                self.outputQshift[7*0:7*1].as_signed() +
                self.outputQshift[7*1:7*2].as_signed() +
                self.outputQshift[7*2:7*3].as_signed() +
                self.outputQshift[7*3:7*4].as_signed()
            )
        ]

        return m