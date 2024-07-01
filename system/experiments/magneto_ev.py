import datetime
import random
import time
import cv2 as cv
import numpy as np
import arena
import bbox
import experiment as exp
import schedule
import video_system
from experiment import session_state
from image_observers.yolo_bbox_detector import BBoxDataCollector
from video_system import capture_images, image_sources

from enum import Enum, auto


class Door_state(Enum):
    OPEN = auto()
    CLOSED = auto()
    OPENING = auto()
    CLOSING = auto()


class MagnetoReceptionExperiment(exp.Experiment):
    """
    Experiment to test Electro Magnetic reception in common swamp turtles.
    """

    default_params = {
        "Doors": {"decision_doors", "back_doors"},
        "decision_area": {"location": [0, 0], "radius": 200},
        "chose_right_area": {"location": [0, 0], "radius": 200},
        "chose_left_area": {"location": [0, 0], "radius": 200},
        "image_source_id": "top",
        "Reward": {"feeders": {"left_feeder": 15, "right_feeder": 15}}
    }


    #session_state should include:
    session_state["EMF_induced"] = False
    session_state["EMF_being_induced"] = False
    session_state["door_state"] = Door_state.CLOSED
    session_state["left_feeder_empty"] = False
    session_state["right_feeder_empty"] = False

    def setup(self):
        self.actions["Induce Electromagnetic Field"] = {"run": self.start_electromagnet}
        # TODO: directions of magnet
        self.actions["Turn down Electromagnetic Field"] = {"run": self.stop_electromagnet()}
        self.actions["Open Desicion Doors"] = {"run": self.open_doors(self.default_params["Doors"]["decision_doors"])}
        self.actions["Open Back Doors"] = {"run": self.open_doors(self.default_params["Doors"]["back_doors"])}
        self.actions["Close Desicion Doors"] = {"run": self.close_doors(self.default_params["Doors"]["decision_doors"])}
        self.actions["Close Back Doors"] = {"run": self.close_doors(self.default_params["Doors"]["back_doors"])}
        self.actions["Dispense Reward from Left feeder"] = {"run": self.dispense_reward("left_feeder")}
        self.actions["Dispense Reward from Right feeder"] = {"run": self.dispense_reward("right_feeder")}
        # self.actions["Find Turtle"] = {"run": self.fnd_turtle()}
        self.actions["Rest Area - On"] = {"run": self.rest_area_on()}
        self.actions["Rest Area - Off"] = {"run": self.rest_area_off()}

        self.bbox_collector = BBoxDataCollector("body_bbox")
        self.print_next_detection = False

        session_state["is_in_area"] = False

        if "rewards_count" not in exp.session_state:
            self.reset_rewards_count()

        self.daytime = False

    def start_electromagnet(self):
        """Sends command to the arena to induce an electromagnetic field for the experiment."""
        arena.run_command("set", "inductor")
        self.EMF_induced = True

    def trial_end(self):
        direction = random.random() # L / R
        if direction > 0.5:
            self.emf_left()
        else:
            self.emf_right()
    def stop_electromagnet(self):
        """Sends command to the arena to induce an electromagnetic field for the experiment."""
        arena.run_command("set", "inductor")
        self.EMF_induced = False

    def open_doors(self, doors_interfaces):
        """Sends command to the arena to open doors
        "doors" argument is a tuple"""

        for interface in doors_interfaces:
            arena.run_command("open", interface, None, False)

        self.door_state = Door_state.OPEN  #part of session state update


    def close_doors(self, doors_interfaces):
        """Sends command to the arena to close doors
        "doors" argument is a tuple"""
        for interface in doors_interfaces:
            arena.run_command("close", interface, None, False)
        self.door_state = Door_state.CLOSED  #part of session state update
        # TODO: add bbox safety check during closing

    def dispense_reward(self, feeder_interface):
        arena.run_command("dispense", feeder_interface, None, False)

        self.default_params["Reward"]["feeders"][feeder_interface] -= 1
        if self.default_params["Reward"]["feeders"][feeder_interface] == 0:
            self.empty_feeder_notification()
            self.end_experiment()


    def end_experiment(self):
        self.rest_area_on()
        self.open_doors("decision_doors")
        self.open_doors("back_doors")
        pass

    def find_turtle(self):
        pass
        #asd Gal how we should do it
