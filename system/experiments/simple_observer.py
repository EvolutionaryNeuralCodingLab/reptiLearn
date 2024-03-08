import experiment as exp
import video_system as vid


class SimpleObserver(exp.Experiment):
    def setup(self):
        # assuming an observer exists with id "hist"
        self.obs = vid.image_observers["hist"]
        self.obs.start_observing()  # start processing image data

    def run(self):
        # register on_observer_update to run every time the output of the observer updates.
        self.remove_listener = self.obs.add_listener(self.on_observer_update, exp.state)

    def end(self):
        # stop listening to observer updates
        self.remove_listener()

    def on_observer_update(self, output, timestamp):
        # run every time the observer updates its output.
        self.log.info(f"{timestamp}: {output[0]}")  # (log only the first value for brevity)

    def release(self):
        self.obs.stop_observing()  # stop processing image data