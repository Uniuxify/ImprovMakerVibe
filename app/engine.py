"""Application engine: main loop, modes, input handling and rendering."""
import os
import time

import pygame

from . import config as C
from . import transitions
from . import exporter
from . import project_io
from . import ui
from .assets_lib import Assets
from .sound import SoundManager
from .mic import MicRecorder
from .scene import Scene
from .sprite import Sprite, HANDLE_TOL
from .view import View
from .recorder import Recorder
from .player import Player
from .panels import PanelManager, ROW_H, THUMB

MODE_EDIT = "EDIT"
MODE_RECORD = "RECORD"
MODE_PAUSING = "PAUSING"
MODE_PAUSED = "PAUSED"
MODE_RESUMING = "RESUMING"
MODE_PLAY = "PLAY"
MODE_EXPORT = "EXPORT"


class Engine:
    def __init__(self):
        pygame.init()
        C.ensure_dirs()
        self.screen = pygame.display.set_mode((C.WINDOW_W, C.WINDOW_H))
        pygame.display.set_caption("Scene Puppet")
        self.clock = pygame.time.Clock()

        self.sm = SoundManager()
        self.assets = Assets(self.sm)
        self.mic = MicRecorder()
        self.recorder = Recorder()
        self.view = View()

        # stage
        from .scene import Stage
        self.stage = Stage()
        self.assets.ensure_builtin_backgrounds()
        self.stage.active.background = self.assets.get_background(
            "gradient_sky")
        self.stage.active.bg_key = "gradient_sky"

        # panels
        panel_rect = pygame.Rect(C.STAGE_W, C.UI_TOP_H, C.PANEL_W,
                                 C.STAGE_H)
        self.panels = PanelManager(panel_rect)

        # playback
        self.player = Player(self.sm, self.assets)

        # modes
        self.mode = MODE_EDIT
        self.t = 0.0                    # recording clock (seconds)
        self.trans_kind = "curtain"
        self.trans_timer = 0.0
        self.pause_start_t = 0.0
        self.pause_wall_start = 0.0
        self.scene_changed_in_pause = False
        self._pending_pause_event = None
        self.status = "Ready. Drag sprites from the panel onto the stage."

        # resolution
        self.frame_w = C.FRAME_W
        self.frame_h = C.FRAME_H

        # interaction
        self.selected_sprites = []      # list of selected Sprite objects
        self.dragging_sprites = []      # list of sprites being moved
        self.drag_offsets = {}          # sprite -> (offset_x, offset_y)
        self.clipboard = []             # list of copied sprite dicts
        self.resizing = None            # Sprite being resized
        self.resize_handle = None
        self._pin_x = 0.0
        self._pin_side_x = None         # "left" or "right"
        self._pin_y = 0.0
        self._pin_side_y = None         # "top" or "bottom"
        self.panning = False            # middle-mouse drag panning the view
        self._pan_last = (0, 0)
        self.frame_surf = pygame.Surface((self.frame_w, self.frame_h))

        self._build_toolbar()
        self.refresh_panels()

    @property
    def selected(self):
        return self.selected_sprites[-1] if self.selected_sprites else None

    @selected.setter
    def selected(self, val):
        if val is None:
            self.selected_sprites = []
        elif val in self.selected_sprites:
            self.selected_sprites.remove(val)
            self.selected_sprites.append(val)
        else:
            self.selected_sprites = [val]

    # ---- toolbar / panels --------------------------------------------
    def _build_toolbar(self):
        self.buttons = {}
        x = 8
        y = 8
        h = C.UI_TOP_H - 16
        specs = [
            ("record", "Record", 110, C.COL_RECORD),
            ("pause", "Pause", 90, C.COL_BUTTON),
            ("play", "Play", 90, C.COL_BUTTON),
            ("export", "Export", 100, C.COL_BUTTON),
            ("save", "Save", 80, C.COL_BUTTON),
            ("load", "Load", 80, C.COL_BUTTON),
            ("resolution", f"{self.frame_w}x{self.frame_h}", 115, C.COL_BUTTON),
            ("add_sprite", "+ Sprite", 100, C.COL_BUTTON),
            ("add_sound", "+ Sound", 100, C.COL_BUTTON),
            ("add_bg", "+ Background", 130, C.COL_BUTTON),
            ("panels", "Panels", 90, C.COL_BUTTON),
        ]
        for key, label, w, col in specs:
            rect = pygame.Rect(x, y, w, h)
            self.buttons[key] = ui.Button(rect, label, color=col)
            x += w + 6

    def refresh_panels(self):
        # sprites
        sp_items = []
        for key, surf in self.assets.images.items():
            thumb = pygame.transform.smoothscale(surf, (THUMB, THUMB))
            sp_items.append({"key": key, "label": key, "thumb": thumb})
        self.panels.panels["Sprites"].set_items(sp_items)

        # sounds
        snd_items = [{"key": n, "label": n, "thumb": None}
                     for n in sorted(self.sm.sounds.keys())]
        self.panels.panels["Sounds"].set_items(snd_items)

        # backgrounds
        bg_items = []
        for key in sorted(self.assets.backgrounds.keys()):
            surf = self.assets.backgrounds[key]
            thumb = pygame.transform.smoothscale(surf, (THUMB, THUMB))
            bg_items.append({"key": key, "label": key, "thumb": thumb})
        self.panels.panels["Backgrounds"].set_items(bg_items)

        # scenes
        sc_items = [{"key": s.name, "label": s.name, "thumb": None}
                    for s in self.stage.scenes]
        sc_items.append({"key": "__add__", "label": "+ New scene",
                         "thumb": None})
        self.panels.panels["Scenes"].set_items(sc_items)

    # ---- main loop ----------------------------------------------------
    def run(self):
        running = True
        while running:
            dt = self.clock.tick(C.FPS) / 1000.0
            mouse_pos = pygame.mouse.get_pos()
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False
                else:
                    self.handle_event(event, mouse_pos)
            self.update(dt)
            self.draw()
            pygame.display.flip()
        pygame.quit()

    def update(self, dt):
        if self.mode == MODE_RECORD:
            self.t += dt
        elif self.mode == MODE_PAUSING:
            self.trans_timer += dt
            if self.trans_timer >= C.TRANSITION_DURATION / 2:
                self.mode = MODE_PAUSED
                self.status = ("Paused. Rearrange objects / switch scene, "
                               "then press Pause to resume.")
        elif self.mode == MODE_RESUMING:
            self.trans_timer += dt
            if self.trans_timer >= C.TRANSITION_DURATION / 2:
                self._finish_resume()
        elif self.mode == MODE_PLAY:
            finished = self.player.update(dt)
            if finished:
                self.mode = MODE_EDIT
                self.player.stop()
                self.status = "Playback finished."

    # ---- input --------------------------------------------------------
    def handle_event(self, event, mouse_pos):
        # toolbar buttons
        for key, btn in self.buttons.items():
            if btn.handle_event(event, mouse_pos):
                self.on_button(key)
                return
        # panel events
        action = self.panels.handle_event(event, mouse_pos)
        if action:
            self.on_panel_action(action)
            return
        # stage interaction
        self.handle_stage(event, mouse_pos)

    def _flip_buttons(self, sp):
        sx, sy = self.view.w2s(sp.x, sp.y)
        ex, ey = self.view.w2s(sp.x + sp.w, sp.y + sp.h)
        mid_x = int((sx + ex) / 2)
        btn_h = pygame.Rect(mid_x - 62, int(ey + 8), 58, 22)
        btn_v = pygame.Rect(mid_x + 4, int(ey + 8), 58, 22)
        return btn_h, btn_v

    def handle_stage(self, event, mouse_pos):
        if self.mode == MODE_PLAY:
            return
        sx, sy = getattr(event, "pos", mouse_pos)

        # middle mouse button: pan the view (allowed anywhere on the stage,
        # and continues even if the cursor drifts over the panel area)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 2:
            self.panning = True
            self._pan_last = (sx, sy)
            return

        if self.panels.visible and sx >= C.STAGE_W and not self.panning:
            return

        # mouse wheel: zoom or z-order
        if event.type == pygame.MOUSEWHEEL:
            mods = pygame.key.get_mods()
            if mods & pygame.KMOD_CTRL:
                factor = 1.1 if event.y > 0 else 0.9
                self.view.zoom(factor, sx, sy)
                return
            elif self.selected is not None and self.selected in self.stage.active.sprites and self._editable():
                if event.y > 0:
                    self.stage.active.move_sprite_up(self.selected)
                    if self.mode == MODE_RECORD:
                        self.recorder.log_z_order(self.t, self.selected, "up")
                elif event.y < 0:
                    self.stage.active.move_sprite_down(self.selected)
                    if self.mode == MODE_RECORD:
                        self.recorder.log_z_order(self.t, self.selected, "down")
                return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            wx, wy = self.view.s2w(sx, sy)
            sc = self.stage.active
            # 1. Flip buttons for selected sprite
            if self.selected is not None and self.selected in sc.sprites and self._editable():
                btn_h, btn_v = self._flip_buttons(self.selected)
                if btn_h.collidepoint(sx, sy):
                    self.selected.toggle_flip_h()
                    if self.mode == MODE_RECORD:
                        self.recorder.log_flip(self.t, self.selected,
                                               self.selected.flip_x, self.selected.flip_y)
                    return
                if btn_v.collidepoint(sx, sy):
                    self.selected.toggle_flip_v()
                    if self.mode == MODE_RECORD:
                        self.recorder.log_flip(self.t, self.selected,
                                               self.selected.flip_x, self.selected.flip_y)
                    return

            # 2. Resize handles of the primary selected sprite
            if (self.selected is not None and self.selected in sc.sprites
                    and self._editable()):
                handle = self.selected.hit_handle(
                    wx, wy, tol=HANDLE_TOL / self.view.scale)
                if handle is not None:
                    self._start_resize(self.selected, handle)
                    return

            # 3. Sprite selection & multi-select
            hit = sc.find_sprite(wx, wy)
            is_shift = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
            if hit is not None and self._editable():
                if is_shift:
                    if hit in self.selected_sprites:
                        self.selected_sprites.remove(hit)
                    else:
                        self.selected_sprites.append(hit)
                else:
                    if hit not in self.selected_sprites:
                        self.selected_sprites = [hit]

                if hit in self.selected_sprites:
                    self.dragging_sprites = list(self.selected_sprites)
                    self.drag_offsets = {s: (wx - s.x, wy - s.y) for s in self.selected_sprites}
                    if self.mode == MODE_RECORD:
                        for s in self.selected_sprites:
                            self.recorder.log_move(self.t, s, s.x, s.y, force=True)
            else:
                if not is_shift:
                    self.selected_sprites = []

        elif event.type == pygame.MOUSEMOTION:
            if self.panning:
                dx = sx - self._pan_last[0]
                dy = sy - self._pan_last[1]
                self.view.pan(dx, dy)
                self._pan_last = (sx, sy)
                return
            wx, wy = self.view.s2w(sx, sy)
            if self.resizing is not None and self._editable():
                self._resize_to(wx, wy)
            elif self.dragging_sprites and self._editable():
                for s in self.dragging_sprites:
                    ox, oy = self.drag_offsets[s]
                    s.x = wx - ox
                    s.y = wy - oy
                    if self.mode == MODE_RECORD:
                        self.recorder.log_move(self.t, s, s.x, s.y)

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 2:
            self.panning = False

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.dragging_sprites and self.mode == MODE_RECORD:
                for s in self.dragging_sprites:
                    self.recorder.log_move(self.t, s, s.x, s.y, force=True)
            self.dragging_sprites = []
            self.resizing = None
            self.resize_handle = None

        elif event.type == pygame.KEYDOWN and self._editable():
            mods = pygame.key.get_mods()
            ctrl = bool(mods & pygame.KMOD_CTRL)
            if event.key == pygame.K_DELETE:
                for sp in list(self.selected_sprites):
                    if self.mode == MODE_RECORD:
                        self.recorder.log_sprite_remove(self.t, sp)
                    self.stage.active.remove_sprite(sp)
                self.selected_sprites = []
            elif ctrl and event.key == pygame.K_c:
                self.clipboard = [sp.to_dict() for sp in self.selected_sprites
                                  if sp in self.stage.active.sprites]
                self.status = f"Copied {len(self.clipboard)} sprite(s)."
            elif ctrl and event.key == pygame.K_v:
                self._paste_clipboard()

    def _make_unique_sprite_name(self, base_name):
        all_names = {sp.name for sc in self.stage.scenes for sp in sc.sprites}
        candidate = f"{base_name}_copy"
        i = 1
        while candidate in all_names:
            i += 1
            candidate = f"{base_name}_copy{i}"
        return candidate

    def _paste_clipboard(self):
        if not self.clipboard:
            return
        new_sprites = []
        for d in self.clipboard:
            name = self._make_unique_sprite_name(d["name"])
            img = self.assets.get_image(d.get("image") or d["name"])
            sp = Sprite(name, img,
                        d.get("x", 0) + 30, d.get("y", 0) + 30,
                        image_key=d.get("image"),
                        scale_x=d.get("scale_x", 1.0),
                        scale_y=d.get("scale_y", 1.0),
                        flip_x=d.get("flip_x", False),
                        flip_y=d.get("flip_y", False))
            self.stage.active.add_sprite(sp)
            if self.mode == MODE_RECORD:
                self.recorder.log_sprite_add(self.t, sp)
                self.recorder.log_move(self.t, sp, sp.x, sp.y, force=True)
            new_sprites.append(sp)
        self.selected_sprites = new_sprites
        self.status = f"Pasted {len(new_sprites)} sprite(s)."

    def _editable(self):
        return self.mode in (MODE_EDIT, MODE_RECORD, MODE_PAUSED)

    # ---- resizing -----------------------------------------------------
    def _start_resize(self, sp, handle):
        self.resizing = sp
        self.resize_handle = handle
        self._pin_x = 0.0
        self._pin_side_x = None
        self._pin_y = 0.0
        self._pin_side_y = None

        # 8 handles support (4 sides + 4 corners)
        if "right" in handle:
            self._pin_x = float(round(sp.x))
            self._pin_side_x = "left"
        elif "left" in handle:
            self._pin_x = float(round(sp.x + sp.w))
            self._pin_side_x = "right"

        if "bottom" in handle:
            self._pin_y = float(round(sp.y))
            self._pin_side_y = "top"
        elif "top" in handle:
            self._pin_y = float(round(sp.y + sp.h))
            self._pin_side_y = "bottom"

    def _resize_to(self, wx, wy):
        sp = self.resizing
        h = self.resize_handle
        if sp is None or h is None:
            return

        is_shift = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
        new_w = sp.w
        new_h = sp.h

        # Compute raw desired width
        if self._pin_side_x == "left":
            new_w = max(1, round(wx) - int(self._pin_x))
        elif self._pin_side_x == "right":
            new_w = max(1, int(self._pin_x) - round(wx))

        # Compute raw desired height
        if self._pin_side_y == "top":
            new_h = max(1, round(wy) - int(self._pin_y))
        elif self._pin_side_y == "bottom":
            new_h = max(1, int(self._pin_y) - round(wy))

        # Proportional resize if Shift is held or corner handle with Shift
        if is_shift and (self._pin_side_x is not None) and (self._pin_side_y is not None):
            scale = max(new_w / sp.orig_w, new_h / sp.orig_h)
            new_w = max(1, int(round(scale * sp.orig_w)))
            new_h = max(1, int(round(scale * sp.orig_h)))

        # Apply scale
        scale_x = (new_w / sp.orig_w) if self._pin_side_x else sp.scale_x
        scale_y = (new_h / sp.orig_h) if self._pin_side_y else sp.scale_y
        sp.set_scale(scale_x, scale_y)

        # Reposition sprite so pinned edges remain completely stable
        if self._pin_side_x == "left":
            sp.x = self._pin_x
        elif self._pin_side_x == "right":
            sp.x = self._pin_x - sp.w

        if self._pin_side_y == "top":
            sp.y = self._pin_y
        elif self._pin_side_y == "bottom":
            sp.y = self._pin_y - sp.h

        if self.mode == MODE_RECORD:
            self.recorder.log_move(self.t, sp, sp.x, sp.y, force=True)
            self.recorder.log_scale(self.t, sp, sp.scale_x, sp.scale_y,
                                    anchor_x=self._pin_x if self._pin_side_x else None,
                                    anchor_side_x=self._pin_side_x,
                                    anchor_y=self._pin_y if self._pin_side_y else None,
                                    anchor_side_y=self._pin_side_y)

    # ---- buttons ------------------------------------------------------
    def on_button(self, key):
        if key == "record":
            if self.mode == MODE_EDIT:
                self.start_recording()
            elif self.mode == MODE_RECORD:
                self.stop_recording()
        elif key == "pause":
            self.on_pause()
        elif key == "play":
            if self.mode == MODE_PLAY:
                self.stop_playback()
            else:
                self.start_playback()
        elif key == "export":
            self.do_export()
        elif key == "save":
            self.do_save()
        elif key == "load":
            self.do_load()
        elif key == "resolution":
            self.choose_resolution_dialog()
        elif key == "add_sprite":
            self.add_sprite_dialog()
        elif key == "add_sound":
            self.add_sound_dialog()
        elif key == "add_bg":
            self.add_bg_dialog()
        elif key == "panels":
            self.panels.toggle()

    def start_recording(self):
        self.t = 0.0
        self.scene_changed_in_pause = False
        self.stage.active_index = 0
        self.recorder.start(self._stage_snapshot())
        self.mic.start()
        self.mode = MODE_RECORD
        self.status = "Recording..."

    def stop_recording(self):
        # capture final positions for all sprites
        for sc in self.stage.scenes:
            for sp in sc.sprites:
                self.recorder.log_move(self.t, sp, sp.x, sp.y, force=True)
        self.recorder.stop(self.t)
        # stop mic
        out = os.path.join(C.RECORDINGS_DIR,
                           f"rec_{int(time.time())}.wav")
        self.mic.stop(out)
        if os.path.exists(out):
            self.recorder.log.mic_path = os.path.relpath(out, C.ROOT).replace(
                "\\", "/")
        self.mode = MODE_EDIT
        self.status = (f"Recorded {self.t:.1f}s, "
                       f"{len(self.recorder.log.events)} events.")

    def on_pause(self):
        if self.mode == MODE_RECORD:
            self.pause_start_t = self.t
            self.pause_wall_start = time.perf_counter()
            self.mic.set_capturing(False)
            self.trans_kind = C.TRANSITION_KINDS[
                (len(self.recorder.log.events)) % len(C.TRANSITION_KINDS)]
            self.scene_changed_in_pause = False
            # anchor positions before pause so idle stretch is not drift
            for sc in self.stage.scenes:
                for sp in sc.sprites:
                    self.recorder.log_move(self.t, sp, sp.x, sp.y,
                                           force=True)
            self.recorder.log_pause(self.t, self.trans_kind,
                                    C.TRANSITION_DURATION,
                                    self.stage.active.name)
            self._pending_pause_event = self.recorder.log.events[-1]
            self.trans_timer = 0.0
            self.mode = MODE_PAUSING
            self.status = "Pausing (transition)..."
        elif self.mode == MODE_PAUSED:
            self.mode = MODE_RESUMING
            self.trans_timer = 0.0
            self.status = "Resuming..."

    def _finish_resume(self):
        # advance the recording clock to include the transition
        self.t = self.pause_start_t + C.TRANSITION_DURATION
        # keep the microphone track aligned with the recording clock:
        # the pause captured nothing, so insert exactly one transition of
        # silence before resuming capture.
        self.mic.insert_silence(C.TRANSITION_DURATION)
        self.mic.set_capturing(True)
        # teleport all sprites to their (possibly edited) paused positions,
        # logged at the transition midpoint so the cover hides the jump
        mid = self.pause_start_t + C.TRANSITION_DURATION / 2
        for sc in self.stage.scenes:
            for sp in sc.sprites:
                self.recorder.log_move(mid, sp, sp.x, sp.y, force=True)
        if self.scene_changed_in_pause and self._pending_pause_event is not None:
            self._pending_pause_event["scene"] = self.stage.active.name
        self.mode = MODE_RECORD
        self.status = "Recording..."

    def start_playback(self):
        log = self.recorder.log
        if not log.events:
            self.status = "Nothing recorded yet."
            return
        self.mode = MODE_PLAY
        self.player.start(log)
        self.status = "Playing..."

    def stop_playback(self):
        self.player.stop()
        self.mode = MODE_EDIT
        self.status = "Playback stopped."

    def do_export(self):
        log = self.recorder.log
        if not log.events:
            self.status = "Nothing to export."
            return
        out = ui.save_file(self.screen, self.clock, "Export video",
                           exts=(".mp4",), initialdir=C.PROJECTS_DIR,
                           initialfile="export.mp4")
        if not out:
            return
        self.status = "Exporting... (please wait)"
        self._draw()
        pygame.display.flip()
        try:
            exporter.export(log, self.assets, out)
            self.status = f"Exported: {out}"
        except Exception as exc:
            self.status = f"Export failed: {exc}"

    def do_save(self):
        path = ui.save_file(self.screen, self.clock, "Save project",
                            exts=(".json",), initialdir=C.PROJECTS_DIR,
                            initialfile="my_scene.json")
        if not path:
            return
        try:
            project_io.save_project(path, self.stage, self.recorder.log,
                                    self.assets, self.sm)
            self.status = f"Saved: {path}"
        except Exception as exc:
            self.status = f"Save failed: {exc}"

    def do_load(self):
        path = ui.open_file(self.screen, self.clock, "Open project",
                            exts=(".json",), initialdir=C.PROJECTS_DIR)
        if not path:
            return
        try:
            stage, log = project_io.load_project(path, self.assets, self.sm)
            self.stage = stage
            self.recorder.log = log
            self.refresh_panels()
            self.status = f"Loaded: {path}"
        except Exception as exc:
            self.status = f"Load failed: {exc}"

    def set_scene_resolution(self, w, h):
        self.frame_w = int(w)
        self.frame_h = int(h)
        C.FRAME_W = int(w)
        C.FRAME_H = int(h)
        self.view.set_frame_size(w, h)
        self.frame_surf = pygame.Surface((self.frame_w, self.frame_h))
        self.assets.rescale_backgrounds(self.frame_w, self.frame_h)
        for sc in self.stage.scenes:
            if sc.bg_key:
                sc.background = self.assets.get_background(sc.bg_key)
        if "resolution" in self.buttons:
            self.buttons["resolution"].label = f"{self.frame_w}x{self.frame_h}"
        self.status = f"Scene resolution set to {self.frame_w}x{self.frame_h}."

    def choose_resolution_dialog(self):
        presets = [
            ("1920x1080 (Full HD 16:9)", 1920, 1080),
            ("1280x720 (HD 16:9)", 1280, 720),
            ("1080x1920 (Vertical 9:16)", 1080, 1920),
            ("1080x1080 (Square 1:1)", 1080, 1080),
        ]
        box_w, box_h = 420, 310
        box = pygame.Rect((C.WINDOW_W - box_w) // 2, (C.WINDOW_H - box_h) // 2, box_w, box_h)
        buttons = []
        by = box.y + 50
        for name, pw, ph in presets:
            btn = ui.Button((box.x + 24, by, box_w - 48, 36), name)
            buttons.append((btn, pw, ph))
            by += 44
        cancel_btn = ui.Button((box.centerx - 60, box.bottom - 44, 120, 32), "Cancel")

        dialog_running = True
        while dialog_running:
            self.clock.tick(60)
            mouse = pygame.mouse.get_pos()
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                    dialog_running = False
                elif cancel_btn.handle_event(event, mouse):
                    dialog_running = False
                else:
                    for btn, pw, ph in buttons:
                        if btn.handle_event(event, mouse):
                            self.set_scene_resolution(pw, ph)
                            dialog_running = False
                            break

            dim = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
            dim.fill((0, 0, 0, 150))
            self.screen.blit(dim, (0, 0))

            pygame.draw.rect(self.screen, C.COL_PANEL, box, border_radius=8)
            pygame.draw.rect(self.screen, C.COL_ACCENT, box, 2, border_radius=8)
            ui.draw_label(self.screen, "Choose Scene Resolution", (box.x + 24, box.y + 16), size=18, bold=True)

            for btn, _, _ in buttons:
                btn.draw(self.screen)
            cancel_btn.draw(self.screen)
            pygame.display.flip()

    # ---- asset additions ---------------------------------------------
    def add_sprite_dialog(self):
        paths = ui.open_files(self.screen, self.clock, "Add sprite images",
                              exts=C.IMAGE_EXTS, initialdir=C.SPRITES_DIR)
        count = 0
        for p in paths:
            key = self.assets.load_image_file(p)
            if key and self.mode == MODE_RECORD:
                sp = Sprite(key, self.assets.get_image(key),
                            C.MARGIN + 200, C.MARGIN + 200)
                self.stage.active.add_sprite(sp)
                self.recorder.log_sprite_add(self.t, sp)
            if key:
                count += 1
        self.refresh_panels()
        self.status = f"Loaded {count} sprite(s)."

    def add_sound_dialog(self):
        paths = ui.open_files(self.screen, self.clock, "Add sounds",
                              exts=C.SOUND_EXTS, initialdir=C.SOUNDS_DIR)
        count = 0
        for p in paths:
            if self.sm.load(p):
                count += 1
        self.refresh_panels()
        self.status = f"Loaded {count} sound(s)."

    def add_bg_dialog(self):
        p = ui.open_file(self.screen, self.clock, "Add background",
                         exts=C.IMAGE_EXTS, initialdir=C.BACKGROUNDS_DIR)
        if not p:
            return
        key = self.assets.load_background_file(p)
        if key:
            self.refresh_panels()
            self.status = f"Loaded background '{key}'."

    # ---- panel actions ------------------------------------------------
    def on_panel_action(self, action):
        kind = action[0]
        if kind == "drop":
            _, _, item, pos, _thumb = action
            self.drop_sprite(item, pos)
        elif kind == "item":
            _, panel, item = action
            self.on_item_click(panel, item)

    def drop_sprite(self, item, pos):
        if not self._editable():
            return
        sx, sy = pos
        if sx >= C.STAGE_W:
            return
        key = item["key"]
        surf = self.assets.get_image(key)
        wx, wy = self.view.s2w(sx, sy)
        sp = Sprite(key, surf, wx - surf.get_width() / 2,
                    wy - surf.get_height() / 2, image_key=key)
        self.stage.active.add_sprite(sp)
        self.selected = sp
        if self.mode == MODE_RECORD:
            self.recorder.log_sprite_add(self.t, sp)
            self.recorder.log_move(self.t, sp, sp.x, sp.y, force=True)

    def on_item_click(self, panel, item):
        key = item["key"]
        if panel == "Sounds":
            self.sm.play(key)
            if self.mode == MODE_RECORD:
                self.recorder.log_sound(self.t, key)
            self.status = f"Sound: {key}"
        elif panel == "Backgrounds":
            self.stage.active.bg_key = key
            self.stage.active.background = self.assets.get_background(key)
            if self.mode == MODE_RECORD:
                self.recorder.log_background(self.t, key)
            self.status = f"Background: {key}"
        elif panel == "Scenes":
            if key == "__add__":
                sc = self.stage.add_scene()
                # if recording, register the new scene in the start snapshot
                # so it exists during playback/export
                snap = self.recorder.log.start_state
                if self.mode == MODE_RECORD and snap is not None:
                    snap.setdefault("scenes", []).append(sc.to_dict())
                self.refresh_panels()
                self.status = f"Added {sc.name}."
            else:
                self.switch_scene(key)

    def switch_scene(self, name):
        if not self._editable():
            return
        self.stage.switch_to(name)
        if self.mode == MODE_RECORD:
            self.recorder.log_scene_change(self.t, name)
        elif self.mode == MODE_PAUSED:
            self.scene_changed_in_pause = True
        self.status = f"Scene: {name}"

    # ---- serialisation helpers ---------------------------------------
    def _stage_snapshot(self):
        snap = {"scenes": []}
        for sc in self.stage.scenes:
            snap["scenes"].append(sc.to_dict())
        return snap

    # ---- drawing ------------------------------------------------------
    def draw(self):
        self._draw()
        pygame.display.flip()

    def _draw(self):
        self.screen.fill(C.COL_BG)
        self._draw_stage()
        self._draw_toolbar()
        self._sync_panel_active()
        self.panels.draw(self.screen)
        self._draw_status()

    def _sync_panel_active(self):
        self.panels.panels["Scenes"].active_key = self.stage.active.name
        self.panels.panels["Backgrounds"].active_key = \
            self.stage.active.bg_key

    def _blit_world(self, surf, wx, wy):
        """Blit a world-space surface at world (wx, wy), applying view zoom."""
        sx, sy = self.view.w2s(wx, wy)
        scale = self.view.scale
        if scale != 1.0:
            w = max(1, int(round(surf.get_width() * scale)))
            h = max(1, int(round(surf.get_height() * scale)))
            surf = pygame.transform.smoothscale(surf, (w, h))
        self.screen.blit(surf, (int(sx), int(sy)))


    def _draw_stage(self):
        stage_rect = pygame.Rect(0, C.UI_TOP_H, C.STAGE_W, C.STAGE_H)
        pygame.draw.rect(self.screen, C.COL_BUFFER, stage_rect)

        fx, fy, fw, fh = self.view.frame_rect_screen()

        if self.mode == MODE_PLAY and self.player.runtime is not None:
            self.frame_surf.fill((0, 0, 0))
            self.player.render(self.frame_surf)
            if fw != self.frame_surf.get_width() or fh != self.frame_surf.get_height():
                self.screen.blit(
                    pygame.transform.smoothscale(self.frame_surf, (fw, fh)),
                    (fx, fy))
            else:
                self.screen.blit(self.frame_surf, (fx, fy))
        else:
            sc = self.stage.active

            if sc.background is not None:
                if self.view.scale != 1.0:
                    bg = pygame.transform.smoothscale(
                        sc.background, (int(fw), int(fh)))
                else:
                    bg = sc.background
                self.screen.blit(bg, (int(fx), int(fy)))

            # sprites: world-space at their own coordinates
            for sp in sc.sprites:
                self._blit_world(sp.image, sp.x, sp.y)

            # transition overlay over the frame
            cover = self._current_cover()
            if cover > 0.0:
                overlay = pygame.Surface((C.FRAME_W, C.FRAME_H))
                overlay.fill((0, 0, 0))
                transitions.draw(cover, self.trans_kind, overlay)
                if self.view.scale != 1.0:
                    overlay = pygame.transform.smoothscale(overlay, (fw, fh))
                self.screen.blit(overlay, (fx, fy))

            # selection highlight + resize handles + flip buttons
            for sp in self.selected_sprites:
                if sp not in sc.sprites:
                    continue
                sx, sy = self.view.w2s(sp.x, sp.y)
                ex, ey = self.view.w2s(sp.x + sp.w, sp.y + sp.h)
                pygame.draw.rect(self.screen, C.COL_ACCENT,
                                (int(sx), int(sy), int(ex - sx),
                                int(ey - sy)), 2)

            if self.selected is not None and self.selected in sc.sprites:
                sp = self.selected
                # 8 resize handles
                for _n, (hx, hy) in sp.handle_points().items():
                    hxs, hys = self.view.w2s(hx, hy)
                    r = pygame.Rect(0, 0, 10, 10)
                    r.center = (int(hxs), int(hys))
                    pygame.draw.rect(self.screen, C.COL_ACCENT, r)
                    pygame.draw.rect(self.screen, (255, 255, 255), r, 1)

                # Flip buttons below sprite
                btn_h, btn_v = self._flip_buttons(sp)
                pygame.draw.rect(self.screen, C.COL_BUTTON, btn_h, border_radius=4)
                pygame.draw.rect(self.screen, C.COL_ACCENT if sp.flip_x else (100, 104, 120), btn_h, 1, border_radius=4)
                ui.draw_label(self.screen, "Flip H", (btn_h.x + 8, btn_h.y + 3), size=13,
                            color=C.COL_ACCENT if sp.flip_x else C.COL_TEXT)

                pygame.draw.rect(self.screen, C.COL_BUTTON, btn_v, border_radius=4)
                pygame.draw.rect(self.screen, C.COL_ACCENT if sp.flip_y else (100, 104, 120), btn_v, 1, border_radius=4)
                ui.draw_label(self.screen, "Flip V", (btn_v.x + 8, btn_v.y + 3), size=13,
                            color=C.COL_ACCENT if sp.flip_y else C.COL_TEXT)

        # frame border
        pygame.draw.rect(self.screen, C.COL_FRAME,
                        (fx, fy, fw, fh), 2)

    def _current_cover(self):
        half = C.TRANSITION_DURATION / 2
        if self.mode == MODE_PAUSING:
            return min(1.0, self.trans_timer / half)
        if self.mode == MODE_PAUSED:
            # keep the scene visible (dimmed) so the author can rearrange
            return 0.5
        if self.mode == MODE_RESUMING:
            return max(0.0, 1.0 - self.trans_timer / half)
        return 0.0

    def _draw_toolbar(self):
        bar = pygame.Rect(0, 0, C.WINDOW_W, C.UI_TOP_H)
        pygame.draw.rect(self.screen, C.COL_PANEL_HDR, bar)
        # set active states / labels / enablement
        recording = self.mode == MODE_RECORD
        playing = self.mode == MODE_PLAY
        self.buttons["record"].active = recording
        self.buttons["record"].toggle = True
        self.buttons["record"].label = ("Stop Recording"
                                        if recording else "Record")
        self.buttons["pause"].label = ("Resume"
                                       if self.mode == MODE_PAUSED else "Pause")
        self.buttons["play"].label = "Stop playing" if playing else "Play"
        # enablement: during playback only the play/stop toggle is available;
        # during recording Play/Export/Save/Load are blocked
        for key, btn in self.buttons.items():
            if playing:
                btn.enabled = (key == "play")
            elif recording:
                btn.enabled = key not in ("play", "export", "save", "load")
            else:
                btn.enabled = True
        for btn in self.buttons.values():
            btn.draw(self.screen)
        # mode tag - only show when not in standard EDIT mode
        if self.mode != MODE_EDIT:
            tag = ui.get_font(16, bold=True).render(self.mode, True, C.COL_ACCENT)
            self.screen.blit(tag, (C.WINDOW_W - tag.get_width() - 14, 14))

    def _draw_status(self):
        rect = pygame.Rect(0, C.WINDOW_H - C.STATUS_H, C.WINDOW_W, C.STATUS_H)
        t = self.t if self.mode in (MODE_RECORD, MODE_PAUSING, MODE_PAUSED,
                                    MODE_RESUMING) else 0.0
        text = f"{self.status}    |    t={t:.1f}s"
        ui.draw_status(self.screen, text, rect)
        zoom_text = f"Zoom: {int(round(self.view.scale * 100))}%"
        ui.draw_label(self.screen, zoom_text, (rect.right - 110, rect.y + 5), size=14, color=C.COL_ACCENT)
