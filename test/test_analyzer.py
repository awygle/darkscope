# This file is Copyright (c) 2017-2019 Florent Kermarrec <florent@enjoy-digital.fr>
# License: BSD

import unittest

from nmigen import *
from nmigen.back.pysim import *

from darkscope import DarkScopeAnalyzer


class TestAnalyzer(unittest.TestCase):
    def test_analyzer(self):
        dut = Module()
        counter = Signal(16)
        dut.d.sync += counter.eq(counter + 1)
        dut.submodules.analyzer = DarkScopeAnalyzer(counter, 512)
        
        sim = Simulator(dut)
        sim.add_clock(1e-6, domain="scope")
        sim.add_clock(1e-6, domain="sync")
        def process():
            data = []
            yield Tick()
            # Configure Trigger
            yield dut.submodules.analyzer.trigger.mem_value.eq(0x0010)
            yield dut.submodules.analyzer.trigger.mem_mask.eq(0xffff)
            yield dut.submodules.analyzer.trigger.mem_write.eq(1)

            # Configure Subsampler
            yield dut.submodules.analyzer.subsampler.value.eq(2)

            # Configure Storage
            yield dut.submodules.analyzer.storage.length.eq(256)
            yield dut.submodules.analyzer.storage.offset.eq(8)
            yield dut.submodules.analyzer.storage.enable.eq(1)
            yield Tick()
            for i in range(16):
                yield Tick()
            # Wait capture
            while not (yield dut.submodules.analyzer.storage.done):
                yield Tick()
            yield Tick()
            # Reade captured datas
            while (yield dut.submodules.analyzer.storage.mem_valid):
                yield dut.submodules.analyzer.storage.mem_data_read.eq(1)
                data.append((yield dut.submodules.analyzer.storage.mem_data))
                yield Tick()
                yield dut.submodules.analyzer.storage.mem_data_read.eq(0)
                yield Tick()
            self.assertEqual(data, [518 + 3*i for i in range(256)])
        sim.add_process(process)
        sim.run()
        
