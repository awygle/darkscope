import unittest

from nmigen import *
from nmigen.back.pysim import *

from darkscope.nmigen_stream import *


class TestStream(unittest.TestCase):
    def test_smoke(self):
        dut = Module()
        
        testtype = Layout([("eggs", 1)])
        source = StreamSource(testtype)
        sink = StreamSink(testtype)
        
        dut.d.sync += sink.connect(source)
        
        sim = Simulator(dut)
        sim.add_clock(1e-6, domain="sync")
        def process():
            for i in range(512):
                yield Tick()
        sim.add_process(process)
        sim.run()
        
    def test_fifo(self):
        dut = Module()
        counter = Record([("value", 16)])
        dut.d.sync += counter.eq(counter + 1)
        dut.submodules.fifo = fifo = SyncFIFOStream(counter.layout, 4)
        
        source = StreamSource(counter.layout)
        sink = StreamSink(counter.layout)
        dut.d.comb += source.data.eq(counter)
        dut.d.comb += sink.ready.eq(1)
        
        dut.d.comb += fifo.sink.connect(source)
        dut.d.comb += sink.connect(fifo.source)
        
        sim = Simulator(dut)
        sim.add_clock(1e-6, domain="sync")
        def input_process():
            yield Tick()
            
            # 129 is because we add a single clock of latency for writing to the FIFO
            for i in range(129):
                yield source.valid.eq(1)
                yield Tick()
                yield source.valid.eq(0)
                yield Tick()

        def output_process():
            data = []
            yield Tick()
            
            # 129 is because we add a single clock of latency for writing to the FIFO
            for i in range(129):
                if (yield sink.valid):
                    data.append((yield sink.data))
                yield Tick()
            self.assertEqual(data, [i for i in range(1, 128, 2)])
        sim.add_process(input_process)
        sim.add_process(output_process)
        sim.run()
        
    def test_fifo_async(self):
        dut = Module()
        counter = Record([("value", 16)])
        dut.d.sync += counter.eq(counter + 1)
        f = AsyncFIFOStream(counter.layout, 4)
        f = DomainRenamer({"write": "sync"})(f)
        dut.submodules.fifo = fifo = f
        
        source = StreamSource(counter.layout)
        sink = StreamSink(counter.layout)
        dut.d.comb += source.data.eq(counter)
        dut.d.comb += sink.ready.eq(1)
        
        dut.d.comb += fifo.sink.connect(source)
        dut.d.comb += sink.connect(fifo.source)
        
        sim = Simulator(dut)
        sim.add_clock(1e-6, domain="sync")
        sim.add_clock(1e-6, domain="read")
        def input_process():
            yield Tick()
            
            # tuned for async FIFO latency... need to double-check this later
            for i in range(131):
                yield source.valid.eq(1)
                yield Tick()
                yield source.valid.eq(0)
                yield Tick()

        def output_process():
            data = []
            yield Tick()
            
            # tuned for async FIFO latency - need to double-check this later
            for i in range(131):
                if (yield sink.valid):
                    data.append((yield sink.data))
                yield Tick()
            self.assertEqual(data, [i for i in range(1, 128, 2)])
        sim.add_process(input_process)
        sim.add_process(output_process)
        sim.run()
        
    def test_joiner(self):
        dut = Module()
        counter = Record([("value", 16)])
        dut.d.sync += counter.eq(counter + 1)
        dut.submodules.fifo = fifo = SyncFIFOStream(counter.layout, 4)
        
        source = StreamSource(counter.layout)
        sink = StreamSink(counter.layout)
        dut.d.comb += source.data.eq(counter)
        dut.d.comb += sink.ready.eq(1)
        
        dut.d.comb += fifo.sink.connect(source)
        dut.d.comb += sink.connect(fifo.source)
        
        dut.submodules.joiner = StreamJoiner([source])
        
        sim = Simulator(dut)
        sim.add_clock(1e-6, domain="sync")
        def input_process():
            yield Tick()
            
            # 129 is because we add a single clock of latency for writing to the FIFO
            for i in range(129):
                yield source.valid.eq(1)
                yield Tick()
                yield source.valid.eq(0)
                yield Tick()

        def output_process():
            data = []
            yield Tick()
            
            # 129 is because we add a single clock of latency for writing to the FIFO
            for i in range(129):
                if (yield sink.valid):
                    data.append((yield sink.data))
                yield Tick()
            self.assertEqual(data, [i for i in range(1, 128, 2)])
        sim.add_process(input_process)
        sim.add_process(output_process)
        sim.run()
        
    def test_buffer(self):
        dut = Module()
        counter = Record([("value", 16)])
        dut.d.sync += counter.eq(counter + 1)
        
        source = StreamSource(counter.layout)
        sink = StreamSink(counter.layout)
        
        dut.submodules.b = StreamBuffer(source, sink)
        
        dut.d.comb += source.data.eq(counter)
        dut.d.comb += sink.ready.eq(1)
        
        sim = Simulator(dut)
        sim.add_clock(1e-6, domain="sync")
        def input_process():
            yield Tick()
            
            # 129 is because we add a single clock of latency for writing to the buffer
            for i in range(129):
                yield source.valid.eq(1)
                yield Tick()
                yield source.valid.eq(0)
                yield Tick()

        def output_process():
            data = []
            yield Tick()
            
            # 129 is because we add a single clock of latency for writing to the buffer
            for i in range(129):
                if (yield sink.valid):
                    data.append((yield sink.data))
                yield Tick()
            self.assertEqual(data, [i for i in range(1, 128, 2)])
        sim.add_process(input_process)
        sim.add_process(output_process)
        sim.run()
