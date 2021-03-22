import os

from alldigitalradio.io.generic_serdes import GenericSerdes 
from nmigen import Signal
from nmigen.build import Resource, Pins, Attrs
from nmigen.back import verilog

def load():
    class VirtualPlatform(object):
        def build(self, module, **kwargs):
            with open('build/top.v', 'w') as f:
                f.write(verilog.convert(module, ports=[module.serdes.rx_data, module.uart.tx_o]))
        def request(self, *args, **kwargs):
            return Signal()

    return (VirtualPlatform, GenericSerdes)
