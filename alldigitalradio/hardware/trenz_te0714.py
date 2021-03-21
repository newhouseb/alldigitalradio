from alldigitalradio.io.xilinx_gtp import XilinxGTPSerdes
from nmigen.build import Resource, Pins, Attrs

def load():
    from boards.trenz import TE0714

    TE0714.resources += [
        Resource("clk_n", 0, Pins("B5", dir="i"), Attrs(IOSTANDARD="LVDS_25")),
        Resource("clk_p", 0, Pins("B6", dir="i"), Attrs(IOSTANDARD="LVDS_25")), 

        Resource("tx_n", 0, Pins("B1")),
        Resource("tx_p", 0, Pins("B2")),

        Resource("rx_n", 0, Pins("G3")),
        Resource("rx_p", 0, Pins("G4"))
    ]

    return (TE0714, XilinxGTPSerdes)
