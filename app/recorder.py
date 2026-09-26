"""Event-log recorder.

A recording is a list of timestamped events plus a snapshot of the stage
state at t=0. Playback/export clone the start state and apply events over time.
Move events are stored as keyframes (one per frame in which the position
changed); the player interpolates between them for smooth motion.
"""
import copy
import json


class EventLog:
    def __init__(self):
        self.duration = 0.0
        self.events = []          # list[dict] with a "t" key
        self.start_state = None   # serialised stage at t=0
        self.mic_path = None      # relative path to recorded mic wav

    def sort(self):
        self.events.sort(key=lambda e: e["t"])

    def to_dict(self):
        return {
            "duration": self.duration,
            "start_state": self.start_state,
            "mic": self.mic_path,
            "events": self.events,
        }

    def save(self, path):
        self.sort()
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, ensure_ascii=False)

    @staticmethod
    def load(path):
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        log = EventLog()
        log.duration = data.get("duration", 0.0)
        log.events = data.get("events", [])
        log.start_state = data.get("start_state")
        log.mic_path = data.get("mic")
        
        return log


class Recorder:
    def __init__(self):
        self.log = EventLog()
        self._last_pos = {}     # sprite name -> (x, y) last logged
        self._last_scale = {}   # sprite name -> (sx, sy) last logged
        self._recording = False

    @property
    def recording(self):
        return self._recording

    def start(self, stage_snapshot_dict):
        self.log = EventLog()
        self.log.start_state = copy.deepcopy(stage_snapshot_dict)
        self._last_pos = {}
        self._last_scale = {}
        self._recording = True

    def stop(self, duration):
        self._recording = False
        self.log.duration = duration
        self.log.sort()

    def _add(self, t, **fields):
        if not self._recording:
            return
        ev = {"t": round(float(t), 4)}
        ev.update(fields)
        self.log.events.append(ev)

    def log_move(self, t, sprite, x, y, force=False):
        key = sprite.name
        prev = self._last_pos.get(key)
        if not force and prev is not None and prev == (x, y):
            return
        self._last_pos[key] = (x, y)
        self._add(t, type="move", sprite=key, x=round(float(x), 2),
                  y=round(float(y), 2))

    def log_sound(self, t, name):
        self._add(t, type="sound", sound=name)

    def log_pause(self, t, transition, duration, scene):
        self._add(t, type="pause", transition=transition,
                  duration=round(float(duration), 3), scene=scene)

    def log_scene_change(self, t, scene):
        self._add(t, type="scene_change", scene=scene)

    def log_background(self, t, background):
        self._add(t, type="background", background=background)

    def log_sprite_add(self, t, sprite):
        self._add(t, type="sprite_add", sprite=sprite.name,
                image=sprite.image_key, x=sprite.x, y=sprite.y,
                scale_x=sprite.scale_x, scale_y=sprite.scale_y,
                flip_x=sprite.flip_x, flip_y=sprite.flip_y)
        self._last_pos[sprite.name] = (sprite.x, sprite.y)
        self._last_scale[sprite.name] = (round(sprite.scale_x, 4),
                                     round(sprite.scale_y, 4))

    def log_flip(self, t, sprite, flip_x, flip_y):
        self._add(t, type="flip", sprite=sprite.name,
                  flip_x=bool(flip_x), flip_y=bool(flip_y))

    def log_z_order(self, t, sprite, action):
        self._add(t, type="z_order", sprite=sprite.name, action=str(action))

    def log_scale(self, t, sprite, scale_x, scale_y,
                anchor_x=None, anchor_side_x=None,
                anchor_y=None, anchor_side_y=None,
                force=False):
        key = sprite.name
        sx = round(float(scale_x), 4)
        sy = round(float(scale_y), 4)
        prev = self._last_scale.get(key)
        if not force and prev is not None and prev == (sx, sy):
            return
        self._last_scale[key] = (sx, sy)

        fields = {"type": "scale", "sprite": key,
                "scale_x": sx, "scale_y": sy}
        # optional pinned-edge info so playback keeps the opposite side fixed
        if anchor_x is not None:
            fields["ax"] = round(float(anchor_x), 2)
            fields["axs"] = anchor_side_x
        if anchor_y is not None:
            fields["ay"] = round(float(anchor_y), 2)
            fields["ays"] = anchor_side_y
        self._add(t, **fields)

    def log_sprite_remove(self, t, sprite):
        self._add(t, type="sprite_remove", sprite=sprite.name)
        self._last_pos.pop(sprite.name, None)
        self._last_scale.pop(sprite.name, None)