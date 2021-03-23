# alldigitalradio - A toolbox for creating entirely digital radios using nmigen.

This is a collection of functional components used to build digital radios that use direct RF sampling at one bit of precision using SERDES transceivers on FPGAs. It was initially broken out of the [onebitbt](https://github.com/newhouseb/onebitbt) repository so that components oculd be reused in other kinds of radios (i.e. low-speed WiFi). it is far from perfect and is expected to evolve fairly quickly. If you want to use it, I'd suggest forking it so that you aren't caught off guard when an interface changes.

# Getting started.

First, install dependencies (ideally in a python3 virtual environment)

```
pip install numpy scipy jupyterlab
pip install git+https://github.com/nmigen/nmigen
```

**Pro-tip:** if you want to hack on this repository, I'd recomment cloning it and then doing:

```
pip install +e [path to checkout]
```

This will allow you to depend on this package from another project and edit this package live without needing to reinstall.

Next (if you have the same TE0714 hardware as I) you can run simple examples like:

```
python -m alldigitalradio.examples.cw_out te0714 # Transmits a 2.5Ghz constant wave on the SERDES TX
python -m alldigitalradio.examples.loopback te0714 # Transmits whatever is received back out.
```

# Documentation / How To

For the various building blocks, you can refer to the notebooks in the `research` directory.

- [Downconversion](https://github.com/newhouseb/alldigitalradio/blob/main/research/Downconversion.ipynb) - Conversion from a carrier-modulated signal to baseband (with 1-bit signals)
- [Filtering](https://github.com/newhouseb/alldigitalradio/blob/main/research/Filtering.ipynb) - Comically simple filtering.
- [Synchronization](https://github.com/newhouseb/alldigitalradio/blob/main/research/Synchronization.ipynb) - Symbol synchronization.
- [Trigonometry](https://github.com/newhouseb/alldigitalradio/blob/main/research/Trigonometry.ipynb) - Computing the magnitude of a complext signal.
- [Shift Registers](https://github.com/newhouseb/alldigitalradio/blob/main/research/ShiftRegisters.ipynb) - Shift registers underpinning whitening and CRC checking.
- [Parsing](https://github.com/newhouseb/alldigitalradio/blob/main/research/Parsing.ipynb) - Not nmigen, but just generic Python utilities to parse and generate arbitrary packets.

# Credits

The Xilinx SERDES implemenation is derived from the migen [implementation](https://github.com/enjoy-digital/liteiclink/blob/master/liteiclink/serdes/gtp_7series.py) in [liteiclink](https://github.com/enjoy-digital/liteiclink).
