from nmigen import Elaboratable, Signal, Module, Memory
from alldigitalradio.io.numpy import make_callable
import numpy as np

class SymbolTable(Elaboratable):
    def __init__(self, table=None, packet=None, samples_per_symbol=1, tx_domain="tx"):
        """
            table is a list of deserialized 20-bit words that represent a symbol table
            packet is the symbol indexes to send (in a Memory, not yet multiplied by samples_per_symbol)
            samples_per_symbol is the number of bits per symbol at the TX output bit rate
            tx_domain is the name of the domain used to clock the SERDES TX
        """
        print(table)
        self.table = Memory(width=20, depth=len(table), init=table)
        self.samples_per_symbol = samples_per_symbol
        self.tx_domain = tx_domain
        self.packet = packet

        # Inputs
        self.packet_length = Signal(16)
        self.tx_reset = Signal()

        # Outputs
        self.tx_data = Signal(20)
        self.tx_done = Signal(reset=1) # Goes high when transmit has completed

    def elaborate(self, platform):
        m = Module()

        m.submodules.symbol_idx = symbol_idx = self.packet.read_port(domain=self.tx_domain)
        m.submodules.symbol_samples = symbol_samples = self.table.read_port(domain=self.tx_domain)

        domain = getattr(m.d, self.tx_domain)

        sample_index = Signal(range(self.samples_per_symbol//20))
        last_sample_index = Signal(range(self.samples_per_symbol//20))
        packet_index = Signal(16)

        # Reset going high unsets done and resets counters
        with m.If(self.tx_reset):
            domain += [
                self.tx_done.eq(0),
            ]

        with m.Else():
            # If we're not done
            with m.If(self.tx_done == 0):
                # If we're at the end of a symbol
                with m.If(sample_index == (self.samples_per_symbol//20 - 1)):
                    # If we're done with all symbols, stop doing things
                    with m.If(packet_index >= self.packet_length - 1):
                        domain += [
                            self.tx_done.eq(1),
                            sample_index.eq(0),
                            packet_index.eq(0)
                        ]
                    # Otherwise move to the next symbol
                    with m.Else():
                        domain += [
                            sample_index.eq(0),
                            packet_index.eq(packet_index + 1)
                        ]
                # Otherwise fetch the next symbol
                with m.Else():
                    domain += sample_index.eq(sample_index + 1)

                # Wire up the outputs of the sample to the right places
                domain += [
                    # We need to delay the sample_index because we need to pull the base symbol idx
                    # from memory which takes a cycle
                    last_sample_index.eq(sample_index),
                ]
                m.d.comb += [
                    symbol_idx.addr.eq(packet_index),
                    self.tx_data.eq(symbol_samples.data),
                    symbol_samples.addr.eq((symbol_idx.data * self.samples_per_symbol//20) + last_sample_index),
                ]

            # If we are done, output zeros
            # TODO: This will zero out the output before the pipeline has fully pushed through
            # this is only a couple clock cycles worth of data so not a huge deal but would be good to
            # properly transmit _all_ the data
            with m.Else():
                m.d.comb += self.tx_data.eq(0)

        return m

def test_symbol_table():
    st = SymbolTable(
        table=[i for i in range(100)], 
        packet=Memory(width=16, depth=5, init=[1,2,3,4,5]),
        samples_per_symbol=10*20,
        tx_domain="sync")
    st = make_callable(st, inputs=[st.tx_reset, st.packet_length], outputs=[st.tx_data, st.tx_done])

    # This should output an incrementing output symbol a couple cycles delayed until we get done
    print(st(1, 5))
    for i in range(100):
        out, done = st(0, 5)
        print(i, out, done)
        if done:
            break
        if i > 2:
            assert(i + 10 - 2 == out)

    # Do it again to test reset logic
    print(st(1, 5))
    for i in range(100):
        out, done = st(0, 5)
        print(i, out, done)
        if done:
            break
        if i > 2:
            assert(i + 10 - 2 == out)