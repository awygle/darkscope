# This file is Copyright (c) 2016-2019 Florent Kermarrec <florent@enjoy-digital.fr>
# This file is Copyright (c) 2018 bunnie <bunnie@kosagi.com>
# This file is Copyright (c) 2016 Tim 'mithro' Ansell <mithro@mithis.com>
# License: BSD

from nmigen import *
from nmigen.hdl import *
from nmigen.hdl.dsl import FSM
from nmigen.lib.cdc import FFSynchronizer
from nmigen.lib.fifo import AsyncFIFO as NAsyncFIFO
from nmigen.utils import bits_for

from .migen_compat import WaitTimer

def write_to_file(filename, contents, force_unix=False):
    newline = None
    if force_unix:
        newline = "\n"
    old_contents = None
    if os.path.exists(filename):
        with open(filename, "r", newline=newline) as f:
            old_contents = f.read()
    if old_contents != contents:
        with open(filename, "w", newline=newline) as f:
            f.write(contents)

from .litex_stream import Endpoint, Pipeline, SyncFIFO, AsyncFIFO

# DarkScope Analyzer -------------------------------------------------------------------------------

def core_layout(data_width):
    return [("data", data_width), ("hit", 1)]


class _Trigger(Elaboratable):
    def __init__(self, data_width, depth=16):
        self.sink   = sink   = Endpoint(core_layout(data_width))
        self.source = source = Endpoint(core_layout(data_width))

        self.enable = Signal()
        self.done   = Signal()

        self.mem_write = Signal()
        self.mem_mask  = Signal(data_width)
        self.mem_value = Signal(data_width)
        self.mem_full  = Signal()
        
        self._data_width = data_width
        self._depth = depth


    def elaborate(self, platform):
        m = Module()

        # Control re-synchronization
        enable   = Signal()
        enable_d = Signal()
        m.submodules += FFSynchronizer(self.enable, enable, o_domain="scope")
        m.d.scope += enable_d.eq(enable)

        # Status re-synchronization
        done = Signal()
        m.submodules += FFSynchronizer(done, self.done)

        # Memory and configuration
        mem_write_last = Signal()
        m.d.sync += mem_write_last.eq(self.mem_write)
        
        mem = AsyncFIFO([("mask", self._data_width), ("value", self._data_width)], self._depth)
        mem = DomainRenamer({"write": "sync", "read": "scope"})(mem)
        m.submodules += mem
        m.d.comb += [
            mem.sink.valid.eq(~mem_write_last & self.mem_write),
            mem.sink.payload.mask.eq(self.mem_mask),
            mem.sink.payload.value.eq(self.mem_value),
            self.mem_full.eq(~mem.sink.ready)
        ]

        # Hit and memory read/flush
        hit   = Signal()
        flush = WaitTimer(2*self._depth)
        m.submodules += flush
        m.d.comb += [
            flush.wait.eq(~(~enable & enable_d)), # flush when disabling
            hit.eq((self.sink.payload.data & mem.source.payload.mask) == mem.source.payload.value),
            mem.source.ready.eq((enable & hit) | ~flush.done),
        ]

        # Output
        m.d.comb += [
            self.sink.connect(self.source),
            # Done when all triggers have been consumed
            done.eq(~mem.source.valid),
            self.source.payload.hit.eq(done)
        ]
        
        return m


class _SubSampler(Elaboratable):
    def __init__(self, data_width):
        self.sink   = sink   = Endpoint(core_layout(data_width))
        self.source = source = Endpoint(core_layout(data_width))

        self.value = Signal(16)


    def elaborate(self, platform):
        m = Module()
        
        value = Signal(16)
        m.submodules += FFSynchronizer(self.value, value, o_domain="scope")

        counter = Signal(16)
        done    = Signal()
        with m.If(self.source.ready):
            with m.If(done):
                m.d.scope += counter.eq(0)
            with m.Elif(self.sink.valid):
                m.d.scope += counter.eq(counter + 1)

        m.d.comb += [
            done.eq(counter == value),
            self.sink.connect(self.source, omit={"valid"}),
            self.source.valid.eq(self.sink.valid & done)
        ]
        
        return m


class _Mux(Elaboratable):
    def __init__(self, data_width, n):
        self.sinks  = sinks  = [Endpoint(core_layout(data_width)) for i in range(n)]
        self.source = source = Endpoint(core_layout(data_width))

        self.value = Signal(bits_for(n))
        
        self._n = n

    def elaborate(self, platform):
        m = Module()
        
        value = Signal(self.value.shape())
        m.submodules += FFSynchronizer(self.value, value, o_domain="scope")

        cases = {}
        for i in range(self._n):
            cases[i] = self.sinks[i].connect(self.source)
        
        with m.Switch(value):
            for i in range(self._n):
                with m.Case(i):
                    m.d.comb += self.sinks[i].connect(self.source)
        
        return m


class _Storage(Elaboratable):
    def __init__(self, data_width, depth):
        self.sink = sink = Endpoint(core_layout(data_width))

        self.enable    = Signal()
        self.done      = Signal()

        self.length    = Signal(bits_for(depth))
        self.offset    = Signal(bits_for(depth))

        self.mem_valid = Signal()
        self.mem_data  = Signal(data_width)
        self.mem_data_read  = Signal()
        
        self._data_width = data_width
        self._depth = depth

    def elaborate(self, platform):
        m = Module()
        
        # Control re-synchronization
        enable   = Signal()
        enable_d = Signal()
        m.submodules += FFSynchronizer(self.enable, enable, o_domain="scope")
        m.d.scope += enable_d.eq(enable)

        length = Signal(range(self._depth))
        offset = Signal(range(self._depth))
        m.submodules += [
            FFSynchronizer(self.length, length, o_domain="scope"),
            FFSynchronizer(self.offset, offset, o_domain="scope")
        ]

        # Status re-synchronization
        done = Signal()
        m.submodules += FFSynchronizer(done, self.done)

        # Memory
        mem = SyncFIFO([("data", self._data_width)], self._depth, buffered=True)
        mem = DomainRenamer("scope")(mem)
        cdc = AsyncFIFO([("data", self._data_width)], 4)
        cdc = DomainRenamer(
            {"write": "scope", "read": "sync"})(cdc)
        m.submodules += mem, cdc

        # Flush
        mem_flush = WaitTimer(self._depth)
        mem_flush = DomainRenamer("scope")(mem_flush)
        m.submodules += mem_flush
        
        # FSM
        with m.FSM(reset="IDLE", domain="scope") as fsm:
            with m.State("IDLE"):
                m.d.comb += done.eq(1)
                with m.If(enable & ~enable_d):
                    m.next = "FLUSH"
                m.d.comb += self.sink.ready.eq(1)
                m.d.comb += mem.source.connect(cdc.sink)
            with m.State("FLUSH"):
                m.d.comb += self.sink.ready.eq(1),
                m.d.comb += mem_flush.wait.eq(1)
                m.d.comb += mem.source.ready.eq(1)
                with m.If(mem_flush.done):
                    m.next = "WAIT"
            with m.State("WAIT"):
                m.d.comb += self.sink.connect(mem.sink, omit={"hit"})
                with m.If(self.sink.valid & self.sink.payload.hit):
                    m.next = "RUN"
                m.d.comb += mem.source.ready.eq(mem.level >= self.offset)
            with m.State("RUN"):
                m.d.comb += self.sink.connect(mem.sink, omit={"hit"})
                with m.If(mem.level >= self.length):
                    m.next = "IDLE"


        # Memory read
        mem_data_read_last = Signal()
        m.d.sync += mem_data_read_last.eq(self.mem_data_read)

        m.d.comb += [
            self.mem_valid.eq(cdc.source.valid),
            cdc.source.ready.eq((~mem_data_read_last & self.mem_data_read) | ~self.enable),
            self.mem_data.eq(cdc.source.payload.data)
        ]
        
        return m


class DarkScopeAnalyzer(Elaboratable):
    def __init__(self, groups, depth, clock_domain="sync", trigger_depth=16, csr_csv=None):
        self.groups = groups = self.format_groups(groups)
        self.depth  = depth

        self.data_width = data_width = max([sum([len(s) for s in g]) for g in groups.values()])

        self.csr_csv = csr_csv
        
        self._clock_domain = clock_domain
        self._trigger_depth = trigger_depth

        # # #
    def elaborate(self, platform):
        m = Module()

        # Create scope clock domain
        m.domains += ClockDomain("scope")
        m.d.comb += ClockSignal(domain="scope").eq(ClockSignal(self._clock_domain))

        # Mux
        m.submodules.mux = self.mux = _Mux(self.data_width, len(self.groups))
        for i, signals in self.groups.items():
            m.d.comb += [
                m.submodules.mux.sinks[i].valid.eq(1),
                m.submodules.mux.sinks[i].payload.data.eq(Cat(signals))
            ]

        # Frontend
        m.submodules.trigger = self.trigger = _Trigger(self.data_width, depth=self._trigger_depth)
        m.submodules.subsampler = self.subsampler = _SubSampler(self.data_width)

        # Storage
        m.submodules.storage = self.storage = _Storage(self.data_width, self.depth)

        # Pipeline
        m.submodules.pipeline = Pipeline(
            m.submodules.mux.source,
            m.submodules.trigger,
            m.submodules.subsampler,
            m.submodules.storage.sink)
        
        return m

    def format_groups(self, groups):
        if not isinstance(groups, dict):
            groups = {0 : groups}
        new_groups = {}
        for n, signals in groups.items():
            if not isinstance(signals, list):
                signals = [signals]

            split_signals = []
            for s in signals:
                if isinstance(s, Record):
                    split_signals.extend(s.flatten())
                elif isinstance(s, type(FSM)):
                    s.do_finalize()
                    s.finalized = True
                    split_signals.append(s.state)
                else:
                    split_signals.append(s)
            new_groups[n] = split_signals
        return new_groups

    def export_csv(self, vns, filename):
        def format_line(*args):
            return ",".join(args) + "\n"
        r = format_line("config", "None", "data_width", str(self.data_width))
        r += format_line("config", "None", "depth", str(self.depth))
        for i, signals in self.groups.items():
            for s in signals:
                r += format_line("signal", str(i), vns.get_name(s), str(len(s)))
        write_to_file(filename, r)

    def do_exit(self, vns):
        if self.csr_csv is not None:
            self.export_csv(vns, self.csr_csv)
