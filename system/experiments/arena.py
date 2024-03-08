import experiment as exp
import arena


class ArenaControl(exp.Experiment):
    def run(self):
        arena.run_command("periodic", "LED", [1, 200], False)

    def end(self):    
        arena.run_command("periodic", "LED", [0], False)
