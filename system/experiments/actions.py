import experiment as exp


class ActionsExperiment(exp.Experiment):
    def setup(self):
        self.update_actions(None, False)
        exp.session_state.add_callback("is_running", self.update_actions)

    def update_actions(self, _, new):
        if new:
            self.actions = {
                "Stop": {"run": exp.stop_experiment},
            }
        else:
            self.actions = {
                "Run": {"run": exp.run_experiment},
            }

        exp.refresh_actions()
    
    def release(self):
        exp.session_state.remove_callback("is_running")
 