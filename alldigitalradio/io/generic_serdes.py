from nmigen import Elaboratable, Signal

class GenericSerdes(Elaboratable):
    def __init__(self, refclk_freq=125e6, line_rate=5e9):
        self.rx_data = Signal(20)
        self.rx_clock = Signal()

        self.tx_data = Signal(20)
        self.tx_clock = Signal()

default_serdes = None
def get_serdes_implementation():
    return default_serdes