import numpy as np
from nmigen import *
from nmigen.sim import Simulator
from alldigitalradio.util import (
    binarize,
    make_carrier,
    pack_mem
)
import json

class OneBitFixedOscillator(Elaboratable):
    def __init__(self, sample_rate: float, frequency: float, max_error: float, width: int, phase: float=0, domain: str="sync"):
        self.sample_rate = sample_rate
        self.frequency = frequency
        self.max_error = max_error
        self.width = width
        self.domain = domain
        self.output = Signal(width)

        samples = width
        while True:
             period_error = np.round(samples*frequency/sample_rate)
             realized_frequency = period_error*sample_rate/samples
             if np.abs(realized_frequency - frequency) < max_error:
                 break
             samples += width

        pattern = binarize(make_carrier(realized_frequency, sample_rate, samples, phase=phase))

        self.packed_pattern = pack_mem(pattern, width)
        self.realized_frequency = realized_frequency
        self.pattern_words = len(self.packed_pattern)

        print("Goal Frequency: {}, actual: {}, period: {}, len: {}".format(frequency, realized_frequency, samples, len(self.packed_pattern)))

    def inputs(self):
        return []

    def outputs(self):
        return [self.output]

    def elaborate(self, platform):
        m = Module()

        pattern = Memory(width=self.width, depth=len(self.packed_pattern), init=self.packed_pattern)
        m.submodules.pattern_rport = rport = pattern.read_port(domain=self.domain)

        self.counter = counter = Signal(range(len(self.packed_pattern) + 1))

        domain = getattr(m.d, self.domain)
        with m.If(counter == (len(self.packed_pattern) - 1)):
            domain += counter.eq(0) 
        with m.Else():
            domain += counter.eq(counter + 1) 

        m.d.comb += [
            rport.addr.eq(counter)
        ]

        domain += [
            self.output.eq(rport.data)
        ]

        return m

def test_frequency_generation():
    """This creates an oscillator with a frequency error that meets a given spec and then
       verifies that it actually loops through everything. Note that below a certain error
       level, we start to get assorted floating point differences that mean that this test
       fails against even the "realized frequency" reference"""
    
    freq = 2.4*1e9
    sample_rate = 5*1e9
    error = 0.0001*1e6 # 50ppm allowable frequency error, not 

    m = OneBitFixedOscillator(sample_rate=sample_rate, frequency=freq, max_error=error, width=20, domain='sync')
    sim = Simulator(m)
    sim.add_clock(1e-6, domain="sync")

    assert np.abs(m.realized_frequency - freq) < error
    samples = m.pattern_words*10

    ref = binarize(make_carrier(sample_rate=sample_rate, freq=m.realized_frequency, samples=samples*20))
    ref = pack_mem(ref, 20)

    output = np.zeros((samples,), dtype=np.uint32)

    def process():
        for i in range(samples):
            yield
            result = yield m.output
            counter = yield m.counter
            output[i] = result
            if bin(result) != bin(ref[i]):
                raise Exception("At {} got {} but expected {}".format(i, bin(result), bin(ref[i])))
        print(json.dumps(list(map(int, output))))

    sim.add_sync_process(process)
    
    with sim.write_vcd("nco.vcd"):
        sim.run()