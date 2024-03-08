import experiment as exp
import asyncio

# TODO: add async action

class AsyncPhasesExperiment(exp.Experiment):
    default_params = {
        "run_msg": "TestExperiment is running",
        "end_msg": "TestExperiment has ended",
    }

    async def setup(self):
        self.log.info("setup")
        await asyncio.sleep(1)
        self.log.info(".")
        self.actions["Run me"] = {"run": self.run_me}

    async def run_me(self):
        self.log.info("async")
        await asyncio.sleep(1)
        self.log.info("action")

    async def run_trial(self):
        self.log.info(f"run trial: {exp.session_state['cur_trial']}")
        await asyncio.sleep(1)
        self.log.info(".")

    async def run_block(self):
        self.log.info(f"run block: {exp.get_params()['run_msg']}")
        await asyncio.sleep(1)
        self.log.info(".")

    async def run(self):
        self.log.info(f"run: {exp.get_params()['run_msg']}")
        await asyncio.sleep(1)
        self.log.info(".")

    async def end(self):
        self.log.info(f"end: {exp.get_params()['end_msg']}")
        await asyncio.sleep(1)
        self.log.info(".")

    async def end_block(self):
        self.log.info(f"end block: {exp.get_params()['end_msg']}")
        await asyncio.sleep(1)
        self.log.info(".")

    async def end_trial(self):
        self.log.info(f"trial {exp.session_state['cur_trial']} ended")
        await asyncio.sleep(1)
        self.log.info(".")

    async def release(self):
        self.log.info("release")
        await asyncio.sleep(1)
        self.log.info(".")
        
