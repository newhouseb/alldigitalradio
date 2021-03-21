from boards.trenz import TE0714

from nmigen import Elaboratable, Module
from nmigen.build import Resource, Pins, Attrs

from alldigitalradio.io.xilinx_gtp import XilinxGTPSerdes

class CWOutExample(Elaboratable):
    def elaborate(self, platform):
        m = Module()
        m.submodules.serdes = serdes = XilinxGTPSerdes()
        m.d.comb += serdes.tx_data.eq(serdes.rx_data)
        return m

TE0714.resources += [
    Resource("clk_n", 0, Pins("B5", dir="i"), Attrs(IOSTANDARD="LVDS_25")),
    Resource("clk_p", 0, Pins("B6", dir="i"), Attrs(IOSTANDARD="LVDS_25")), 

    Resource("tx_n", 0, Pins("B1")),
    Resource("tx_p", 0, Pins("B2")),

    Resource("rx_n", 0, Pins("G3")),
    Resource("rx_p", 0, Pins("G4"))
]

if __name__ == '__main__':
    TE0714().build(CWOutExample(), do_program=True)