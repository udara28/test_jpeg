
from random import randint
from math import floor
import traceback

import myhdl
from myhdl import Signal, instance, always_comb

from jpegenc.interfaces import ObjectWithBlocks, DataStream
from .buffers import FIFOReadyValid


class ProcessingSubblock(ObjectWithBlocks):
    def __init__(self, cycles_to_process=1, pipelined=False, block_size=None, buffered=False):
        """A simple model to represent a processing subblock in the jpegenc

        Arguments:
            cycles_to_process (int): the number of cycles to model,
                this is the number of cycles to process a sample/block.

            pipelined (bool): indicates the processing block is fully
                pipelined, a new sample can be input on every clock.
                The pipeline length is the ``cycles_to_process``.

            block_size (tuple): the size of an image block, if None process
                sample by sample.

            buffered (bool):

        The processing element class is named ProcessingSubblock, `psb`
        and `pe` will be used as shorthand.
        """
        assert isinstance(cycles_to_process, int)
        assert cycles_to_process > 0
        assert isinstance(pipelined, bool)
        if block_size is not None:
            assert isinstance(block_size, tuple) and len(block_size) == 2

        super(ProcessingSubblock, self).__init__(name='pe')

        # the cycles to process is the same as latency
        self.ctp = cycles_to_process
        self.pipe = pipelined
        self.block_size = block_size

        # determine if buffered on inputs, outputs, or both
        assert isinstance(buffered, (bool, str))
        if isinstance(buffered, str):
            assert buffered in ('input', 'output')
            self.buffer_type = buffered
            buffered = True
        else:
            self.buffer_type = 'both' if buffered else 'none'
        self.buffered = buffered

        if buffered:
            # @todo: use buffer_size argument to limit buffer size
            #        test overruns
            self.fifo_i = FIFOReadyValid()
            self.fifo_o = FIFOReadyValid()
        else:
            self.fifo_i = None
            self.fifo_o = None

    @myhdl.block
    def process(self, glbl, datain, dataout):
        assert isinstance(datain, DataStream)
        assert isinstance(dataout, DataStream)
        assert len(datain.data) == len(dataout.data)

        ctp, piped, buffered = self.ctp, self.pipe, self.buffered

        clock, reset = glbl.clock, glbl.reset
        ready = Signal(bool(0))

        # include an input and output fifo
        if self.buffered:
            buffered_data_i = datain.copy()
            buffered_data_o = datain.copy()

            fifo_i = self.fifo_i
            fifo_i_inst = fifo_i.process(glbl, datain, buffered_data_i)
            fifo_o = self.fifo_o
            fifo_o_inst = fifo_o.process(glbl, buffered_data_o, dataout)
        else:
            buffered_data_i = datain
            buffered_data_o = None

        @always_comb
        def beh_ready():
            # tell upstream ready to process
            if self.buffered:
                datain.ready.next = ready and buffered_data_i.ready
            else:
                datain.ready.next = ready

        # need an intermediate to hold the signal values
        dataproc = datain.copy()
        npipe = ctp-1
        pipeline = [datain.copy() for _ in range(npipe)]

        @instance
        def processing_model():
            ready.next = True

            while True:
                # datain -> dataproc -> dataout
                if piped:
                    pipeline[0].next = datain
                    for ii in range(1, npipe):
                        pipeline[ii].next = pipeline[ii-1]
                    dataproc.next = pipeline[-1]
                else:
                    dataproc.next = datain
                    for nn in range(self.ctp-1):
                        ready.next = False
                        yield clock.posedge
                    ready.next = True

                # always at least one
                yield clock.posedge
                dataout.next = dataproc

        mon_insts = []
        for intf in (datain, dataproc, dataout):
            inst = intf.monitor()
            inst.name = intf.name
            mon_insts.append(inst)
        # must delete the temp inst reference when using myhdl.instances()
        del inst

        return myhdl.instances()

