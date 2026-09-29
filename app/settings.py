"""Persistent user settings for Scene Puppet."""
import json
import os

from . import config as C

SETTINGS_PATH = os.path.join(C.ROOT, "settings.json")

DEFAULTS = {
    "media_initial_dir": C.ASSETS_DIR,
    "default_pause_transition": "curtain",
    "pause_duration": C.TRANSITION_DURATION,
    "panel_width": C.PANEL_W,
    "fullscreen": False,
    "window_width": C.WINDOW_W,
    "window_height": C.WINDOW_H,
}


def _validate(settings):
    data = dict(DEFAULTS)
    if isinstance(settings, dict):
        for key in DEFAULTS:
            if key in settings:
                data[key] = settings[key]

    transition = data.get("default_pause_transition")
    if transition not in C.TRANSITION_KINDS:
        transition = DEFAULTS["default_pause_transition"]
    data["default_pause_transition"] = transition

    try:
        pause_duration = float(data.get("pause_duration",
                                        DEFAULTS["pause_duration"]))
    except (TypeError, ValueError):
        pause_duration = DEFAULTS["pause_duration"]
    pause_duration = max(C.PAUSE_DURATION_MIN,
                         min(C.PAUSE_DURATION_MAX, pause_duration))
    data["pause_duration"] = round(pause_duration, 3)

    path = data.get("media_initial_dir")
    if not isinstance(path, str) or not path or not os.path.isdir(path):
        path = DEFAULTS["media_initial_dir"]
    data["media_initial_dir"] = os.path.abspath(path)

    try:
        panel_width = int(data.get("panel_width", DEFAULTS["panel_width"]))
    except (TypeError, ValueError):
        panel_width = DEFAULTS["panel_width"]
    data["panel_width"] = max(C.PANEL_MIN_W, panel_width)

    fullscreen = data.get("fullscreen", DEFAULTS["fullscreen"])
    if isinstance(fullscreen, str):
        fullscreen = fullscreen.strip().lower() in ("1", "true", "yes", "on")
    data["fullscreen"] = bool(fullscreen)

    try:
        window_width = int(data.get("window_width", DEFAULTS["window_width"]))
    except (TypeError, ValueError):
        window_width = DEFAULTS["window_width"]
    data["window_width"] = max(C.MIN_WINDOW_W, window_width)

    try:
        window_height = int(data.get("window_height", DEFAULTS["window_height"]))
    except (TypeError, ValueError):
        window_height = DEFAULTS["window_height"]
    data["window_height"] = max(C.MIN_WINDOW_H, window_height)

    return data


def load_settings():
    data = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            data.update(loaded)
    except Exception:
        pass
    return _validate(data)


def save_settings(settings):
    data = _validate(settings)
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
    return data