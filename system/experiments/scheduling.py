import schedule as sc
import experiment as exp
import datetime as dt

class SchedulingExperiment(exp.Experiment):
    def setup(self):
        self.cancel_tick = None
        self.cancel_next_block = None

    def run(self):
        self.cancel_tick = sc.repeat(self.tick, interval=2, repeats=True)
    
    def end(self):
        if self.cancel_tick is not None:
            self.cancel_tick()

    def tick(self):
        self.log.info("tick!")

    def run_block(self):
        if self.cancel_next_block is not None:
            self.cancel_next_block()

        self.cancel_next_block = sc.once(exp.next_block, interval=5)
