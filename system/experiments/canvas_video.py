import experiment as exp
from data_log import QueuedDataLogger
from canvas import Canvas


class CanvasVideoExperiment(exp.Experiment):
    default_params = {
        "canvas_id": "1",
        "video_url": "http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4",
        "playback_rate": 1,
        "repeat": False,
        "background": "#333333",
    }

    def on_video_update(self, payload):
        self.frame_logger.log(
            [payload["response_timestamp"], payload["video_timestamp"]]
        )

    def on_video_ended(self, payload):
        self.log.info(f"video ended {payload}")
        if exp.get_params()["repeat"] is True:
            # repeat forever
            self.canvas.play_video("vid")
        else:
            exp.next_block()

    def on_mousedown(self, event):
        self.canvas.tween("vid_rotate", "pause")

    def on_mouseup(self, event):
        self.canvas.play_tween("vid_rotate")

    def video_loadedmetadata(self, payload):
        self.log.info(f"Received video metadata: {payload}")
        metadata = payload["video"]
        w, h = metadata["width"] // 4, metadata["height"] // 4
        self.canvas.add_video(
            "main",
            "vid",
            x=(self.width) // 2,
            y=(self.height) // 2,
            width=w,
            height=h,
            offsetX=w // 2,
            offsetY=h // 2,
            id="vid_node",
        )
        self.canvas.on("vid_node", "mousedown", self.on_mousedown)
        self.canvas.on("vid_node", "mouseup", self.on_mouseup)

        self.canvas.video_set_props(
            "vid", playbackRate=exp.get_params()["playback_rate"]
        )

        def tween_finished(payload):
            self.log.info("tween finished")
            self.canvas.tween("vid_rotate", "reset")
            self.canvas.play_tween("vid_rotate")

        self.canvas.make_tween(
            "vid_rotate",
            node_id="vid_node",
            duration=5,
            rotation=360,
            easing="BounceEaseIn",
            on_finish=tween_finished,
        )

        self.canvas.make_tween(
            "vid_shrink",
            node_id="vid_node",
            w=w / 5,
            h=h / 5,
            duration=5,
            easing="BounceEaseIn",
            on_finish=tween_finished,
        )

        self.canvas.play_tween("vid_rotate")
        self.canvas.play_video("vid")

    def video_error(self, payload):
        self.log.info(f"Received video error: {payload}")

    async def run(self):
        # create and start data logger for video timing data
        self.frame_logger = QueuedDataLogger(
            ["time", "video_timestamp"],
            exp.session_state["data_dir"] / "video_timing.csv",
            split_csv=True,
        )
        self.frame_logger.start()

        self.canvas = Canvas(
            exp.get_params()["canvas_id"],
            on_disconnect=exp.stop_experiment,
            logger=self.log,
        )
        await self.canvas.aio.connected()
        stage = await self.canvas.aio.get_node("stage")
        self.width = stage["attrs"]["width"]
        self.height = stage["attrs"]["height"]

        await self.canvas.aio.reset()
        self.canvas.load_video(
            "vid",
            exp.get_params()["video_url"],
            muted=True,
            video_loadedmetadata=self.video_loadedmetadata,
            on_update=self.on_video_update,
            on_ended=self.on_video_ended,
            video_error=self.video_error,
        )
        self.canvas.add(
            "stage",
            "Layer",
            id="main",
        )
        self.canvas.add(
            "main",
            "Rect",
            fill=exp.get_params()["background"],
            x=0,
            y=0,
            width=self.width,
            height=self.height,
        )

    def run_trial(self):
        self.canvas.play_video("vid")

    async def end_trial(self):
        self.canvas.pause_video("vid")

    def end(self):
        self.frame_logger.stop()
        self.canvas.reset()
