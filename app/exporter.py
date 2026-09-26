"""Export an event log to an MP4 file via ffmpeg.

Video frames are rendered offscreen (identical to the on-screen render) and
written to ffmpeg's stdin. Audio is built as a filter graph mixing the recorded
microphone track with each sound-effect delayed to its logged start time.
"""
import os
import shutil
import subprocess

import pygame

from . import config as C
from .player import Runtime


def ffmpeg_path():
    return shutil.which("ffmpeg")


def is_available():
    return ffmpeg_path() is not None


class ExportError(Exception):
    pass


def export(log, assets, out_path, progress=None):
    """Render `log` to `out_path` (mp4). Returns the output path."""
    if not is_available():
        raise ExportError("ffmpeg not found on PATH")

    duration = max(log.duration, 0.04)
    fps = C.FPS
    total_frames = max(1, int(round(duration * fps)))

    runtime = Runtime(log, assets)
    frame_surf = pygame.Surface((C.FRAME_W, C.FRAME_H))

    audio_inputs, audio_filters = _build_audio_graph(log, assets)
    cmd = _build_command(out_path, fps, audio_inputs, audio_filters)

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for i in range(total_frames):
            t = i / fps
            frame_surf.fill((0, 0, 0))
            runtime.render(frame_surf, t)
            raw = pygame.image.tostring(frame_surf, "RGB")
            proc.stdin.write(raw)
            if progress and (i % 10 == 0):
                progress(i / total_frames)
        proc.stdin.close()
    except BrokenPipeError:
        pass
    finally:
        _, err = proc.communicate()
    if proc.returncode != 0:
        raise ExportError(
            "ffmpeg failed:\n" + (err.decode("utf-8", "ignore") if err else ""))
    if progress:
        progress(1.0)
    return out_path


def _resolve(path, assets):
    if not path:
        return None
    if os.path.isabs(path):
        return path if os.path.exists(path) else None
    full = os.path.join(assets.root, path)
    return full if os.path.exists(full) else None


def _build_audio_graph(log, assets):
    """Return (input_args, filter_args). Falls back gracefully to no audio."""
    inputs = []
    chains = []
    labels = []

    # microphone track
    mic = _resolve(log.mic_path, assets) if log.mic_path else None
    if mic:
        inputs += ["-i", mic]
        chains.append("[%d:a]aresample=%d[mic]" % (len(inputs) // 2 - 1,
                                                   C.SAMPLE_RATE))
        labels.append("[mic]")

    # sound effects, delayed to their logged time
    idx_base = len(inputs) // 2
    sfx_count = 0
    for ev in sorted(log.events, key=lambda e: e["t"]):
        if ev["type"] != "sound":
            continue
        snd = assets.sm.get(ev["sound"])
        src = assets.sm.paths.get(ev["sound"]) if hasattr(assets.sm, "paths") \
            else None
        if not src:
            continue
        inputs += ["-i", src]
        i = idx_base + sfx_count
        delay = int(ev["t"] * 1000)
        chains.append("[%d:a]aresample=%d,adelay=%d:all=1[sfx%d]"
                      % (i, C.SAMPLE_RATE, delay, sfx_count))
        labels.append("[sfx%d]" % sfx_count)
        sfx_count += 1

    if not labels:
        return inputs, []

    chains_str = ";".join(chains)
    if len(labels) == 1:
        mix = f"{chains_str};{labels[0]}apad[aout]"
    else:
        mix = (f"{chains_str};{''.join(labels)}"
               f"amix=inputs={len(labels)}:normalize=0:dropout_transition=0,apad[aout]")
    return inputs, ["-filter_complex", mix, "-map", "[aout]"]


def _build_command(out_path, fps, audio_inputs, audio_filters):
    cmd = [ffmpeg_path(), "-y",
           "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{C.FRAME_W}x{C.FRAME_H}", "-r", str(fps),
           "-i", "-"]
    cmd += audio_inputs
    cmd += ["-map", "0:v"]
    cmd += audio_filters
    cmd += [
        "-c:v", C.VIDEO_CODEC, "-preset", C.EXPORT_PRESET, "-crf",
        str(C.EXPORT_CRF), "-pix_fmt", "yuv420p",
        "-c:a", C.AUDIO_CODEC, "-shortest",
        out_path,
    ]
    return cmd