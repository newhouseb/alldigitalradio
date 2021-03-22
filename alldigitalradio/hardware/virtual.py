import subprocess
import os
import sys

from alldigitalradio.io.generic_serdes import GenericSerdes 
from nmigen import Signal, Module, ClockDomain, ClockSignal
from nmigen.build import Resource, Pins, Attrs
from nmigen.back import verilog

HARNESS = """
#include "Vtop.h"
#include <cstdio>
#include <vector>
#include "verilated_vcd_c.h"

int main(int argc, char** argv) {
	Verilated::traceEverOn(true);
	VerilatedVcdC* tfp = new VerilatedVcdC;
	Vtop top;
	top.trace(tfp, 0);
	tfp->open("sim.vcd");

    printf("Reading %s\\n", argv[1]);

	FILE *fp;
	fp = fopen(argv[1], "r");

    if (fp == NULL) {
        printf("Failed to find file\\n");
    }

	FILE *out;
	out = fopen("out.txt", "w");

	uint32_t input = 0;
	int bit = 0;

	uint64_t time = 0;

	int c;
	while (fp) {
		c = fgetc(fp);

		if (feof(fp)) {
			break;
		}
		if (c == '1') {
			input |= (1 << bit);
		}
		if (bit == 19) {

			top.rx_data = input;
			top.rx_clock = 0;
			top.eval();
			tfp->dump(time++);

			top.clk = (((time - 1) % 20) < 10) ? 1 : 0;

			top.rx_clock = 1;
			top.eval();
			tfp->dump(time++);

			top.clk = (((time - 1) % 20) < 10) ? 1 : 0;
			
			bit = 0;
			input = 0;
		} else {
			bit += 1;
		}
	}

	tfp->close();
	fclose(out);

    printf("Simulation Complete!\\n");

	return 0;
}
"""

def load():
    class VirtualSerdes(GenericSerdes):
        def elaborate(self, platform):
            m = Module()
            m.domains += ClockDomain("rx", reset_less=True)
            m.d.comb += ClockSignal("rx").eq(self.rx_clock)
            return m

    class VirtualPlatform(object):
        def build(self, module, **kwargs):
            # TODO: mkdir build
            with open('build/top.v', 'w') as f:
                f.write(verilog.convert(module, ports=[module.serdes.rx_data, module.serdes.rx_clock, module.uart.tx_o]))

            os.chdir('build')
            with open('main.cpp', 'w') as f:
                f.write(HARNESS)

            subprocess.check_call([
                'verilator',
                '-Wno-fatal',
                '--trace', 
                '-cc',
                '--exe',
                'top.v',
                'main.cpp'
            ])

            subprocess.check_call(['make', '-C', 'obj_dir/', '-f', 'Vtop.mk'])
            subprocess.check_call(['./obj_dir/Vtop', sys.argv[2]])

    return (VirtualPlatform, VirtualSerdes)
