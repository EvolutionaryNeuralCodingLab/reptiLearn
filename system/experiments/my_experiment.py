import experiment as exp

class MyExperiment(exp.Experiment):
    default_params = {
        "color": "blue",
    }

    default_blocks = [
        {"color": "red"},
        {"color": "green"},
        {}
    ]

    def run_trial(self):
        if exp.state["video", "record", "is_recording"]:
            self.log.info("Video is being recorded")
        else:
            self.log.info("Video is not being recorded")

        exp.session_state["is_even_trial"] =  exp.session_state["cur_trial"] % 2 == 0

    def run_block(self):
        color = exp.get_params()["color"]
        self.log.info(f"Starting new block. Color is {color}")

    def run(self):
        self.log.info("My experiment is running!")

    def end(self):
        self.log.info("My experiment has ended!")

    def setup(self):
        exp.session_state.add_callback("is_even_trial", self.on_is_even_trial_changed)

    def on_is_even_trial_changed(self, old, new):
        self.log.info(f"is_even_trial changed from: {old} to: {new}")

    def end_trial(self):
        if exp.session_state["cur_trial"] >= exp.session_state["cur_block"]:
            exp.next_block()