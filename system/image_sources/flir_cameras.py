try:
    import PySpin
except Exception:
    pass

from video_stream import ImageSource
import re
import time


class FLIRImageSource(ImageSource):
    default_params = {
        **ImageSource.default_params,
        "exposure": 8000,
        "trigger": True,
        "frame_rate": None,
        "pyspin": {},
        "cam_id": None,
        "trigger_source": "Line3",
    }

    def configure_camera(self):
        """Configure camera for trigger mode before acquisition"""
        if "exposure" in self.config:
            try:
                self.cam.ExposureAuto.SetValue(PySpin.ExposureAuto_Off)
                self.cam.ExposureMode.SetValue(PySpin.ExposureMode_Timed)
                self.cam.ExposureTime.SetValue(self.get_config("exposure"))
            except Exception:
                self.log.exception("Exception while configuring camera:")

        try:
            if self.get_config("trigger") is True:
                self.cam.AcquisitionFrameRateEnable.SetValue(False)
                self.cam.TriggerMode.SetValue(PySpin.TriggerMode_Off)
                self.cam.TriggerSelector.SetValue(PySpin.TriggerSelector_FrameStart)
                self.cam.TriggerSource.SetValue(
                    getattr(
                        PySpin, "TriggerSource_" + self.get_config("trigger_source")
                    )
                )
                self.cam.TriggerMode.SetValue(PySpin.TriggerMode_On)
                self.cam.TriggerActivation.SetValue(
                    PySpin.TriggerActivation_FallingEdge
                )
            elif self.get_config("frame_rate") is not None:
                self.cam.TriggerMode.SetValue(PySpin.TriggerMode_Off)
                self.cam.AcquisitionFrameRateEnable.SetValue(True)
                self.cam.AcquisitionFrameRate.SetValue(self.get_config("frame_rate"))

            self.cam.AcquisitionMode.SetValue(PySpin.AcquisitionMode_Continuous)

            pyspin_config = self.get_config("pyspin")

            nodemap = self.cam.GetNodeMap()
            for key in pyspin_config.keys():
                value = pyspin_config[key]
                # self.setPySpinNode(nodemap, "TemperatureLinearResolution", "High")
                try:
                    self.setPySpinNode(nodemap, key, value)
                except Exception:
                    self.log.exception("Error while setting pyspin node:")

        except Exception:
            self.log.exception("Exception while configuring camera:")

    def setPySpinNode(self, nodemap, node_name, value):
        self.log.info(f"Setting {node_name} to {value}")
        if isinstance(value, int):
            node = PySpin.CIntegerPtr(nodemap.GetNode(node_name))
        elif isinstance(value, float):
            node = PySpin.CFloatPtr(nodemap.GetNode(node_name))
        elif isinstance(value, bool):
            node = PySpin.CBooleanPtr(nodemap.GetNode(node_name))
        elif isinstance(value, str):
            node = PySpin.CEnumerationPtr(nodemap.GetNode(node_name))
        else:
            raise ValueError(f"Invalid value type: {value}")

        if not PySpin.IsAvailable(node) or not PySpin.IsWritable(node):
            raise ValueError(f"Node {node_name} is not available or not writable")

        if isinstance(value, str):
            enum_entry = PySpin.CEnumEntryPtr(node.GetEntryByName(value))
            if not PySpin.IsAvailable(enum_entry) or not PySpin.IsReadable(enum_entry):
                raise ValueError(
                    f"Enum entry {value} is unavailable for node {node_name}"
                )
            node.SetIntValue(enum_entry.GetValue())
        else:
            node = value

    def getPySpinNode(self, nodemap, node_name):
        node = nodemap.GetNode(node_name)
        if not PySpin.IsAvailable(node) or not PySpin.IsReadable(node):
            raise ValueError(f"Node {node_name} is not available or not readable")
        return node.GetValue()

    def update_time_delta(self):
        try:
            self.cam.TimestampLatch()
            cam_time = self.cam.TimestampLatchValue.GetValue()  # in nanosecs
        except Exception:
            cam_time = self.cam.Timestamp.GetValue()

        server_time = time.time_ns()
        self.camera_time_delta = (server_time - cam_time) / 1e9
        self.log.debug(f"Updated time delta: {self.camera_time_delta}")

    def _on_start(self):
        try:
            self.system = PySpin.System_GetInstance()
            self.cam_list = self.system.GetCameras()
            filtered = filter_cameras(self.cam_list, self.get_config("cam_id"))
            if len(filtered) < 1:
                self.log.error(f"Camera {self.get_config('cam_id')} was not found.")
                return False

            self.cam: PySpin.CameraPtr = filtered[0]
            self.cam.Init()
            self.configure_camera()

            self.update_time_delta()

            self.cam.BeginAcquisition()
            self.log.info("Camera initialized.")
            self.image_result = None

            self.prev_writing = self.state.get("writing", False)
            return True
        except Exception:
            self.log.exception("Exception while initializing camera:")
            return False

    def _acquire_image(self):
        if self.image_result is not None:
            try:
                self.image_result.Release()
            except PySpin.SpinnakerException:
                pass

        if self.prev_writing is False and self.state.get("writing", False) is True:
            self.update_time_delta()
        self.prev_writing = self.state.get("writing", False)

        is_incomplete = True

        while is_incomplete:
            try:
                self.image_result: PySpin.ImagePtr = self.cam.GetNextImage()
            except Exception:
                self.log.exception("Error while retrieving next image:")

            is_incomplete = self.image_result.IsIncomplete()
            if is_incomplete:
                time.sleep(0.001)

                # self.log.info(f"Image incomplete with image status {PySpin.Image_GetImageStatusDescription(self.image_result.GetImageStatus())}")

        timestamp = self.image_result.GetTimeStamp() / 1e9 + self.camera_time_delta

        try:
            img = self.image_result.GetNDArray()
            return (img, timestamp)
        except Exception:
            self.log.exception("Exception while getting image from flir camera:")

    def _on_stop(self):
        if self.cam.IsStreaming():
            self.cam.EndAcquisition()

        self.cam.DeInit()
        self.cam = None
        self.cam_list.Clear()
        self.system.ReleaseInstance()


def get_device_id(cam) -> str:
    """Get the camera device ID of the cam instance"""
    nodemap_tldevice = cam.GetTLDeviceNodeMap()
    device_id = PySpin.CStringPtr(nodemap_tldevice.GetNode("DeviceID")).GetValue()
    m = re.search(r"SRL_[a-zA-Z\d]{8}", device_id)
    if not m:
        return device_id
    return m[0][4:]


def filter_cameras(cam_list, cameras_string: str) -> None:
    """Filter cameras according to camera_label, which can be a name or last digits of device ID"""
    current_devices = [get_device_id(cam) for cam in cam_list]
    chosen_devices = []
    for cam_id in cameras_string.split(","):
        if re.match(r"[a-zA-Z]+", cam_id):
            if cam_id and cam_id in current_devices:
                chosen_devices.append(cam_id)
        elif re.match(r"[0-9]+", cam_id):
            chosen_devices.extend(
                [d for d in current_devices if d[-len(cam_id) :] == cam_id]
            )

    def _remove_from_cam_list(device_id):
        devices = [get_device_id(c) for c in cam_list]
        cam_list.RemoveByIndex(devices.index(device_id))

    for d in current_devices:
        if d not in chosen_devices:
            _remove_from_cam_list(d)

    return cam_list


def get_cam_ids():
    system = PySpin.System.GetInstance()
    cameras = system.GetCameras()
    dids = [get_device_id(cam) for cam in cameras]
    cameras.Clear()
    system.ReleaseInstance()
    return dids


def factory_reset(cam_id):
    """not tested"""
    system = PySpin.System.GetInstance()
    cameras = system.GetCameras()
    filtered = filter_cameras(cameras, cam_id)
    if len(filtered) == 0:
        raise Exception(f"Camera {cam_id} was not found.")

    cam = filtered[0]
    cam.Init()
    cam.FactoryReset.Execute()
    cam.DeInit()
    cameras.Clear()
    system.ReleaseInstance()


if __name__ == "__main__":
    print("Connected cameras ids:", get_cam_ids())
