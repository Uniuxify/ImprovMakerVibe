"""Persistent user settings for Scene Puppet."""
import json
import os

from . import config as C

SETTINGS_PATH = os.path.join(C.ROOT, "settings.json")

DEFAULTS = {
    "media_initial_dir": C.ASSETS_DIR,
    "default_pause_transition": "curtain",
    "panel_width": C.PANEL_W,
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

    path = data.get("media_initial_dir")
    if not isinstance(path, str) or not path or not os.path.isdir(path):
        path = DEFAULTS["media_initial_dir"]
    data["media_initial_dir"] = os.path.abspath(path)

    try:
        panel_width = int(data.get("panel_width", DEFAULTS["panel_width"]))
    except (TypeError, ValueError):
        panel_width = DEFAULTS["panel_width"]
    data["panel_width"] = max(C.PANEL_MIN_W, panel_width)

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