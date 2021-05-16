import sys

from nmigen import Elaboratable, Module, Memory, Signal
from nmigen.build import Resource, Pins, Attrs

from alldigitalradio.io.generic_serdes import get_serdes_implementation
import alldigitalradio.hardware as hardware
from alldigitalradio.shiftregisters import prbs9, prbs14
from alldigitalradio.util import pack_mem

class CWOutExample(Elaboratable):
    def elaborate(self, platform):
        m = Module()
        m.submodules.serdes = serdes = get_serdes_implementation()()

        seq = prbs14()
        print("Peaks will be", 5000/len(seq), "MHz apart")
        pattern = Memory(width=20, depth=len(seq), init=pack_mem(seq*20, 20))
        m.submodules.pattern_rport = rport = pattern.read_port(domain="tx")

        counter = Signal(range(len(seq) + 1))
        with m.If(counter == (len(seq) - 1)):
            m.d.tx += counter.eq(0) 
        with m.Else():
            m.d.tx += counter.eq(counter + 1) 

        m.d.comb += [
            rport.addr.eq(counter),
            serdes.tx_data.eq(rport.data)
        ]
        return m

if __name__ == '__main__':
    with hardware.use(sys.argv[1]) as platform:
        platform().build(CWOutExample(), do_program=True)