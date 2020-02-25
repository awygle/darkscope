from nmigen import *
from nmigen.hdl.ir import *
from nmigen.cli import main
from nmigen_boards.versa_ecp5 import *
from nmigen_boards.test.blinky import *

from darkscope.nmigen_stream import *
from nmigen_stdio.uart import UART

class Top(Elaboratable):
    def __init__(self):
        pass
        
    def elaborate(self, platform):
        clk_freq = platform.default_clk_frequency
        baud = 9600
        divisor = round(clk_freq / baud)
        
        m = Module()
        
        m.submodules.uart = uart = UART(divisor)
        m.submodules.blink = blink = Blinky()
        m.submodules.fifo = fifo = SyncFIFOStream(uart.layout, 4)
        
        uart_pins = platform.request("uart")
        
        m.d.comb += uart.tx.connect(fifo.source)
        m.d.comb += fifo.sink.connect(uart.rx)
        
        m.d.comb += [
                
                uart_pins.tx.o.eq(uart.tx_o),
                uart.rx_i.eq(uart_pins.rx.i),
                
                ]

        
        return m

if __name__ == "__main__":
    platform = VersaECP5Platform()
    top = Top()
    platform.build(top, do_program=True)
