"""
Voice activation pipeline:
openWakeWord -> Silero VAD -> faster-whisper -> allow-listed action router.

Audio is streamed from the browser microphone over Socket.IO as 16 kHz mono
Int16 PCM chunks ("voice_audio" events). A "voice_trigger" event (sent by the
UI Listen button) skips the wake-word stage and starts capturing immediately,
which also serves as a fallback when openWakeWord fails to initialize.

Pipeline status is published to the state store under the "voice" key, so the
web UI receives updates through the regular state Socket.IO broadcast.

Author: ReptiLearn voice module, 2026
"""
import difflib
import queue
import re
import threading
import time
from collections import deque

import numpy as np

import experiment
from configure import get_config
from rl_logging import get_main_logger

SAMPLE_RATE = 16000
WAKE_FRAME_SAMPLES = 1280  # 80ms, openWakeWord's expected frame size
VAD_FRAME_SAMPLES = 512  # Silero VAD v5 frame size at 16 kHz

_log = None
_config: dict = None
_voice_state = None
_socketio = None

_audio_queue: queue.Queue = None
_trigger_event = threading.Event()
_cancel_event = threading.Event()
_shutdown_event = threading.Event()
_worker_thread: threading.Thread = None

_wake_model = None
_vad_model = None
_stt_model = None


class _SileroVAD:
    """
    Minimal stateful wrapper around the Silero VAD v5 ONNX model using
    onnxruntime directly (avoids importing torch at runtime).
    """

    CONTEXT_SAMPLES = 64

    def __init__(self):
        import importlib.resources

        import onnxruntime

        with importlib.resources.path(
            "silero_vad.data", "silero_vad.onnx"
        ) as model_path:
            opts = onnxruntime.SessionOptions()
            opts.inter_op_num_threads = 1
            opts.intra_op_num_threads = 1
            self.session = onnxruntime.InferenceSession(
                str(model_path),
                providers=["CPUExecutionProvider"],
                sess_options=opts,
            )
        self.reset()

    def reset(self):
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, self.CONTEXT_SAMPLES), dtype=np.float32)

    def __call__(self, frame_f32):
        """
        Return the speech probability for a float32 frame of VAD_FRAME_SAMPLES samples.
        """
        x = np.concatenate(
            [self._context, frame_f32.reshape(1, -1).astype(np.float32)], axis=1
        )
        out, state = self.session.run(
            None,
            {
                "input": x,
                "state": self._state,
                "sr": np.array(SAMPLE_RATE, dtype=np.int64),
            },
        )
        self._state = state
        self._context = x[:, -self.CONTEXT_SAMPLES:]
        return float(out[0][0])


def _update_voice_state(**kvs):
    try:
        _voice_state.update((), kvs)
    except Exception:
        _log.exception("Error updating voice state:")


def _load_models():
    """
    Load pipeline models. A wake-word failure is not fatal (manual trigger still
    works), but the pipeline is unusable without VAD or the STT model.
    """
    global _wake_model, _vad_model, _stt_model

    wake_cfg = _config.get("wake", {})
    stt_cfg = _config.get("stt", {})

    try:
        import openwakeword
        import openwakeword.utils
        from openwakeword.model import Model as WakeModel

        model_name = wake_cfg.get("model", "hey_jarvis")
        if not model_name.endswith(".onnx"):
            try:
                openwakeword.utils.download_models(model_names=[model_name])
            except Exception:
                _log.warning(
                    "Could not download openWakeWord models (no internet?). "
                    "Trying to load from cache..."
                )
        _wake_model = WakeModel(
            wakeword_models=[model_name], inference_framework="onnx"
        )
        _log.info(f"Voice: loaded openWakeWord model '{model_name}'.")
    except Exception:
        _wake_model = None
        _log.exception(
            "Voice: failed to initialize openWakeWord. "
            "Wake-word detection is disabled; use the Listen button instead."
        )

    _update_voice_state(wake_available=_wake_model is not None)

    try:
        _vad_model = _SileroVAD()
        _log.info("Voice: loaded Silero VAD (ONNX).")
    except Exception:
        _vad_model = None
        _log.exception("Voice: failed to initialize Silero VAD.")
        return False

    try:
        from faster_whisper import WhisperModel

        _stt_model = WhisperModel(
            stt_cfg.get("model", "large-v3-turbo"),
            device=stt_cfg.get("device", "auto"),
            compute_type=stt_cfg.get("compute_type", "default"),
        )
        _log.info(
            f"Voice: loaded faster-whisper model '{stt_cfg.get('model', 'large-v3-turbo')}'."
        )
    except Exception:
        _stt_model = None
        _log.exception("Voice: failed to initialize faster-whisper.")
        return False

    return True


def _drain_queue():
    try:
        while True:
            _audio_queue.get_nowait()
    except queue.Empty:
        pass


def _wait_for_activation(pre_roll: deque):
    """
    Consume audio from the queue, feeding it to the wake-word model, until
    either the wake word is detected or a manual trigger arrives.

    Returns "wake", "manual", or None on shutdown.
    """
    wake_buf = np.empty(0, dtype=np.int16)
    threshold = _config.get("wake", {}).get("threshold", 0.5)

    if _wake_model is not None:
        _wake_model.reset()

    while not _shutdown_event.is_set():
        if _trigger_event.is_set():
            _trigger_event.clear()
            return "manual"

        try:
            chunk = _audio_queue.get(timeout=0.1)
        except queue.Empty:
            continue

        pre_roll.append(chunk)

        if _wake_model is None:
            continue

        wake_buf = np.concatenate([wake_buf, chunk])
        while len(wake_buf) >= WAKE_FRAME_SAMPLES:
            frame, wake_buf = (
                wake_buf[:WAKE_FRAME_SAMPLES],
                wake_buf[WAKE_FRAME_SAMPLES:],
            )
            scores = _wake_model.predict(frame)
            if max(scores.values()) >= threshold:
                _log.info(f"Voice: wake word detected (scores: {scores}).")
                _wake_model.reset()
                return "wake"

    return None


def _capture_utterance(initial_chunks):
    """
    Record audio until end of speech is detected by Silero VAD.

    Args:
    - initial_chunks: list of int16 chunks to prepend (pre-roll audio).

    Returns a float32 mono 16 kHz numpy array, or None if no speech was
    detected in time or capturing was cancelled.
    """
    vad_cfg = _config.get("vad", {})
    threshold = vad_cfg.get("threshold", 0.5)
    silence_duration = vad_cfg.get("silence_duration", 0.8)
    speech_timeout = vad_cfg.get("speech_timeout", 5.0)
    max_duration = vad_cfg.get("max_utterance_duration", 10.0)

    _vad_model.reset()
    _cancel_event.clear()

    collected = []
    vad_buf = np.empty(0, dtype=np.float32)
    speech_started = False
    silence_time = 0.0
    start_time = time.time()
    pending = list(initial_chunks)

    while not _shutdown_event.is_set():
        if _cancel_event.is_set():
            _cancel_event.clear()
            _log.info("Voice: capture cancelled.")
            return None

        if pending:
            chunk = pending.pop(0)
        else:
            try:
                chunk = _audio_queue.get(timeout=0.1)
            except queue.Empty:
                if not speech_started and time.time() - start_time > speech_timeout:
                    _log.info("Voice: no speech detected, going back to sleep.")
                    return None
                continue

        collected.append(chunk)
        vad_buf = np.concatenate(
            [vad_buf, chunk.astype(np.float32) / 32768.0]
        )

        while len(vad_buf) >= VAD_FRAME_SAMPLES:
            frame, vad_buf = (
                vad_buf[:VAD_FRAME_SAMPLES],
                vad_buf[VAD_FRAME_SAMPLES:],
            )
            prob = _vad_model(frame)
            frame_duration = VAD_FRAME_SAMPLES / SAMPLE_RATE

            if prob >= threshold:
                speech_started = True
                silence_time = 0.0
            elif speech_started:
                silence_time += frame_duration
                if silence_time >= silence_duration:
                    return _chunks_to_f32(collected)

        elapsed = time.time() - start_time
        if not speech_started and elapsed > speech_timeout:
            _log.info("Voice: no speech detected, going back to sleep.")
            return None
        if speech_started and elapsed > max_duration:
            _log.info("Voice: max utterance duration reached.")
            return _chunks_to_f32(collected)

    return None


def _chunks_to_f32(chunks):
    audio = np.concatenate(chunks).astype(np.float32) / 32768.0
    return audio


def _transcribe(audio_f32):
    stt_cfg = _config.get("stt", {})
    segments, _ = _stt_model.transcribe(
        audio_f32,
        language=stt_cfg.get("language", "en"),
        beam_size=5,
    )
    return " ".join(s.text.strip() for s in segments).strip()


# Filler words removed before phrase matching so e.g. "please open the left
# door" matches the allow-listed phrase "open left door".
_STOPWORDS = {"please", "the", "a", "an", "now", "could", "would", "you", "can"}


def _normalize(text):
    text = re.sub(r"[^\w\s]", "", text.lower())
    words = [w for w in text.split() if w not in _STOPWORDS]
    return " ".join(words)


def _run_matched_action(matched_phrase, label):
    if experiment.cur_experiment is None:
        _log.warning(
            f'Voice: matched "{matched_phrase}" -> "{label}", but no session is open. Ignoring.'
        )
        _update_voice_state(last_action=None)
        return

    if label not in experiment.cur_experiment.actions:
        _log.warning(
            f'Voice: matched "{matched_phrase}" -> "{label}", but the current experiment '
            "does not register this action. Ignoring."
        )
        _update_voice_state(last_action=None)
        return

    _log.info(f'Voice: running action "{label}" (matched phrase: "{matched_phrase}").')
    _update_voice_state(last_action=label)
    experiment.run_action(label)


def _run_matched_analysis(matched_phrase, spec):
    panel = spec.get("panel")
    scope = spec.get("scope", "current")
    _log.info(
        f'Voice: running analysis panel "{panel}" (scope: {scope}, '
        f'matched phrase: "{matched_phrase}").'
    )
    _update_voice_state(last_action=f"Analysis: {panel} ({scope})")
    # The web UI listens for this event, runs the analysis through the
    # existing REST endpoint, and shows the figure popup.
    _socketio.emit("voice_analysis", {"panel": panel, "scope": scope})


def _route(transcript):
    """
    Match a transcript against the allow-listed phrases and run the matching
    experiment action or analysis panel. Every decision is logged.
    """
    router_cfg = _config.get("router", {})
    match_threshold = router_cfg.get("match_threshold", 0.75)

    # Candidates: normalized phrase -> (kind, target).
    candidates = {}
    for phrase, label in router_cfg.get("allowed_actions", {}).items():
        candidates[_normalize(phrase)] = ("action", label)
    for phrase, spec in router_cfg.get("allowed_analysis", {}).items():
        candidates[_normalize(phrase)] = ("analysis", spec)

    normalized = _normalize(transcript)
    _update_voice_state(last_transcript=transcript)

    if not normalized:
        _log.info("Voice: empty transcript, ignoring.")
        return

    _log.info(f'Voice: heard "{transcript}"')

    # Exact or substring match first, preferring the longest matching phrase.
    matched_phrase = None
    for phrase in sorted(candidates, key=len, reverse=True):
        if phrase == normalized or phrase in normalized:
            matched_phrase = phrase
            break

    # Fall back to fuzzy matching of the whole transcript.
    if matched_phrase is None:
        close = difflib.get_close_matches(
            normalized, list(candidates.keys()), n=1, cutoff=match_threshold
        )
        if close:
            matched_phrase = close[0]

    if matched_phrase is None:
        _log.info(
            f'Voice: no allow-listed command matched "{normalized}". Ignoring.'
        )
        _update_voice_state(last_action=None)
        return

    kind, target = candidates[matched_phrase]
    if kind == "analysis":
        _run_matched_analysis(matched_phrase, target)
    else:
        _run_matched_action(matched_phrase, target)


def _worker():
    _update_voice_state(status="loading")

    if not _load_models():
        _update_voice_state(
            status="error", error="Voice models failed to load. See system log."
        )
        return

    _update_voice_state(status="listening", error=None)

    pre_roll_seconds = _config.get("vad", {}).get("pre_roll", 0.5)

    while not _shutdown_event.is_set():
        # Rough chunk count assuming ~128ms chunks from the UI; deque length
        # only bounds memory, VAD trims leading silence anyway.
        pre_roll = deque(maxlen=max(1, int(pre_roll_seconds / 0.128) + 1))

        _update_voice_state(status="listening")
        activation = _wait_for_activation(pre_roll)
        if activation is None:
            break

        _update_voice_state(status="recording")
        # After a wake word, the command comes next; the pre-roll would only
        # add the wake word's tail, so it is used for manual triggers only.
        initial = list(pre_roll) if activation == "manual" else []
        audio = _capture_utterance(initial)

        if audio is None:
            continue

        _update_voice_state(status="transcribing")
        try:
            transcript = _transcribe(audio)
        except Exception:
            _log.exception("Voice: transcription failed:")
            continue

        _route(transcript)
        _drain_queue()


def init(state, socketio):
    """
    Initialize the voice module.

    Args:
    - state: A managed_state.Cursor pointing to the state store root.
    - socketio: The flask_socketio.SocketIO server instance.
    """
    global _log, _config, _voice_state, _audio_queue, _worker_thread, _socketio

    _log = get_main_logger()
    _config = getattr(get_config(), "voice", None)
    _socketio = socketio

    _voice_state = state.get_cursor("voice")
    _voice_state.set_self(
        {
            "status": "disabled",
            "wake_available": False,
            "last_transcript": None,
            "last_action": None,
            "error": None,
        }
    )

    if _config is None or not _config.get("enabled", False):
        _log.info("Voice: disabled in config.")
        return

    # ~30s of audio at 16kHz with ~128ms chunks.
    _audio_queue = queue.Queue(maxsize=256)

    @socketio.on("voice_audio")
    def handle_voice_audio(data):
        try:
            chunk = np.frombuffer(data, dtype=np.int16)
        except (ValueError, TypeError):
            return
        if len(chunk) == 0:
            return
        try:
            _audio_queue.put_nowait(chunk)
        except queue.Full:
            # Drop the oldest chunk to keep the stream near real time.
            try:
                _audio_queue.get_nowait()
                _audio_queue.put_nowait(chunk)
            except (queue.Empty, queue.Full):
                pass

    @socketio.on("voice_trigger")
    def handle_voice_trigger():
        _log.info("Voice: manual listen trigger received.")
        _trigger_event.set()

    @socketio.on("voice_cancel")
    def handle_voice_cancel():
        _cancel_event.set()

    _worker_thread = threading.Thread(
        target=_worker, name="voice_worker", daemon=True
    )
    _worker_thread.start()


def shutdown():
    """
    Stop the voice worker thread.
    """
    _shutdown_event.set()
