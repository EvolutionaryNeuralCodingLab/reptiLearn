import vimba

from video_stream import ImageSource
import time
import numpy as np

FRAME_QUEUE_SIZE = 10


class AlliedVisionImageSource(ImageSource):
    default_params = {
        **ImageSource.default_params,
        "exposure": 8000,
        "trigger": True,
        "gain": None,
        "frame_rate": None,
        "cam_id": None,
        "trigger_source": "Line3",
        "wb_mode": None,
        "wb_red": None,
        "wb_blue": None,
    }

    def configure_camera(self):
        """Configure camera for trigger mode before acquisition"""
        try:
            self.cam.ExposureAuto.set("Off")
            self.cam.ExposureMode.set("Timed")
            self.cam.ExposureTime.set(self.get_config("exposure"))
            # Raise USB link budget to reduce incomplete frames at higher resolutions.
            if hasattr(self.cam, "DeviceLinkThroughputLimit"):
                self.cam.DeviceLinkThroughputLimit.set(120000000)

            # Prefer Mono8 for lower bandwidth and better stream stability.
            try:
                if hasattr(self.cam, "set_pixel_format"):
                    self.cam.set_pixel_format(vimba.PixelFormat.Mono8)
            except Exception:
                self.log.warning("Could not set camera pixel format to Mono8.")
            gain = self.get_config("gain")
            if gain is not None and hasattr(self.cam, "Gain"):
                # Optional: turn off auto-gain if the camera has it
                if hasattr(self.cam, "GainAuto"):
                    self.cam.GainAuto.set("Off")
                self.cam.Gain.set(gain)

            wb_mode = self.get_config("wb_mode")
            if wb_mode is not None and hasattr(self.cam, "BalanceWhiteAuto"):
                # e.g. "Off", "Once", "Continuous"
                self.cam.BalanceWhiteAuto.set(wb_mode)

            wb_red = self.get_config("wb_red")
            wb_blue = self.get_config("wb_blue")

            if (wb_red is not None or wb_blue is not None) and hasattr(self.cam, "BalanceRatio") and hasattr(self.cam, "BalanceRatioSelector"):

                if wb_red is not None:
                    self.cam.BalanceRatioSelector.set("Red")
                    self.cam.BalanceRatio.set(wb_red)

                if wb_blue is not None:
                    self.cam.BalanceRatioSelector.set("Blue")
                    self.cam.BalanceRatio.set(wb_blue)

            configured_trigger = self.get_config("trigger") is True
            if configured_trigger:
                # Hardware trigger mode
                if hasattr(self.cam, "AcquisitionFrameRateEnable"):
                    self.cam.AcquisitionFrameRateEnable.set(False)

                if hasattr(self.cam, "TriggerMode"):
                    self.cam.TriggerMode.set("Off")

                if hasattr(self.cam, "TriggerSelector"):
                    self.cam.TriggerSelector.set("FrameStart")

                if hasattr(self.cam, "LineSelector"):
                    self.cam.LineSelector.set(self.get_config("trigger_source"))

                if hasattr(self.cam, "LineMode"):
                    self.cam.LineMode.set("Input")

                if hasattr(self.cam, "TriggerSource"):
                    self.cam.TriggerSource.set(self.get_config("trigger_source"))

                if hasattr(self.cam, "TriggerMode"):
                    self.cam.TriggerMode.set("On")

                if hasattr(self.cam, "TriggerActivation"):
                    self.cam.TriggerActivation.set("FallingEdge")

            elif self.get_config("frame_rate") is not None:
                # Free-run frame-rate mode
                if hasattr(self.cam, "TriggerMode"):
                    self.cam.TriggerMode.set("Off")

                if hasattr(self.cam, "AcquisitionFrameRateEnable"):
                    self.cam.AcquisitionFrameRateEnable.set(True)

                if hasattr(self.cam, "AcquisitionFrameRate"):
                    self.cam.AcquisitionFrameRate.set(self.get_config("frame_rate"))
            else:
                self.log.error(
                    "Configuration error: Expecting either a 'trigger' or 'frame_rate' property"
                )
                return

            if hasattr(self.cam, "AcquisitionMode"):
                self.cam.AcquisitionMode.set("Continuous")

        except Exception:
            self.log.exception("Exception while configuring camera:")
            # Fallback: enforce free-run mode when trigger-related writes are blocked.
            try:
                if hasattr(self.cam, "TriggerMode"):
                    self.cam.TriggerMode.set("Off")
                if hasattr(self.cam, "AcquisitionFrameRateEnable"):
                    self.cam.AcquisitionFrameRateEnable.set(True)
                if hasattr(self.cam, "AcquisitionFrameRate") and self.get_config("frame_rate") is not None:
                    self.cam.AcquisitionFrameRate.set(self.get_config("frame_rate"))
                self.log.warning("Applied free-run fallback camera configuration.")
            except Exception:
                self.log.exception("Failed to apply free-run fallback camera configuration.")

    def update_time_delta(self):
        self.cam.TimestampLatch.run()
        cam_time = self.cam.TimestampLatchValue.get()  # in nanosecs
        server_time = time.time_ns()
        self.camera_time_delta = (server_time - cam_time) / 1e9
        self.log.info(f"Updated time delta: {self.camera_time_delta}")

    def _on_start(self):
        try:
            self.configure_camera()

            self.update_time_delta()
            # self.cam.start_streaming(self._frame_hander)
            self.log.info("Camera initialized.")
            self.image_result = None

            self.prev_writing = self.state.get("writing", False)
            self._hb_last_ts = time.time()
            self._hb_frame_count = 0
            self._hb_incomplete_count = 0
            self._hb_last_status = "unknown"

        except vimba.VimbaCameraError:
            self.log.error(
                "Failed to access Camera {}. Abort.".format(self.get_config("cam_id"))
            )

        return True

    def run(self):
        super(ImageSource, self).run()
        self.system = vimba.Vimba.get_instance()
        with self.system as v:
            cams = v.get_all_cameras()
            print("Cameras found: {}".format(len(cams)))
            for cam in cams:
                print_camera(cam)
            self.cam = v.get_camera_by_id(self.get_config("cam_id"))
            with self.cam:
                try:
                    if not self._on_start():
                        return
                    self.cam.start_streaming(self._frame_hander)
                    self.state["acquiring"] = True
                    self.stop_event.wait()
                    if self.stop_event.is_set():
                        self.log.info("Shutting down")
                        self.stop_event.clear()
                except KeyboardInterrupt:
                    pass
                finally:
                    if "acquiring" in self.state:
                        self.state["acquiring"] = False
                    self._on_stop()

    def _frame_hander(self, cam, frame):
        try:
            frame_status = "unknown"
            if hasattr(frame, "get_status"):
                try:
                    frame_status = str(frame.get_status())
                except Exception:
                    frame_status = "status_error"

            # Drop incomplete/error frames to avoid visual tearing artifacts.
            if frame_status not in ("FrameStatus.Complete", "Complete", "0"):
                self._hb_incomplete_count += 1
                now = time.time()
                if now - self._hb_last_ts >= 1.0:
                    self.log.warning(
                        "Frame heartbeat: source frames/sec=%s, dropped_incomplete/sec=%s, last_status=%s",
                        self._hb_frame_count,
                        self._hb_incomplete_count,
                        frame_status,
                    )
                    self._hb_frame_count = 0
                    self._hb_incomplete_count = 0
                    self._hb_last_ts = now
                return

            self._hb_frame_count += 1

            if self.prev_writing is False and self.state.get("writing", False) is True:
                self.update_time_delta()
            self.prev_writing = self.state.get("writing", False)
            timestamp = 0.
            try:
                timestamp = frame.get_timestamp() / 1e9 + self.camera_time_delta
            except TypeError:
                self.log.info("frame timestamp error")
            img = frame.as_numpy_ndarray()

            # Add this: Reshape monochrome images
            if len(img.shape) == 3 and img.shape[-1] == 1:
                img = img.squeeze()

            self.image_result = img

            with self.buf.get_lock():
                self.timestamp.value = timestamp

                self.buf_np = np.frombuffer(
                    self.buf.get_obj(), dtype=self.buf_dtype
                ).reshape(self.buf_shape)

                # # If the buffer is 3D but the image is 2D, reshape the image to match
                if len(self.buf_shape) == 3 and len(img.shape) == 2:
                    img = img[..., np.newaxis]

                np.copyto(self.buf_np, img)

                for obs in self.observer_events:
                    obs.set()
        except Exception:
            self.log.exception(
                "Exception while getting image from alliedVision camera:"
            )
        finally:
            cam.queue_frame(frame)

    # def _frame_hander(self, cam, frame):
    #     try:
    #         if self.prev_writing is False and self.state.get("writing", False) is True:
    #             self.update_time_delta()
    #         self.prev_writing = self.state.get("writing", False)
    #         timestamp = frame.get_timestamp() / 1e9 + self.camera_time_delta
    #         img = frame.as_numpy_ndarray()
    #         self.image_result = img
    #
    #         with self.buf.get_lock():
    #             self.timestamp.value = timestamp
    #
    #             self.buf_np = np.frombuffer(
    #                 self.buf.get_obj(), dtype=self.buf_dtype
    #             ).reshape(self.buf_shape)
    #             np.copyto(self.buf_np, img)
    #
    #             for obs in self.observer_events:
    #                 obs.set()
    #     except Exception:
    #         self.log.exception(
    #             "Exception while getting image from alliedVision camera:"
    #         )
    #     finally:
    #         cam.queue_frame(frame)

    def _acquire_image(self):
        raise NotImplementedError("")

    def _on_stop(self):
        if self.cam.is_streaming():
            self.cam.stop_streaming()


def factory_reset(cam_id):
    """not tested"""
    raise NotImplementedError("No factory reset for allied-vision")


def print_camera(cam):
    print("/// Camera Name   : {}".format(cam.get_name()))
    print("/// Model Name    : {}".format(cam.get_model()))
    print("/// Camera ID     : {}".format(cam.get_id()))
    print("/// Serial Number : {}".format(cam.get_serial()))
    print("/// Interface ID  : {}\n".format(cam.get_interface_id()))


if __name__ == "__main__":
    with vimba.Vimba.get_instance() as v:
        cams = v.get_all_cameras()

        print("Cameras found: {}".format(len(cams)))

        for cam in cams:
            print_camera(cam)
