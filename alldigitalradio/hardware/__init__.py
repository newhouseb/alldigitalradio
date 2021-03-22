from contextlib import contextmanager

import alldigitalradio.hardware.trenz_te0714 as te0714
import alldigitalradio.hardware.virtual as virtual
import alldigitalradio.io.generic_serdes

platforms = {
    'te0714': te0714.load,
    'virtual': virtual.load
}

@contextmanager
def use(name, **kwargs):
    platform, serdes = platforms[name]()
    alldigitalradio.io.generic_serdes.default_serdes = serdes
    yield platform
    alldigitalradio.io.generic_serdes.default_serdes = None
