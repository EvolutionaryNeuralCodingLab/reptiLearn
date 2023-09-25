import experiment as exp
from canvas import Canvas


class CanvasNoiseExperiment(exp.Experiment):
    default_params = {
        "canvas_id": "1",
        "fill": "red",
        "duration": 20,
        "max_noise": 10,
    }

    async def run_block(self):
        self.canvas = Canvas(exp.get_params()["canvas_id"], on_disconnect=exp.stop_experiment, logger=self.log)
        self.log.info("Connecting...")
        await self.canvas.aio.connected()
        self.log.info("Done connecting.")
        await self.canvas.aio.reset()
        await self.canvas.aio.add("stage", "Layer", id="main")

        stage = await self.canvas.aio.get_node("stage")
        self.width = stage["attrs"]["width"]
        self.height = stage["attrs"]["height"]
        rad = self.width // 6

        await self.canvas.aio.add(
            "main",
            "Circle",
            x=self.width // 2,
            y=self.height // 2,
            radius=rad,
            fill=exp.get_params()["fill"],
            id="shape",
            filters=["Noise"],
            noise=0,
        )
        self.canvas.make_tween("noise_tween", noise=exp.get_params()["max_noise"], node_id="shape", duration=exp.get_params()["duration"], on_finish=lambda resp: exp.next_block())
        self.canvas.node("shape", "cache")
        self.canvas.play_tween("noise_tween")

    async def end_block(self):
        await self.canvas.aio.reset()
