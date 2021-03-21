import sys

from nmigen import Elaboratable, Module
from nmigen.build import Resource, Pins, Attrs

from alldigitalradio.io.generic_serdes import get_serdes_implementation
import alldigitalradio.hardware as hardware

class CWOutExample(Elaboratable):
    def elaborate(self, platform):
        m = Module()
        m.submodules.serdes = serdes = get_serdes_implementation()()
        m.d.comb += serdes.tx_data.eq(0b10101010101010101010)
        return m

if __name__ == '__main__':
    with hardware.use(sys.argv[1]) as platform:
        platform().build(CWOutExample(), do_program=True)
