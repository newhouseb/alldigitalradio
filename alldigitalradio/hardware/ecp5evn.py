from nmigen.build import Resource, Pins, Attrs
from alldigitalradio.io.ecp5 import ECP5Serdes 

def load():
    from nmigen_boards.ecp5_5g_evn import ECP55GEVNPlatform
    return (ECP55GEVNPlatform, ECP5Serdes)
