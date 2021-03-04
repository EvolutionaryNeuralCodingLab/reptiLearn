import multiprocessing as mp
import config
from video_stream import ImageSource
from pathlib import Path
import mqtt
from threading import Timer
from datetime import datetime
import imageio
import time

# TODO:
# - videowriter should check if the timestamp matches the fps. if delta is about twice the 1/fps, it should repeat the
#   current frame twice, etc.
# - take fps from image source if possible, allow custom fps


video_writers = {}

mqtt_client = mqtt.Client()


def init(image_sources):
    for img_src in image_sources:
        video_writers[img_src.src_id] = VideoWriter(
            img_src, frame_rate=60, write_path=Path("videos")
        )

    mqtt_client.connect()

    for w in video_writers.values():
        w.start()


def start_trigger(pulse_len=17):
    mqtt_client.publish_json("arena/ttl_trigger/start", {"pulse_len": pulse_len})


def stop_trigger():
    mqtt_client.publish("arena/ttl_trigger/stop")


def start_record(src_ids=None):
    if src_ids is None:
        src_ids = video_writers.keys()

    def standby():
        for src_id in src_ids:
            video_writers[src_id].start_writing()

    stop_trigger()
    Timer(0.5, standby).start()
    Timer(1, start_trigger).start()


def stop_record(src_ids=None):
    if src_ids is None:
        src_ids = video_writers.keys()

    def stop():
        for src_id in src_ids:
            video_writers[src_id].stop_writing()

    stop_trigger()
    Timer(0.5, stop).start()


class VideoWriter(mp.Process):
    def __init__(
        self,
        img_src: ImageSource,
        frame_rate,
        write_path=Path("."),
        codec="mp4v",
        file_ext="mp4",
        logger=mp.get_logger(),
    ):
        super().__init__()
        self.codec = codec
        self.frame_rate = frame_rate
        self.img_src = img_src
        self.img_src.set_state({"writing": False})

        self.write_path = write_path
        self.file_ext = file_ext
        self.log = logger
        self.update_event = mp.Event()
        img_src.add_observer_event(self.update_event)

        self.parent_pipe, self.child_pipe = mp.Pipe()
        self.name = f"{type(self).__name__}:{self.img_src.src_id}"

    def start_writing(self, num_frames=None):
        self.parent_pipe.send("start")

    def stop_writing(self):
        self.parent_pipe.send("stop")
        self.img_src.set_state({"writing": False})

    def _get_new_write_paths(self):
        base = (
            self.img_src.src_id + "_" + datetime.now().strftime("%Y%m%d-%H%M%S") + "."
        )
        return (
            self.write_path / (base + self.file_ext),
            self.write_path / (base + "csv"),
        )

    def _begin_writing(self):
        if not self.img_src.get_state("acquiring"):
            self.log.error("Can't write video. Image source is not acquiring.")
            return

        vid_path, ts_path = self._get_new_write_paths()

        self.log.info(f"Starting to write video to: {vid_path}")
        self.writer = imageio.get_writer(
            str(vid_path),
            format="FFMPEG",
            mode="I",
            fps=self.frame_rate,
            **config.video_encoding,
        )

        self.ts_file = open(str(ts_path), "w")
        self.ts_file.write("timestamp\n")

        self.img_src.set_state({"writing": True})

    def _write(self):
        img, timestamp = self.img_src.get_image()

        self.ts_file.write(str(timestamp) + "\n")
        self.writer.append_data(img)

    def _finish_writing(self):
        self.writer.close()
        self.ts_file.close()

    def run(self):
        cmd = None

        while True:
            try:
                cmd = self.child_pipe.recv()
            except KeyboardInterrupt:
                break

            if cmd == "start":
                self.avg_write_time = 0
                self.frame_count = 0
                
                self._begin_writing()
                self.update_event.clear()

                try:
                    while True:
                        if self.img_src.end_event.is_set():
                            break
                        if self.child_pipe.poll() and self.child_pipe.recv() == "stop":
                            break
                        if self.update_event.wait(1):
                            self.update_event.clear()
                            t0 = time.time()
                            self._write()
                            dt = time.time() - t0
                            self.frame_count += 1
                            if self.frame_count == 1:
                                self.avg_write_time = dt
                            else:
                                self.avg_write_time = (
                                    self.avg_write_time * (self.frame_count - 1) + dt
                                ) / self.frame_count

                except KeyboardInterrupt:
                    break
                finally:
                    self.log.info(
                        f"Finished writing {self.frame_count} frames. Average frame write time: {self.avg_write_time*1000:.3f}ms"
                    )
                    self._finish_writing()
