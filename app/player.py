"""Runtime evaluation of an event log + real-time player.

`Runtime` turns an EventLog into a live stage state at any time t. It is used
by both real-time playback and by the exporter, guaranteeing identical output.

Discrete events (scene_change, background, sprite_add/remove, sound, pause)
are applied as the clock passes them. Move events are precomputed into
per-sprite keyframe tracks and linearly interpolated for smooth motion.
"""
import os

import pygame

from . import config as C
from . import transitions
from .sprite import Sprite
from .scene import Scene


class Runtime:
    def __init__(self, log, assets):
        self.log = log
        self.assets = assets            # object with get_image/get_background
        self.scenes = {}                # name -> Scene
        self.active = None
        self.tracks = {}                # scene -> sprite -> [(t,x,y)]
        self.scale_tracks = {}          # scene -> sprite -> [(t,sx,sy)]
        self.events = sorted(log.events, key=lambda e: e["t"])
        self.duration = log.duration
        self._idx = 0
        self.transition = None          # {kind,start,mid,end,switch_scene}
        self.triggered_sounds = []
        self._build()

    # ---- construction -------------------------------------------------
    def _build(self):
        start = self.log.start_state or {"scenes": []}
        for sd in start.get("scenes", []):
            sc = Scene(sd.get("name", "scene1"))
            sc.bg_key = sd.get("background")
            sc.background = self.assets.get_background(sc.bg_key)
            for spr in sd.get("sprites", []):
                img = self.assets.get_image(spr.get("image") or spr.get("name"))
                sp = Sprite(spr.get("name", "sprite"), img,
                            spr.get("x", 0), spr.get("y", 0),
                            image_key=spr.get("image"),
                            scale_x=spr.get("scale_x", 1.0),
                            scale_y=spr.get("scale_y", 1.0),
                            flip_x=spr.get("flip_x", False),
                            flip_y=spr.get("flip_y", False))
                sc.sprites.append(sp)
            self.scenes[sc.name] = sc
        if not self.scenes:
            self.scenes["scene1"] = Scene("scene1")
        self.active = list(self.scenes.values())[0]

        # first pass: build move tracks tagged with the active scene at that time
        cur = self.active.name
        for ev in self.events:
            et = ev["type"]
            if et == "scene_change":
                if ev["scene"] in self.scenes:
                    cur = ev["scene"]
            elif et == "pause":
                # a pause may switch scenes at its midpoint
                if ev.get("scene") in self.scenes:
                    cur = ev["scene"]
            elif et == "move":
                tr = self.tracks.setdefault(cur, {}).setdefault(ev["sprite"], [])
                tr.append((ev["t"], ev["x"], ev["y"]))
            elif et == "scale":
                tr = self.scale_tracks.setdefault(
                    cur, {}).setdefault(ev["sprite"], [])
                tr.append((ev["t"],
                           ev.get("scale_x", 1.0),
                           ev.get("scale_y", 1.0)))

    # ---- runtime stepping --------------------------------------------
    def reset(self):
        self.__init__(self.log, self.assets)

    def _apply_pending_switch(self, at_t):
        """Apply the scene switch scheduled by a pause transition once the
        timeline reaches its midpoint (before events logged at the midpoint).
        """
        tr = self.transition
        if tr and tr.get("switch_scene") and at_t >= tr["mid"]:
            sc = self.scenes.get(tr["switch_scene"])
            if sc is not None:
                self.active = sc
            tr["switch_scene"] = None

    def update_to(self, t):
        """Advance state to absolute time t. Returns list of sounds triggered."""
        self.triggered_sounds = []
        n = len(self.events)
        while self._idx < n and self.events[self._idx]["t"] <= t:
            ev = self.events[self._idx]
            # a pause may switch scenes at its midpoint: apply the switch
            # before any midpoint event so adds/removes land on the new scene
            self._apply_pending_switch(ev["t"])
            self._apply(ev)
            self._idx += 1
        # ensure the switch still happens if no event triggered it
        self._apply_pending_switch(t)
        self._interpolate(t)
        return self.triggered_sounds

    def _apply(self, ev):
        et = ev["type"]
        if et == "scene_change":
            sc = self.scenes.get(ev["scene"])
            if sc is not None:
                self.active = sc
        elif et == "background":
            self.active.bg_key = ev["background"]
            self.active.background = self.assets.get_background(ev["background"])
        elif et == "sprite_add":
            self._add_sprite(ev)
        elif et == "sprite_remove":
            self._remove_sprite(ev)
        elif et == "scale":
            sp = self.active.sprite_by_name(ev["sprite"])
            if sp is not None:
                sp.set_scale(ev.get("scale_x", 1.0), ev.get("scale_y", 1.0))
        elif et == "flip":
            sp = self.active.sprite_by_name(ev["sprite"])
            if sp is not None:
                sp.set_flip(ev.get("flip_x"), ev.get("flip_y"))
        elif et == "z_order":
            sp = self.active.sprite_by_name(ev["sprite"])
            if sp is not None:
                act = ev.get("action")
                if act == "up":
                    self.active.move_sprite_up(sp)
                elif act == "down":
                    self.active.move_sprite_down(sp)
                elif act == "front":
                    self.active.bring_to_front(sp)
                elif act == "back":
                    self.active.send_to_back(sp)
        elif et == "sound":
            self.triggered_sounds.append(ev["sound"])
        elif et == "pause":
            start = ev["t"]
            # Fixed open/close animation length; `hold` is how long the
            # transition stays fully closed (the configurable pause time).
            anim = C.TRANSITION_DURATION / 2.0
            hold = ev.get("hold")
            if hold is None:
                # backward compatibility: older logs stored the total length
                total = ev.get("duration", C.TRANSITION_DURATION)
                hold = max(0.0, total - C.TRANSITION_DURATION)
            hold = max(0.0, float(hold))
            self.transition = {
                "kind": ev.get("transition", "curtain"),
                "start": start,
                "mid": start + anim,                # fully closed
                "hold_end": start + anim + hold,    # starts to open
                "end": start + anim + hold + anim,  # fully open
                "switch_scene": ev.get("scene"),
            }

    def _add_sprite(self, ev):
        sc = self.active
        if sc.sprite_by_name(ev["sprite"]):
            return
        img = self.assets.get_image(ev.get("image") or ev["sprite"])
        sp = Sprite(ev["sprite"], img, ev.get("x", 0), ev.get("y", 0),
                    image_key=ev.get("image"),
                    scale_x=ev.get("scale_x", 1.0),
                    scale_y=ev.get("scale_y", 1.0),
                    flip_x=ev.get("flip_x", False),
                    flip_y=ev.get("flip_y", False))
        sc.sprites.append(sp)

    def _remove_sprite(self, ev):
        sp = self.active.sprite_by_name(ev["sprite"])
        if sp:
            self.active.remove_sprite(sp)

    def _interpolate(self, t):
        scene = self.active.name
        # position: fully determined by the move track
        for name, tr in self.tracks.get(scene, {}).items():
            sp = self.active.sprite_by_name(name)
            if sp is None or not tr:
                continue
            x, y = _lerp_track(tr, t)
            sp.x, sp.y = x, y
        # scale: size only; position is handled above
        for name, tr in self.scale_tracks.get(scene, {}).items():
            sp = self.active.sprite_by_name(name)
            if sp is None or not tr:
                continue
            sx, sy = _lerp_scale(tr, t)
            sp.set_scale(sx, sy)

    # ---- drawing ------------------------------------------------------
    def transition_cover(self, t):
        tr = self.transition
        if not tr or t < tr["start"] or t >= tr["end"]:
            return 0.0, None
        if t < tr["mid"]:
            # closing
            span = max(1e-6, tr["mid"] - tr["start"])
            cover = (t - tr["start"]) / span
        elif t < tr["hold_end"]:
            # fully closed for the configured pause duration
            cover = 1.0
        else:
            # opening
            span = max(1e-6, tr["end"] - tr["hold_end"])
            cover = 1.0 - (t - tr["hold_end"]) / span
        return max(0.0, min(1.0, cover)), tr["kind"]

    def render(self, frame_surface, t):
        self.active.draw_frame(frame_surface)
        cover, kind = self.transition_cover(t)
        if cover > 0.0:
            transitions.draw(cover, kind, frame_surface)


def _lerp_track(tr, t):
    if t <= tr[0][0]:
        return tr[0][1], tr[0][2]
    if t >= tr[-1][0]:
        return tr[-1][1], tr[-1][2]
    lo, hi = 0, len(tr) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if tr[mid][0] <= t:
            lo = mid
        else:
            hi = mid
    t0, x0, y0 = tr[lo]
    t1, x1, y1 = tr[hi]
    span = t1 - t0
    if span <= 1e-6:
        return x1, y1
    if span > C.TRACK_LERP_MAX_GAP:
        # это пауза между двумя движениями — держим позицию до паузы
        return x0, y0
    a = (t - t0) / span
    return x0 + (x1 - x0) * a, y0 + (y1 - y0) * a


def _lerp_scale(tr, t):
    """Interpolate scale only within a dense resize burst; across gaps, hold."""
    if t <= tr[0][0]:
        return tr[0][1], tr[0][2]
    if t >= tr[-1][0]:
        return tr[-1][1], tr[-1][2]
    lo, hi = 0, len(tr) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if tr[mid][0] <= t:
            lo = mid
        else:
            hi = mid
    e0, e1 = tr[lo], tr[hi]
    gap = e1[0] - e0[0]
    if gap > C.TRACK_LERP_MAX_GAP:
        # разные ресайзы — держим значение левого события
        return e0[1], e0[2]
    span = gap
    if span <= 1e-6:
        return e1[1], e1[2]
    a = (t - e0[0]) / span
    return (e0[1] + (e1[1] - e0[1]) * a,
            e0[2] + (e1[2] - e0[2]) * a)


class Player:
    """Real-time playback of a Runtime."""

    def __init__(self, sound_manager, assets):
        self.sm = sound_manager
        self.assets = assets
        self.runtime = None
        self.t = 0.0
        self.playing = False
        self.mic_channel = None
        self.mic_sound = None

    def start(self, log):
        self.stop()
        self.runtime = Runtime(log, self.assets)
        self.t = 0.0
        self.playing = True
        self._start_mic(log)
        self.runtime.update_to(0.0)

    def _start_mic(self, log):
        if not log.mic_path:
            return
        path = log.mic_path
        if not os.path.isabs(path):
            path = os.path.join(self.assets.root, path)
        if not os.path.exists(path):
            return
        try:
            self.mic_sound = pygame.mixer.Sound(path)
            self.mic_channel = self.mic_sound.play()
        except pygame.error as exc:
            print(f"[player] mic playback failed: {exc}")

    def update(self, dt):
        if not self.playing or self.runtime is None:
            return False
        self.t += dt
        if self.t >= self.runtime.duration:
            self.t = self.runtime.duration
            sounds = self.runtime.update_to(self.t)
            for name in sounds:
                self.sm.play(name)
            self.playing = False
            return True
        sounds = self.runtime.update_to(self.t)
        for name in sounds:
            self.sm.play(name)
        return False

    def render(self, frame_surface):
        if self.runtime is not None:
            self.runtime.render(frame_surface, self.t)

    def stop(self):
        self.playing = False
        if self.mic_channel is not None:
            try:
                self.mic_channel.stop()
            except Exception:
                pass
        self.mic_channel = None
        self.mic_sound = None
        self.sm.stop_all()