import sys

from nmigen import Elaboratable, Module
from nmigen.build import Resource, Pins, Attrs

from alldigitalradio.io.generic_serdes import get_serdes_implementation
import alldigitalradio.hardware as hardware

class LoopbackExample(Elaboratable):
    def elaborate(self, platform):
        m = Module()
        m.submodules.serdes = serdes = get_serdes_implementation()()
        m.d.comb += serdes.tx_data.eq(serdes.rx_data)
        return m

if __name__ == '__main__':
    with hardware.use(sys.argv[1]) as platform:
        platform().build(LoopbackExample(), do_program=True)