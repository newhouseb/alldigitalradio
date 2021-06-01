
from nmigen import *
import numpy as np

class MagnitudeApproximator(Elaboratable):
    def __init__(self, simple=False):
        self.simple = simple

        self.inputI = Signal(signed(32))
        self.inputQ = Signal(signed(32))

        self.magnitude = Signal(unsigned(32))

    def inputs(self):
        return [self.inputI, self.inputQ]

    def outputs(self):
        return [self.magnitude]

    def elaborate(self, platform):
        m = Module()

        if self.simple:
            m.d.comb += self.magnitude.eq(abs(self.inputI) + abs(self.inputQ))
        else:
            Iabs = Signal(unsigned(32))
            Qabs = Signal(unsigned(32))
            m.d.comb += [
                Iabs.eq(abs(self.inputI)),
                Qabs.eq(abs(self.inputQ)),
            ]

            maxs = lambda a, b: Mux(a > b, a, b)
            mins = lambda a, b: Mux(a < b, a, b)

            a = Signal(signed(32))
            b = Signal(signed(32))
            m.d.comb += [
                a.eq(maxs(Iabs, Qabs)),
                b.eq(mins(Iabs, Qabs)),
            ]

            m.d.comb += self.magnitude.eq(maxs((a - (a >> 8)) + (b >> 1), a))

        return m

class Cordic(Elaboratable):
    """
    This is a pipelined CORDIC implementation that computes
    one result per clock cycle at a latency dependent on the
    number of stages + 2.
    
    Note: there is no constant factor correction in this implementation
    """
    def __init__(self, bit_depth=16, stages=8, domain: str="sync"):
        self.bit_depth = bit_depth
        self.stages = stages
        self.domain = domain
        
        self.input_x = Signal(signed(bit_depth))
        self.input_y = Signal(signed(bit_depth))
        
        self.magnitude = Signal(signed(bit_depth))
        self.angle = Signal(signed(bit_depth))
        
        # Mostly useful for debugging more than anything else
        self.output_x = Signal(signed(bit_depth))
        self.output_y = Signal(signed(bit_depth))

        self.latency = stages + 2
        
    def elaborate(self, platform):
        m = Module()

        domain = getattr(m.d, self.domain)
        
        # First state flips the coordinates if necessaru such that the angle is [-90deg,90deg]
        input_x_flipped = Signal(signed(self.bit_depth))
        input_y_flipped = Signal(signed(self.bit_depth))
        flipped = Signal()
        with m.If(self.input_x < 0):
            domain += [
                input_x_flipped.eq(-self.input_x),
                input_y_flipped.eq(self.input_y),
                flipped.eq(1),
            ]
        with m.Else():
            domain += [
                input_x_flipped.eq(self.input_x),
                input_y_flipped.eq(self.input_y),
                flipped.eq(0)
            ]

        cur_x = input_x_flipped
        cur_y = input_y_flipped
        cur_flipped = flipped
        cur_angle = Signal(signed(self.bit_depth))
        K = 1
        
        # For a configurable number of stages rotate by arctan(2^-i)
        for i in range(self.stages):
            next_x = Signal(signed(self.bit_depth))
            next_y = Signal(signed(self.bit_depth))
            next_angle = Signal(signed(self.bit_depth))
            next_flipped = Signal()
            
            K *= np.cos(np.arctan(2**-i))
            angle = int(2**(self.bit_depth - 4)*np.arctan(2**-i))
            
            with m.If(cur_y < 0):
                domain += [
                    next_x.eq(cur_x - (cur_y >> i)),
                    next_y.eq(cur_y + (cur_x >> i)),
                    next_angle.eq(cur_angle - angle)
                ]
            with m.Else():
                domain += [
                    next_x.eq(cur_x + (cur_y >> i)),
                    next_y.eq(cur_y - (cur_x >> i)),
                    next_angle.eq(cur_angle + angle)
                ]
            
            domain += next_flipped.eq(cur_flipped)
            
            cur_x = next_x
            cur_y = next_y
            cur_angle = next_angle
            cur_flipped = next_flipped
            
        # Final stage flips the angle back if we flipped the coords at the start and makes
        # sure that the angle is positive (to make discontinuities more predictable)        
        with m.If(cur_flipped):
            domain += self.angle.eq(int(2**(self.bit_depth - 4)*np.pi) - cur_angle)
        with m.Else():
            with m.If(cur_angle < 0):
                domain += self.angle.eq(int(2**(self.bit_depth - 4)*2*np.pi) + cur_angle)
            with m.Else():
                domain += self.angle.eq(cur_angle)
            
        domain += [
            self.magnitude.eq(cur_x),
            self.output_x.eq(cur_x),
            self.output_y.eq(cur_y),
        ]
        
        return m