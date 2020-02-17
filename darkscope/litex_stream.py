# This file is Copyright (c) 2015 Sebastien Bourdeauducq <sb@m-labs.hk>
# This file is Copyright (c) 2015-2020 Florent Kermarrec <florent@enjoy-digital.fr>
# This file is Copyright (c) 2018 Tim 'mithro' Ansell <me@mith.ro>
# This file is Copyright (c) 2020 Andrew Wygle <me@awygle.com>
# License: BSD

import math

from nmigen.compat.genlib.record import Record, DIR_M_TO_S, DIR_S_TO_M, layout_len
#from nmigen.hdl.rec import Record, DIR_FANOUT, DIR_FANIN, DIR_NONE, Layout
from functools import reduce

from nmigen import Elaboratable, Signal
from nmigen import Module
from nmigen.lib import fifo

# Endpoint -----------------------------------------------------------------------------------------

(DIR_SINK, DIR_SOURCE) = range(2)

def _make_m2s(layout):
    r = []
    for f in layout:
        if isinstance(f[1], (int, tuple)):
            r.append((f[0], f[1], DIR_M_TO_S))
        else:
            r.append((f[0], _make_m2s(f[1])))
    return r


class EndpointDescription:
    def __init__(self, payload_layout, param_layout=[]):
        self.payload_layout = payload_layout
        self.param_layout   = param_layout

    def get_full_layout(self):
        reserved   = {"valid", "ready", "payload", "param", "first", "last", "description"}
        attributed = set()
        for f in self.payload_layout + self.param_layout:
            if f[0] in attributed:
                raise ValueError(f[0] + " already attributed in payload or param layout")
            if f[0] in reserved:
                raise ValueError(f[0] + " cannot be used in endpoint layout")
            attributed.add(f[0])

        full_layout = [
            ("valid",   1, DIR_M_TO_S),
            ("ready",   1, DIR_S_TO_M),
            ("first",   1, DIR_M_TO_S),
            ("last",    1, DIR_M_TO_S),
            ("payload", _make_m2s(self.payload_layout)),
            ("param",   _make_m2s(self.param_layout))
        ]
        return full_layout


class Endpoint(Record):
    def __init__(self, description_or_layout, name=None, **kwargs):
        if isinstance(description_or_layout, EndpointDescription):
            self.description = description_or_layout
        else:
            self.description = EndpointDescription(description_or_layout)
        Record.__init__(self, self.description.get_full_layout(), name, **kwargs)

    def __getattr__(self, name):
        try:
            return getattr(object.__getattribute__(self, "payload"), name)
        except:
            return getattr(object.__getattribute__(self, "param"), name)


# FIFO ---------------------------------------------------------------------------------------------

class _FIFOWrapper(Elaboratable):
    def __init__(self, layout, depth, fifo_class, buffered=False):
        self.sink   = sink   = Endpoint(layout)
        self.source = source = Endpoint(layout)
        
        self.fifo_class = fifo_class
        
        self.layout = layout
        self.depth = depth
        

    def elaborate(self, platform):
        m = Module()
        
        description = self.sink.description
        fifo_layout = [
            ("payload", description.payload_layout),
            ("param",   description.param_layout),
            ("first",   1),
            ("last",    1)
        ]
        
        if description.param_layout != []:
            fifo_layout += ("param", description.param_layout)

        fifo_in  = Record(fifo_layout)
        fifo_out = Record(fifo_layout)
        #m.submodules.fifo = fifo = self.fifo_class(width=fifo_in.shape().width, depth=self.depth)
        m.submodules.fifo = fifo = self.fifo_class(width=layout_len(fifo_layout), depth=self.depth)
        m.d.comb += [
            fifo.w_data.eq(fifo_in.raw_bits()),
            fifo_out.raw_bits().eq(fifo.r_data)
        ]

        m.d.comb += [
            self.sink.ready.eq(fifo.w_rdy),
            fifo.w_en.eq(self.sink.valid),
            fifo_in.first.eq(self.sink.first),
            fifo_in.last.eq(self.sink.last),
            fifo_in.payload.eq(self.sink.payload),

            self.source.valid.eq(fifo.r_rdy),
            self.source.first.eq(fifo_out.first),
            self.source.last.eq(fifo_out.last),
            self.source.payload.eq(fifo_out.payload),
            fifo.r_en.eq(self.source.ready),
        ]
        
        if description.param_layout != []:
            m.d.comb += [
                fifo_in.param.eq(self.sink.param),
                self.source.param.eq(fifo_out.param),
             ]

        return m

class SyncFIFO(_FIFOWrapper):
    def __init__(self, layout, depth, buffered=False):
        fifo_class = fifo.SyncFIFOBuffered if buffered else fifo.SyncFIFO
        _FIFOWrapper.__init__(self, layout, depth, fifo_class, buffered)
        
        self.level = Signal(range(depth + 1))
    
    def elaborate(self, platform):
        m = super().elaborate(platform)
        
        m.d.comb += self.level.eq(m.submodules.fifo.level)
        
        return m

class AsyncFIFO(_FIFOWrapper):
    def __init__(self, layout, depth, buffered=False):
        fifo_class = fifo.AsyncFIFOBuffered if buffered else fifo.AsyncFIFO
        _FIFOWrapper.__init__(self, layout, depth, fifo_class, buffered)


# Pipeline -----------------------------------------------------------------------------------------

class Pipeline(Elaboratable):
    def __init__(self, *modules):
        self._modules = modules
    
    def elaborate(self, platform):
        mod = Module()
        
        n = len(self._modules)
        m = self._modules[0]
        # expose sink of first module
        # if available
        if hasattr(m, "sink"):
            self.sink = m.sink
        for i in range(1, n):
            m_n = self._modules[i]
            if isinstance(m, Endpoint):
                source = m
            else:
                source = m.source
            if isinstance(m_n, Endpoint):
                sink = m_n
            else:
                sink = m_n.sink
            if m is not m_n:
                mod.d.comb += source.connect(sink)
            m = m_n
        # expose source of last module
        # if available
        if hasattr(m, "source"):
            self.source = m.source
            
        return mod

