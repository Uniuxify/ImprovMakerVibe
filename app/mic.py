"""Microphone recorder using sounddevice.

Records a single continuous WAV file starting at t=0 of the recording, so it is
automatically synchronised with the event-log timeline.

To avoid slow/fast playback, the microphone is captured at the *actual* sample
rate used by the pygame mixer (queried via pygame.mixer.get_init()). If the
device delivers a different rate, the data is resampled back to the mixer rate
before the WAV is written, so playback always runs at correct speed.
"""
import os
import wave
import threading

import numpy as np
import pygame

try:
    import sounddevice as sd
    _HAS_SD = True
except Exception:  # pragma: no cover - sounddevice may be missing
    sd = None
    _HAS_SD = False

from . import config as C


def mixer_rate():
    """Return the sample rate the pygame mixer actually runs at."""
    try:
        info = pygame.mixer.get_init()
        if info:
            return int(info[0])
    except pygame.error:
        pass
    return C.SAMPLE_RATE


def _resample(data, src_rate, dst_rate):
    """Linear resample of an (N, C) int16 array from src_rate to dst_rate."""
    if src_rate == dst_rate or data.shape[0] == 0:
        return data
    n_src = data.shape[0]
    n_dst = max(1, int(round(n_src * dst_rate / float(src_rate))))
    x_src = np.arange(n_src, dtype=np.float64)
    x_dst = np.linspace(0.0, n_src - 1, n_dst, dtype=np.float64)
    out = np.empty((n_dst, data.shape[1]), dtype=data.dtype)
    for c in range(data.shape[1]):
        out[:, c] = np.interp(x_dst, x_src, data[:, c]).astype(data.dtype)
    return out


class MicRecorder:
    def __init__(self):
        self._stream = None
        self._frames = []
        self._recording = False
        self._capturing = True
        self._rate = C.SAMPLE_RATE          # target (mixer) rate
        self._stream_rate = C.SAMPLE_RATE   # actual device rate
        self._lock = threading.Lock()

    @property
    def recording(self):
        return self._recording

    def start(self):
        self._capturing = True
        self._rate = mixer_rate()
        self._stream_rate = self._rate
        if not _HAS_SD:
            print("[mic] sounddevice not available; microphone disabled")
            return False
        with self._lock:
            self._frames = []
        try:
            self._stream = sd.InputStream(
                samplerate=self._rate,
                channels=C.MIC_CHANNELS,
                dtype="int16",
                blocksize=C.MIC_BLOCKSIZE,
                callback=self._callback,
            )
            self._stream.start()
            # some host APIs open at a different rate than requested
            try:
                self._stream_rate = int(round(self._stream.samplerate))
            except Exception:
                self._stream_rate = self._rate
            self._recording = True
            return True
        except Exception as exc:  # pragma: no cover
            print(f"[mic] cannot start: {exc}")
            self._stream = None
            return False

    def set_capturing(self, flag):
        """Enable/disable capture (used to silence the mic during pauses)."""
        self._capturing = bool(flag)

    def _callback(self, indata, frames, time_info, status):  # pragma: no cover
        with self._lock:
            if self._recording and self._capturing:
                self._frames.append(indata.copy())

    def insert_silence(self, seconds):
        """Insert `seconds` of silence to keep the timeline aligned."""
        if seconds <= 0:
            return
        n = int(seconds * self._rate)
        if n <= 0:
            return
        sil = np.zeros((n, C.MIC_CHANNELS), dtype=np.int16)
        with self._lock:
            self._frames.append(sil)

    def stop(self, out_path=None):
        self._recording = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        with self._lock:
            frames = self._frames
            self._frames = []
        if not frames:
            return None
        data = np.concatenate(frames, axis=0)
        if self._stream_rate != self._rate:
            data = _resample(data, self._stream_rate, self._rate)
        if out_path:
            self._write_wav(out_path, data, self._rate)
        return data

    @staticmethod
    def _write_wav(path, data, rate):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with wave.open(path, "wb") as wf:
            wf.setnchannels(C.MIC_CHANNELS)
            wf.setsampwidth(2)          # int16
            wf.setframerate(rate)
            wf.writeframes(data.tobytes())