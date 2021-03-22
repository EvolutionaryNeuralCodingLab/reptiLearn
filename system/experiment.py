from datetime import datetime
import threading

import config
from state import state, StateDispatcher
from dynamic_loading import load_module, find_subclass, reload_module
import video_record
import re


class ExperimentException(Exception):
    pass


state["experiment"] = {
    "is_running": False,
}

exp_state = state.get_cursor("experiment")
params = exp_state.get_cursor("params")
blocks = exp_state.get_cursor("blocks")

cur_experiment = None
cur_experiment_name = None
state_dispatcher = StateDispatcher()


def get_data_path(exp_id):
    exp_dir = exp_id + "_" + datetime.now().strftime("%Y%m%d-%H%M%S")
    return config.experiment_data_root / exp_dir


def run(exp_id, exp_params, exp_blocks=[]):
    if exp_state["is_running"] is True:
        raise ExperimentException("Experiment is already running.")

    if cur_experiment is None:
        raise ExperimentException("Can't run experiment. No experiment was set.")

    if len(exp_id.strip()) == 0 or len(re.findall(r'[^A-Za-z0-9_]', exp_id)) != 0:
        raise ExperimentException(f"Invalid experiment id: '{exp_id}'")

    data_path = get_data_path(exp_id)
    
    log.info("")
    log.info(f"Running experiment {cur_experiment_name}:")
    log.info("=================================================")
    log.info(f"Data dir: {data_path}")

    params.set_self(exp_params)
    blocks.set_self(exp_blocks)

    exp_state["is_running"] = True
    exp_state["data_dir"] = data_path
    state["video_record", "write_dir"] = data_path

    try:
        data_path.mkdir()
    except FileExistsError:
        raise ExperimentException("Experiment data directory already exists!")

    try:
        cur_experiment.run(params.get_self())
        set_phase(0, 0)
    except Exception:
        log.exception("Exception while running experiment:")
        exp_state["is_running"] = False


def end():
    if exp_state["is_running"] is False:
        raise ExperimentException("Experiment is not running.")

    try:
        cur_experiment.end_trial(merged_params())
        cur_experiment.end_block(merged_params())
        cur_experiment.end(params.get_self())
    except Exception:
        log.exception("Exception while running experiment:")
        return
    
    exp_state["is_running"] = False
    exp_state.delete("cur_trial")
    exp_state.delete("cur_block")
    video_record.restore_rec_dir()

    log.info(f"Experiment {cur_experiment_name} has ended.")


def set_phase(block, trial):
    if blocks.exists(()):
        if len(blocks.get_self()) <= block and block != 0:
            raise ExperimentException(f"Block {block} is not defined.")
    elif block != 0:
        raise ExperimentException("Experiment doesn't have block definitions.")

    num_trials = merged_params().get("num_trials", None)
    if num_trials is not None and trial >= num_trials:
        raise ExperimentException(f"Trial {trial} is out of range for block {block}.")

    if not exp_state["is_running"]:
        exp_state.update((), {"cur_block": block, "cur_trial": trial})
        return
    else:
        cur_trial = exp_state.get("cur_trial", None)
        cur_block = exp_state.get("cur_block", None)

        if cur_trial is not None and cur_trial != trial:
            cur_experiment.end_trial(merged_params())

        if cur_block is not None and cur_block != block:
            cur_experiment.end_block(merged_params())

        exp_state.update((), {"cur_block": block, "cur_trial": trial})

        if cur_block != block:
            cur_experiment.run_block(merged_params())

        if cur_trial != trial or cur_block != block:
            cur_experiment.run_trial(merged_params())


def next_trial():
    if not exp_state["is_running"]:
        log.warning(
            "experiment.py: Attempted to run next_trial() while experiment is not running"
        )

    cur_trial = exp_state["cur_trial"]
    cur_block = exp_state["cur_block"]

    num_trials = merged_params().get("num_trials", None)

    if num_trials is not None and cur_trial + 1 >= num_trials:
        next_block()
    else:
        # next trial
        set_phase(cur_block, cur_trial + 1)


def next_block():
    if not exp_state["is_running"]:
        log.warning(
            "experiment.py: Attempted to run next_block() while experiment is not running"
        )

    cur_block = exp_state["cur_block"]
    if cur_block + 1 < get_num_blocks():
        set_phase(cur_block + 1, 0)
    else:
        end()


def load_experiments(experiments_dir=config.experiment_modules_dir):
    experiment_specs = {}
    experiment_pys = experiments_dir.glob("*.py")

    for py in experiment_pys:
        module, spec = load_module(py)
        cls = find_subclass(module, Experiment)
        if cls is not None:
            experiment_specs[py.stem] = spec

    return experiment_specs


def refresh_experiment_list():
    global experiment_specs
    experiment_specs = load_experiments()
    log.info(
        f"Loaded {len(experiment_specs)} experiment(s): {', '.join(experiment_specs.keys())}"
    )


def set_experiment(name):
    global cur_experiment, cur_experiment_name

    if exp_state["is_running"] is True:
        raise ExperimentException(
            "Can't set experiment while an experiment is running."
        )

    if name not in experiment_specs.keys() and name is not None:
        raise ExperimentException(f"Unknown experiment name: {name}")

    if cur_experiment is not None:
        cur_experiment.release()

    if name is not None:
        spec = experiment_specs[name]
        module = reload_module(spec)
        cls = find_subclass(module, Experiment)
        cur_experiment = cls(log)
        cur_experiment_name = name
        log.info(f"Loaded experiment {name}.")
    else:
        cur_experiment = None
        log.info("Unloaded experiment.")

    exp_state["cur_experiment"] = name


class Experiment:
    default_params = {}
    default_blocks = []

    def __init__(self, logger):
        self.log = logger
        self.setup()

    def run(self, params):
        pass

    def run_block(self, params):
        pass

    def run_trial(self, params):
        pass

    def end(self, params):
        pass

    def end_block(self, params):
        pass

    def end_trial(self, params):
        pass

    def setup(self):
        pass

    def release(self):
        pass


# Convenience functions


def merged_params():
    if blocks.exists(()) and len(blocks.get_self()) > 0 and "cur_block" in exp_state:
        block_params = exp_state[("blocks", exp_state["cur_block"])]
    else:
        block_params = exp_state["params"]

    params_dict = params.get_self()
    params_dict.update(block_params)
    return params_dict


def get_num_blocks():
    if "blocks" in exp_state:
        return len(exp_state["blocks"])
    else:
        return 1


########################


def init(logger):
    global log

    log = logger
    refresh_experiment_list()
    threading.Thread(target=state_dispatcher.listen).start()


def shutdown():
    if cur_experiment is not None:
        if exp_state["is_running"]:
            end()
        set_experiment(None)

    state_dispatcher.stop()
