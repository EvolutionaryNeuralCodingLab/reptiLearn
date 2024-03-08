import experiment as exp
import data_log
import video_system


class HistogramLoggerExperiment(exp.Experiment):
    default_params = {
        "obs_id": "hist",
    }

    def run(self):
        self.obs_id = exp.get_params()["obs_id"]
        self.obs = video_system.image_observers[self.obs_id]
        bin_count = self.obs.get_config("bin_count")
        self.obslog = data_log.ObserverLogger(
            self.obs,
            columns=[("time", "timestamptz not null")]
            + [(f"bin{i}", "double precision") for i in range(bin_count)],
            csv_path=exp.session_state["data_dir"] / (self.obs_id + ".csv"),
            split_csv=True,
        )
        self.obslog.start()
        self.obs.start_observing()

    def end(self):
        self.obs.stop_observing()
        self.obslog.stop()
