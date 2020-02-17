from nmigen import *
from nmigen.utils import bits_for

class WaitTimer(Elaboratable):
    def __init__(self, t):
        self.wait = Signal()
        self.done = Signal()
        
        self._t = t

    def elaborate(self, platform):
        m = Module()

        count = Signal(bits_for(self._t), reset=self._t)
        m.d.comb += self.done.eq(count == 0)
        with m.If(self.wait):
            with m.If(~self.done):
                m.d.sync += count.eq(count - 1)
            with m.Else():
                m.d.sync += count.eq(count.reset)

        return m

