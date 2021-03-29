import numpy as np

from nmigen.sim import Simulator, Tick, Settle
from nmigen import *

def make_callable(m, startup_cycles=0, inputs=None, outputs=None):
    inputs = inputs or m.inputs()
    outputs = outputs or m.outputs()

    
    def gen():
        sim = Simulator(m)
        has_clock = True
        try:
            sim.add_clock(1e-6, domain="sync")
        except ValueError:
            has_clock = False
        
        next_inputs = [0]*len(inputs)
        next_outputs = [0]*len(outputs)
        iteration = [0]
        
        def input_receiver():
            next_input = yield
            yield next_input
        
        def process():
            while True:
                for i in range(len(inputs)):
                    yield inputs[i].eq(next_inputs[i])
                if has_clock:
                    yield Tick()
                for i in range(len(outputs)):
                    next_outputs[i] = (yield outputs[i])
                iteration[0] += 1
                yield Settle()

        sim.add_process(process)
        
        last_iter = 0
        while True:
            # Receive the input
            received = yield
            for i in range(len(received)):
                next_inputs[i] = received[i]
            
            # Iterate until outputs are updated after a clock cycle
            while last_iter == iteration[0]:
                sim.advance()
                
            last_iter = iteration[0]
            if len(next_outputs) == 1:
                yield next_outputs[0]  
            else:
                yield next_outputs.copy()
        
    g = gen()
    for i in range(startup_cycles):
        next(g)
        g.send([0]*len(inputs))

    def tick(*inputs):
        next(g)
        return g.send(inputs)
    return tick

def take_n(f, n):
    return np.array([f() for _ in range(n)])

def test_make_callable():
    class Doubler(Elaboratable):
        def __init__(self):
            self.input = Signal(8)
            self.output = Signal(8)
            self.sync_output = Signal(8)
        
        def elaborate(self, platform):
            m = Module()
            m.d.comb += self.output.eq(self.input << 1)
            m.d.sync += self.sync_output.eq(self.input << 1)
            return m
        
    doubler = Doubler()
    doubler = make_callable(doubler, 
        inputs=[doubler.input], 
        outputs=[doubler.output, doubler.sync_output])

    assert doubler(1) == [2, 0]
    assert doubler(2) == [4, 2]
    assert doubler(2) == [4, 4]
