import experiment as exp
from canvas import Canvas


class CanvasSimpleExperiment(exp.Experiment):
    async def run(self):
        # Create a new Canvas instance to communicate with a Canvas app with ID "my_canvas" and start listening for incoming messages.
        self.canvas = Canvas("my_canvas")
        # Wait until a connection is made. Methods under the aio fields are async functions that await until a response from the browser arrives.
        await self.canvas.aio.connected()
        self.log.info("Connected to canvas app")

        # To add anything to the stage we first need to add a Layer to the stage.
        await self.canvas.aio.add("stage", "Layer", id="main")
        # Add a red circle to the layer. The id from the previous line is used to reference the layer.
        await self.canvas.aio.add(
            "main",
            "Circle",
            x=100,
            y=100,
            radius=80,
            fill="red",
            id="circle",
        )

    async def end(self):
        # Clear the canvas
        self.canvas.reset()
        # Stop listening to canvas messages
        self.canvas.release()
