"""Save/load a project: stage state, asset references and the recording.

A project is a folder containing:
  project.json   - stage, assets map and the event log
  <assets>       - copies of any referenced images/backgrounds/sounds
  mic.wav        - recorded microphone track (if any)
"""
import json
import os
import shutil

from . import config as C
from .scene import Scene, Stage
from .sprite import Sprite
from .recorder import EventLog

FORMAT = "scene_puppet_project"
VERSION = 1


def _copy_asset(src, dest_dir):
    if not src or not os.path.exists(src):
        return None
    os.makedirs(dest_dir, exist_ok=True)
    name = os.path.basename(src)
    dest = os.path.join(dest_dir, name)
    if os.path.abspath(src) != os.path.abspath(dest):
        shutil.copy2(src, dest)
    return os.path.relpath(dest, C.ROOT).replace("\\", "/")


def save_project(path, stage, log, assets, sound_manager):
    """Write the project folder. `path` is the project .json file path."""
    proj_dir = os.path.dirname(path)
    os.makedirs(proj_dir, exist_ok=True)
    a_img = os.path.join(proj_dir, "assets", "sprites")
    a_bg = os.path.join(proj_dir, "assets", "backgrounds")
    a_snd = os.path.join(proj_dir, "assets", "sounds")

    image_map = {}
    for key, src in assets.image_paths.items():
        rel = _copy_asset(src, a_img)
        if rel:
            image_map[key] = rel

    bg_map = {}
    for key, src in assets.bg_paths.items():
        rel = _copy_asset(src, a_bg)
        if rel:
            bg_map[key] = rel

    sound_map = {}
    for key, src in sound_manager.paths.items():
        rel = _copy_asset(src, a_snd)
        if rel:
            sound_map[key] = rel

    # microphone track
    mic_rel = None
    if log.mic_path:
        src = log.mic_path
        if not os.path.isabs(src):
            src = os.path.join(C.ROOT, src)
        if os.path.exists(src):
            os.makedirs(proj_dir, exist_ok=True)
            dest = os.path.join(proj_dir, "mic.wav")
            shutil.copy2(src, dest)
            mic_rel = os.path.relpath(dest, C.ROOT).replace("\\", "/")

    data = {
        "format": FORMAT,
        "version": VERSION,
        "stage": {
            "scenes": [s.to_dict() for s in stage.scenes],
            "active_index": stage.active_index,
        },
        "assets": {"images": image_map, "backgrounds": bg_map,
                   "sounds": sound_map},
        "recording": {
            "duration": log.duration,
            "start_state": log.start_state,
            "events": log.events,
            "mic": mic_rel,
        },
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    return path


def load_project(path, assets, sound_manager):
    """Load a project. Returns (stage, EventLog)."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if data.get("format") != FORMAT:
        raise ValueError("Not a Scene Puppet project file")

    # reload assets
    a = data.get("assets", {})
    for key, rel in a.get("images", {}).items():
        p = os.path.join(C.ROOT, rel)
        if os.path.exists(p):
            assets.load_image_file(p)
    for key, rel in a.get("backgrounds", {}).items():
        p = os.path.join(C.ROOT, rel)
        if os.path.exists(p):
            assets.load_background_file(p)
    for key, rel in a.get("sounds", {}).items():
        p = os.path.join(C.ROOT, rel)
        if os.path.exists(p):
            sound_manager.load(p)

    # rebuild stage
    stage = Stage()
    stage.scenes = []
    sd = data.get("stage", {})
    for scene_data in sd.get("scenes", []):
        sc = Scene(scene_data.get("name", "scene1"))
        sc.bg_key = scene_data.get("background")
        sc.background = assets.get_background(sc.bg_key)
        for spr in scene_data.get("sprites", []):
            img = assets.get_image(spr.get("image") or spr.get("name"))
            sc.sprites.append(Sprite(spr.get("name", "sprite"), img,
                                     spr.get("x", 0), spr.get("y", 0),
                                     image_key=spr.get("image"),
                                     scale_x=spr.get("scale_x", 1.0),
                                     scale_y=spr.get("scale_y", 1.0),
                                     flip_x=spr.get("flip_x", False),
                                     flip_y=spr.get("flip_y", False)))
        stage.scenes.append(sc)
    if not stage.scenes:
        stage.scenes = [Scene("scene1")]
    stage.active_index = min(sd.get("active_index", 0), len(stage.scenes) - 1)

    # rebuild event log
    rec = data.get("recording", {})
    log = EventLog()
    log.duration = rec.get("duration", 0.0)
    log.events = rec.get("events", [])
    log.start_state = rec.get("start_state")
    log.mic_path = rec.get("mic")
    return stage, log