"""Application engine: main loop, modes, input handling and rendering."""
import math
import os
import time

import pygame

from . import config as C
from . import settings as S
from . import transitions
from . import exporter
from . import project_io
from . import ui
from .assets_lib import Assets
from .sound import SoundManager
from .mic import MicRecorder
from .scene import Scene
from .sprite import Sprite, HANDLE_TOL, rotate_point
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

# Screen-pixel pad around the group frame so its handles never coincide with
# the handles of the individual sprites inside the group.
GROUP_BOX_PAD = 20
# Screen-pixel radius around a corner handle (outside the handle square)
# that starts the rotate gesture instead of resize/select.
ROTATE_TOL = 30
# Frame/handle colour used for the selection in "show hitboxes" mode.
COL_SELECTED = (225, 70, 70)
# Frame/handle colour for unselected objects when hitboxes are always on.
COL_HITBOX = (150, 152, 160)


class Engine:
    def __init__(self):
        pygame.init()
        C.ensure_dirs()
        self.settings = S.load_settings()
        self.fullscreen = bool(self.settings.get("fullscreen", False))
        self.show_hitboxes = bool(self.settings.get("show_hitboxes", False))
        try:
            window_w = int(self.settings.get("window_width", C.WINDOW_W))
        except (TypeError, ValueError):
            window_w = C.WINDOW_W
        try:
            window_h = int(self.settings.get("window_height", C.WINDOW_H))
        except (TypeError, ValueError):
            window_h = C.WINDOW_H
        window_w = max(C.MIN_WINDOW_W, window_w)
        window_h = max(C.MIN_WINDOW_H, window_h)
        self.windowed_size = (window_w, window_h)
        if self.fullscreen:
            self.window_w, self.window_h = self._desktop_size()
        else:
            # launch the windowed app maximized so it fills the screen
            self.window_w, self.window_h = self._desktop_size()
        C.WINDOW_W, C.WINDOW_H = self.window_w, self.window_h
        self.screen = self._set_display_mode((self.window_w, self.window_h),
                                             self._window_flags())
        if not self.fullscreen:
            self._maximize_window()
        pygame.display.set_caption("Improv Maker")
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
        # load user assets that live in the assets/ folders on startup
        self.load_assets_from_disk()
        self.stage.active.background = self.assets.get_background(
            "gradient_sky")
        self.stage.active.bg_key = "gradient_sky"

        # panels
        max_panel_w = C.max_panel_width(C.WINDOW_W)
        try:
            self.panel_width = int(self.settings.get("panel_width", C.PANEL_W))
        except (TypeError, ValueError):
            self.panel_width = C.PANEL_W
        self.panel_width = max(C.PANEL_W, min(max_panel_w, self.panel_width))
        self.stage_w = C.WINDOW_W
        self.stage_h = C.stage_height(self.window_h)
        panel_rect = pygame.Rect(C.WINDOW_W - self.panel_width,
                                 C.UI_TOP_H, self.panel_width, self.stage_h)
        self.panels = PanelManager(panel_rect, min_width=C.PANEL_W,
                                   max_width=max_panel_w)
        self._update_layout()

        # playback
        self.player = Player(self.sm, self.assets)

        # modes
        self.mode = MODE_EDIT
        self.t = 0.0                    # recording clock (seconds)
        self.trans_kind = "curtain"
        self.trans_hold = C.TRANSITION_DURATION
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
        self._resize_anchor = (0.0, 0.0)  # pinned corner (world) at start
        self._resize_angle = 0.0          # sprite angle at resize start
        self._resize_w0 = 1               # sprite width at resize start
        self._resize_h0 = 1               # sprite height at resize start
        self._group_snap = None         # {sprite: (x, y, sx, sy)} group resize
        self._group_start_box = None    # group frame bounds at drag start
        self.rotating = None            # list of sprites being rotated
        self._rot_snap = None           # {sprite: (angle0, x0, y0)} rotate
        self._rot_center = (0.0, 0.0)   # rotate pivot (world)
        self._rot_start = 0.0           # mouse angle (rad) at gesture start
        self._pin_x = 0.0
        self._pin_side_x = None         # "left" or "right"
        self._pin_y = 0.0
        self._pin_side_y = None         # "top" or "bottom"
        self.panning = False            # middle-mouse drag panning the view
        self._pan_last = (0, 0)
        self.marquee_selecting = False
        self.marquee_start = (0, 0)
        self.marquee_end = (0, 0)
        self.marquee_base = []
        self.marquee_additive = False
        self.frame_surf = pygame.Surface((self.frame_w, self.frame_h))

        # zoom dropdown control (status bar)
        self.zoom_menu_open = False
        self._zoom_click_rect = None
        self._zoom_menu_box = None
        self._zoom_menu_rects = []
        self._zoom_last_click_time = 0.0

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
            ("settings", "Settings", 90, C.COL_BUTTON),
        ]
        for key, label, w, col in specs:
            rect = pygame.Rect(x, y, w, h)
            self.buttons[key] = ui.Button(rect, label, color=col)
            x += w + 6

    def _effective_stage_width(self):
        return C.WINDOW_W

    def _usable_stage_width(self):
        """Width available to the scene frame, excluding the right side
        panel when it is visible."""
        if self.panels.visible:
            return max(1, C.WINDOW_W - self.panel_width)
        return C.WINDOW_W

    def _point_in_panel(self, sx, sy):
        if not self.panels.visible:
            return False
        pos = (int(sx), int(sy))
        return (self.panels.area.collidepoint(pos) or
                self.panels._resize_rect().collidepoint(pos))

    def _update_layout(self):
        self.stage_h = C.stage_height(C.WINDOW_H)
        self._update_panel_bounds()
        self.stage_w = self._effective_stage_width()
        self.view.set_stage_size(self.stage_w, self.stage_h)
        self._clamp_view_to_stage()

    def _update_stage_width(self):
        self._update_layout()

    def _clamp_view_to_stage(self):
        fw = self.view.frame_w * self.view.scale
        fh = self.view.frame_h * self.view.scale
        if self.view.frame_x + fw > self.stage_w:
            self.view.frame_x = self.stage_w - fw
        if self.view.frame_y + fh > C.UI_TOP_H + self.stage_h:
            self.view.frame_y = C.UI_TOP_H + self.stage_h - fh

    def _set_panel_width(self, width):
        width = max(C.PANEL_W, min(self.panels.max_width, int(width)))
        self.panel_width = width
        self._update_layout()

    def _desktop_size(self):
        try:
            sizes = pygame.display.get_desktop_sizes()
            if sizes:
                return (int(sizes[0][0]), int(sizes[0][1]))
        except Exception:
            pass
        try:
            info = pygame.display.Info()
            w = int(info.current_w or C.WINDOW_W)
            h = int(info.current_h or C.WINDOW_H)
            return (max(C.MIN_WINDOW_W, w), max(C.MIN_WINDOW_H, h))
        except Exception:
            return (C.WINDOW_W, C.WINDOW_H)

    def _window_flags(self):
        if self.fullscreen:
            return pygame.FULLSCREEN
        return pygame.RESIZABLE

    def _maximize_window(self):
        """Maximize the OS window, keeping it in windowed (decorated)
        mode so the app fills the screen without true fullscreen."""
        try:
            from pygame._sdl2 import video as _sdl2_video
            win = _sdl2_video.Window.from_display_module()
            win.maximize()
            pygame.event.pump()
        except Exception:
            pass

    def toggle_fullscreen(self):
        """Switch between true fullscreen and maximized windowed mode."""
        self._apply_fullscreen(not self.fullscreen)
        self.status = ("Fullscreen" if self.fullscreen
                       else "Windowed mode")

    def _set_display_mode(self, size, flags):
        try:
            return pygame.display.set_mode(size, flags)
        except pygame.error:
            return pygame.display.set_mode(size, 0)

    def _update_panel_bounds(self):
        if not hasattr(self, "panels"):
            return
        self.panels.max_width = C.max_panel_width(C.WINDOW_W)
        self.panel_width = max(C.PANEL_W,
                               min(self.panels.max_width, self.panel_width))
        self.panels.set_width(self.panel_width)
        self.panels.set_bounds(right=C.WINDOW_W, height=self.stage_h)

    def _on_window_resize(self, w, h):
        if self.fullscreen:
            return
        w = max(C.MIN_WINDOW_W, int(w))
        h = max(C.MIN_WINDOW_H, int(h))
        if (w, h) == (self.window_w, self.window_h):
            return
        self.window_w, self.window_h = w, h
        self.windowed_size = (w, h)
        C.WINDOW_W, C.WINDOW_H = w, h
        self.screen = self._set_display_mode((w, h), self._window_flags())
        self._update_layout()

    def _apply_fullscreen(self, fullscreen):
        fullscreen = bool(fullscreen)
        if fullscreen == self.fullscreen:
            return

        if fullscreen:
            if not self.windowed_size:
                self.windowed_size = (self.window_w, self.window_h)
            w, h = self._desktop_size()
            self.fullscreen = True
            self.window_w, self.window_h = w, h
            C.WINDOW_W, C.WINDOW_H = w, h
            self.screen = self._set_display_mode((w, h), self._window_flags())
        else:
            # return to a maximized windowed mode (not true fullscreen)
            w, h = self._desktop_size()
            self.fullscreen = False
            self.window_w, self.window_h = w, h
            C.WINDOW_W, C.WINDOW_H = w, h
            self.screen = self._set_display_mode((w, h), self._window_flags())
            self._maximize_window()

        self._update_layout()

    def load_assets_from_disk(self):
        """Load every sprite, sound and background found in the asset
        folders so they appear in the panels at startup."""
        self.assets.load_images_from(C.SPRITES_DIR)
        self.assets.load_backgrounds_from(C.BACKGROUNDS_DIR)
        self.sm.load_all_from(C.SOUNDS_DIR)

    def refresh_panels(self):
        icon = C.PANEL_ICON_SIZE

        # sprites
        sp_items = []
        for key in sorted(self.assets.images.keys()):
            surf = self.assets.images[key]
            thumb = pygame.transform.smoothscale(surf, (icon, icon))
            sp_items.append({"key": key, "label": key, "thumb": thumb})
        self.panels.set_items("Sprites", sp_items)

        # sounds
        snd_items = [{"key": n, "label": n, "thumb": None}
                     for n in sorted(self.sm.sounds.keys())]
        self.panels.set_items("Sounds", snd_items)

        # backgrounds
        bg_items = []
        for key in sorted(self.assets.backgrounds.keys()):
            surf = self.assets.backgrounds[key]
            thumb = pygame.transform.smoothscale(surf, (icon, icon))
            bg_items.append({"key": key, "label": key, "thumb": thumb})
        self.panels.set_items("Backgrounds", bg_items)

        # scenes
        sc_items = [{"key": s.name, "label": s.name, "thumb": None}
                    for s in self.stage.scenes]
        sc_items.append({"key": "__add__", "label": "+ New scene",
                         "thumb": None})
        self.panels.set_items("Scenes", sc_items)

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
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_F11:
                    self.toggle_fullscreen()
                elif event.type == pygame.VIDEORESIZE:
                    self._on_window_resize(event.w, event.h)
                else:
                    self.handle_event(event, mouse_pos)
            self.update(dt)
            self.draw()
            pygame.display.flip()
        pygame.quit()

    def update(self, dt):
        if self.mode == MODE_RECORD:
            self.t += dt
        elif self.mode == MODE_PLAY:
            finished = self.player.update(dt)
            if finished:
                self.mode = MODE_EDIT
                self.player.stop()
                self.status = "Playback finished."

    # ---- zoom control -------------------------------------------------
    def set_zoom(self, factor):
        """Set an absolute zoom factor and keep the frame on screen."""
        self.view.set_scale(factor)
        self._clamp_view_to_stage()

    def toggle_zoom_menu(self):
        self.zoom_menu_open = not self.zoom_menu_open

    def handle_zoom_event(self, event, mouse_pos):
        """Handle clicks on the status-bar Zoom control and its dropdown.
        Returns True when the event was consumed."""
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return self.zoom_menu_open and event.type == pygame.MOUSEMOTION

        pos = event.pos
        # click on an item of the open dropdown
        if self.zoom_menu_open:
            for rect, factor in self._zoom_menu_rects:
                if rect.collidepoint(pos):
                    self.set_zoom(factor)
                    self.zoom_menu_open = False
                    self._zoom_last_click_time = 0.0
                    return True
            # click inside the dropdown box but not on an item: swallow it
            if self._zoom_menu_box is not None and \
                    self._zoom_menu_box.collidepoint(pos):
                return True

        # click on the Zoom control itself
        if self._zoom_click_rect is not None and \
                self._zoom_click_rect.collidepoint(pos):
            now = time.perf_counter()
            if now - self._zoom_last_click_time <= 0.35:
                # double click: reset to 100% and centre the camera,
                # accounting for the visible right side panel
                self.set_zoom(1.0)
                self.view.reset_view(self._usable_stage_width())
                self.zoom_menu_open = False
                self._zoom_last_click_time = 0.0
            else:
                self._zoom_last_click_time = now
                self.toggle_zoom_menu()
            return True

        # clicking anywhere else closes the menu
        self.zoom_menu_open = False
        return False

    # ---- input --------------------------------------------------------
    def handle_event(self, event, mouse_pos):
        # zoom dropdown has priority (it overlays the toolbar / stage)
        if self.handle_zoom_event(event, mouse_pos):
            return
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

    def _flip_buttons_rect(self, x1, y1, x2, y2):
        """Flip buttons placed under a world-space box."""
        sx, sy = self.view.w2s(x1, y1)
        ex, ey = self.view.w2s(x2, y2)
        mid_x = int((sx + ex) / 2)
        btn_h = pygame.Rect(mid_x - 62, int(ey + 8), 58, 22)
        btn_v = pygame.Rect(mid_x + 4, int(ey + 8), 58, 22)
        return btn_h, btn_v

    def _flip_buttons(self, sp):
        """Flip buttons under the midpoint of the sprite's CURRENT bottom
        edge (the rotated hitbox edge, not the angle-0 AABB)."""
        bx, by = sp.handle_points()["bottom"]
        sx, sy = self.view.w2s(bx, by)
        btn_h = pygame.Rect(0, 0, 58, 22)
        btn_v = pygame.Rect(0, 0, 58, 22)
        btn_h.center = (int(sx) - 31, int(sy) + 19)
        btn_v.center = (int(sx) + 31, int(sy) + 19)
        return btn_h, btn_v

    def _selection_sprites(self):
        """Selected sprites that still belong to the active scene."""
        sc = self.stage.active
        return [s for s in self.selected_sprites if s in sc.sprites]

    @staticmethod
    def _box_handle_points(x1, y1, x2, y2):
        """8 resize handles around an arbitrary world-space box."""
        w, h = x2 - x1, y2 - y1
        return {
            "top": (x1 + w / 2.0, y1),
            "bottom": (x1 + w / 2.0, y2),
            "left": (x1, y1 + h / 2.0),
            "right": (x2, y1 + h / 2.0),
            "top_left": (x1, y1),
            "top_right": (x2, y1),
            "bottom_left": (x1, y2),
            "bottom_right": (x2, y2),
        }

    @staticmethod
    def _near_corner(wx, wy, corners, tol, rot_tol):
        """True when (wx, wy) is outside the handle square (tol) but within
        rot_tol of a corner point — the grab zone of the rotate gesture."""
        for name in ("top_left", "top_right", "bottom_left",
                     "bottom_right"):
            hx, hy = corners[name]
            if abs(wx - hx) <= tol and abs(wy - hy) <= tol:
                continue    # that is the resize handle itself
            if math.hypot(wx - hx, wy - hy) <= rot_tol:
                return True
        return False

    def _group_bounds(self, sprites=None):
        """Union of the given sprites' rectangles (world space), or None."""
        if sprites is None:
            sprites = self._selection_sprites()
        if not sprites:
            return None
        x1 = min(s.x for s in sprites)
        y1 = min(s.y for s in sprites)
        x2 = max(s.x + s.w for s in sprites)
        y2 = max(s.y + s.h for s in sprites)
        return (x1, y1, x2, y2)

    def _group_box(self, sprites=None):
        """Padded group frame (world space) for a multi-selection.
        The pad keeps the group handles clear of the individual ones."""
        if sprites is None:
            sprites = self._selection_sprites()
        if len(sprites) < 2:
            return None
        x1, y1, x2, y2 = self._group_bounds(sprites)
        pad = GROUP_BOX_PAD / max(self.view.scale, 1e-6)
        return (x1 - pad, y1 - pad, x2 + pad, y2 + pad)

    def _flip_sprites(self, sprites, horizontal):
        """Toggle a flip axis on every given sprite and log each change."""
        targets = [sp for sp in sprites
                   if sp in self.stage.active.sprites]
        if not targets:
            return
        for sp in targets:
            if horizontal:
                sp.toggle_flip_h()
            else:
                sp.toggle_flip_v()
            if self._logging():
                self.recorder.log_flip(self._edit_t(), sp, sp.flip_x,
                                       sp.flip_y)
        self.status = (f"Flip {'H' if horizontal else 'V'}: "
                       f"{len(targets)} object(s).")

    def handle_stage(self, event, mouse_pos):
        if self.mode == MODE_PLAY:
            return
        sx, sy = getattr(event, "pos", mouse_pos)

        # middle mouse button: pan the view (allowed anywhere on the stage,
        # and continues even if the cursor drifts over the panel area)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 2:
            if not self._point_in_panel(sx, sy):
                self.panning = True
                self._pan_last = (sx, sy)
            return

        if (self._point_in_panel(sx, sy) and not self.panning
                and not self.marquee_selecting):
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
                    if self._logging():
                        self.recorder.log_z_order(self._edit_t(),
                                                  self.selected, "up")
                elif event.y < 0:
                    self.stage.active.move_sprite_down(self.selected)
                    if self._logging():
                        self.recorder.log_z_order(self._edit_t(),
                                                  self.selected, "down")
                return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            wx, wy = self.view.s2w(sx, sy)
            sc = self.stage.active
            if self.marquee_selecting:
                return
            sel = self._selection_sprites()
            group_box = self._group_box(sel)
            tol = HANDLE_TOL / self.view.scale
            rot_tol = ROTATE_TOL / max(self.view.scale, 1e-6)

            # 1. Group frame: flip buttons + resize handles (multi-select).
            #    Checked before everything else so group controls win over
            #    the individual ones drawn inside the frame.
            if group_box is not None and self._editable():
                btn_h, btn_v = self._flip_buttons_rect(*group_box)
                if btn_h.collidepoint(sx, sy):
                    self._flip_sprites(sel, horizontal=True)
                    return
                if btn_v.collidepoint(sx, sy):
                    self._flip_sprites(sel, horizontal=False)
                    return
                for name, (hx, hy) in self._box_handle_points(*group_box
                                                              ).items():
                    if abs(wx - hx) <= tol and abs(wy - hy) <= tol:
                        self._start_group_resize(group_box, sel, name)
                        return
                # rotation: near a corner of the group frame, outside its
                # handle -> the whole group turns around the group centre
                if self._near_corner(wx, wy,
                                     self._box_handle_points(*group_box),
                                     tol, rot_tol):
                    bx1, by1, bx2, by2 = self._group_bounds(sel)
                    self._start_rotation(sel,
                                         ((bx1 + bx2) / 2.0,
                                          (by1 + by2) / 2.0), wx, wy)
                    return

            # 2. Individual flip buttons and resize handles.
            #    With "show hitboxes" every sprite exposes them; otherwise
            #    only a single selected sprite does (for a group the frame
            #    above owns the controls).
            if not self._editable():
                candidates = []
            elif self.show_hitboxes:
                candidates = list(sc.sprites)
            elif len(sel) == 1:
                candidates = [sel[0]]
            else:
                candidates = []
            for sp in candidates:
                btn_h, btn_v = self._flip_buttons(sp)
                if btn_h.collidepoint(sx, sy):
                    self._flip_sprites([sp], horizontal=True)
                    return
                if btn_v.collidepoint(sx, sy):
                    self._flip_sprites([sp], horizontal=False)
                    return
            for sp in candidates:
                handle = sp.hit_handle(wx, wy, tol=tol)
                if handle is not None:
                    self._start_resize(sp, handle)
                    return
            # rotation zone just outside a sprite's corner handles
            for sp in candidates:
                if self._near_corner(wx, wy, sp.handle_points(),
                                     tol, rot_tol):
                    self._start_rotation([sp], sp.center, wx, wy)
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
                    if self._logging():
                        for s in self.selected_sprites:
                            self.recorder.log_move(self._edit_t(), s, s.x, s.y,
                                                   force=True)
            else:
                if self._editable():
                    self._start_marquee(sx, sy, additive=is_shift)
                elif not is_shift:
                    self.selected_sprites = []

        elif event.type == pygame.MOUSEMOTION:
            if self.panning:
                dx = sx - self._pan_last[0]
                dy = sy - self._pan_last[1]
                self.view.pan(dx, dy)
                self._pan_last = (sx, sy)
                return
            if self.marquee_selecting:
                self.marquee_end = (sx, sy)
                return
            wx, wy = self.view.s2w(sx, sy)
            if self.rotating and self._editable():
                self._rotate_to(wx, wy)
            elif self._group_snap is not None and self._editable():
                self._group_resize_to(wx, wy)
            elif self.resizing is not None and self._editable():
                self._resize_to(wx, wy)
            elif self.dragging_sprites and self._editable():
                for s in self.dragging_sprites:
                    ox, oy = self.drag_offsets[s]
                    s.x = wx - ox
                    s.y = wy - oy
                    if self._logging():
                        self.recorder.log_move(self._edit_t(), s, s.x, s.y)

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 2:
            self.panning = False

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.marquee_selecting:
                self._finish_marquee()
                return
            if self.dragging_sprites and self._logging():
                for s in self.dragging_sprites:
                    self.recorder.log_move(self._edit_t(), s, s.x, s.y,
                                           force=True)
            if self.rotating and self._logging():
                for s in self.rotating:
                    self.recorder.log_rotate(self._edit_t(), s, s.angle,
                                             force=True)
                    self.recorder.log_move(self._edit_t(), s, s.x, s.y,
                                           force=True)
            self.dragging_sprites = []
            self.resizing = None
            self.resize_handle = None
            self._group_snap = None
            self._group_start_box = None
            self.rotating = None
            self._rot_snap = None

        elif event.type == pygame.KEYDOWN and self._editable():
            mods = pygame.key.get_mods()
            ctrl = bool(mods & pygame.KMOD_CTRL)
            if event.key == pygame.K_DELETE:
                for sp in list(self.selected_sprites):
                    if self._logging():
                        self.recorder.log_sprite_remove(self._edit_t(), sp)
                    self.stage.active.remove_sprite(sp)
                self.selected_sprites = []
            elif ctrl and event.key == pygame.K_c:
                self.clipboard = [sp.to_dict() for sp in self.selected_sprites
                                  if sp in self.stage.active.sprites]
                self.status = f"Copied {len(self.clipboard)} sprite(s)."
            elif ctrl and event.key == pygame.K_v:
                self._paste_clipboard()

    def _make_unique_sprite_name(self, base_name):
        """A free name derived from base_name: the base itself when nothing
        in the stage uses it, otherwise base_copy, base_copy2, ..."""
        all_names = {sp.name for sc in self.stage.scenes for sp in sc.sprites}
        if base_name not in all_names:
            return base_name
        candidate = f"{base_name}_copy"
        i = 1
        while candidate in all_names:
            i += 1
            candidate = f"{base_name}_copy{i}"
        return candidate

    def _dedupe_sprite_names(self):
        """Make every sprite name in the stage unique (the event log keys
        everything by name, so duplicates would be recorded as one object).
        Heals scenes that already contain duplicates, e.g. loaded from an
        older project. Safe to run before recording: the log is still empty."""
        seen = set()
        for sc in self.stage.scenes:
            for sp in sc.sprites:
                if sp.name in seen:
                    sp.name = self._make_unique_sprite_name(sp.name)
                seen.add(sp.name)

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
                        flip_y=d.get("flip_y", False),
                        angle=d.get("angle", 0.0))
            self.stage.active.add_sprite(sp)
            if self._logging():
                self.recorder.log_sprite_add(self._edit_t(), sp)
                self.recorder.log_move(self._edit_t(), sp, sp.x, sp.y,
                                       force=True)
            new_sprites.append(sp)
        self.selected_sprites = new_sprites
        self.status = f"Pasted {len(new_sprites)} sprite(s)."

    def _editable(self):
        return self.mode in (MODE_EDIT, MODE_RECORD, MODE_PAUSED)

    def _in_recording_session(self):
        """True while a recording is in progress, including pauses."""
        return self.mode in (MODE_RECORD, MODE_PAUSING, MODE_PAUSED,
                             MODE_RESUMING)

    def _logging(self):
        """True when edits must be written to the event log (an active
        recording session, including pauses)."""
        return self.recorder.recording

    def _edit_t(self):
        """Timestamp for a logged edit. While paused, edits are logged at the
        point where the transition is fully closed, so the recorded curtain
        hides the change on playback."""
        if self.mode in (MODE_PAUSING, MODE_PAUSED, MODE_RESUMING):
            return self.pause_start_t + C.TRANSITION_DURATION / 2.0
        return self.t

    # ---- resizing -----------------------------------------------------
    def _start_resize(self, sp, handle):
        self.resizing = sp
        self.resize_handle = handle
        self._resize_angle = sp.angle
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

        # rotated resize: the visual anchor is rotate(pinned_local, centre,
        # angle); snapshot where it sits on screen so the drag can keep it
        # fixed while the opposite edges follow the mouse
        cx, cy = sp.center
        ax = self._pin_x if self._pin_side_x else cx
        ay = self._pin_y if self._pin_side_y else cy
        self._resize_anchor = rotate_point(ax, ay, cx, cy, sp.angle)
        self._resize_w0 = sp.w
        self._resize_h0 = sp.h

    def _resize_to(self, wx, wy):
        sp = self.resizing
        h = self.resize_handle
        if sp is None or h is None:
            return

        # Solve the resize directly from the gesture snapshot (no feedback
        # from the previous frame, so rotated resizing never drifts or
        # jitters). The vector from the pinned corner — fixed on screen at
        # A0 — to the mouse is projected onto the rotated drag axes to get
        # the new size; the sprite is then placed so the pinned corner stays
        # exactly at A0. At angle == 0 this is the classic
        # "drag an edge, pin the opposite side" math.
        angle = self._resize_angle
        a = math.radians(angle)
        # unit vectors of the local +x / +y axes on screen (CCW like pygame)
        ex = (math.cos(a), -math.sin(a))
        ey = (math.sin(a), math.cos(a))
        vx = wx - self._resize_anchor[0]
        vy = wy - self._resize_anchor[1]

        is_shift = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)

        # desired new size along the rotated axes
        proj_x = vx * ex[0] + vy * ex[1]
        proj_y = vx * ey[0] + vy * ey[1]
        if self._pin_side_x == "left":
            new_w = max(1, round(proj_x))
        elif self._pin_side_x == "right":
            new_w = max(1, round(-proj_x))
        else:
            new_w = self._resize_w0

        if self._pin_side_y == "top":
            new_h = max(1, round(proj_y))
        elif self._pin_side_y == "bottom":
            new_h = max(1, round(-proj_y))
        else:
            new_h = self._resize_h0

        # Proportional resize if Shift is held or corner handle with Shift
        if is_shift and (self._pin_side_x is not None) and (self._pin_side_y is not None):
            scale = max(new_w / sp.orig_w, new_h / sp.orig_h)
            new_w = max(1, int(round(scale * sp.orig_w)))
            new_h = max(1, int(round(scale * sp.orig_h)))

        # Apply scale
        scale_x = (new_w / sp.orig_w) if self._pin_side_x else sp.scale_x
        scale_y = (new_h / sp.orig_h) if self._pin_side_y else sp.scale_y
        sp.set_scale(scale_x, scale_y)

        # Place the sprite so the pinned point P (fraction 0 / 0.5 / 1 of
        # the rectangle) lands on A0. The centre offset C - P is
        # (+-w/2, +-h/2) in local space, so  P = A0 + R(d) - d.
        dx = (sp.w / 2.0 if self._pin_side_x == "left" else
              -sp.w / 2.0 if self._pin_side_x == "right" else 0.0)
        dy = (sp.h / 2.0 if self._pin_side_y == "top" else
              -sp.h / 2.0 if self._pin_side_y == "bottom" else 0.0)
        rx, ry = rotate_point(dx, dy, 0.0, 0.0, angle)
        px = self._resize_anchor[0] + rx - dx
        py = self._resize_anchor[1] + ry - dy
        sp.x = (px if self._pin_side_x == "left" else
                px - sp.w if self._pin_side_x == "right"
                else px - sp.w / 2.0)
        sp.y = (py if self._pin_side_y == "top" else
                py - sp.h if self._pin_side_y == "bottom"
                else py - sp.h / 2.0)

        if self._logging():
            self.recorder.log_move(self._edit_t(), sp, sp.x, sp.y, force=True)
            self.recorder.log_scale(self._edit_t(), sp, sp.scale_x,
                                    sp.scale_y,
                                    anchor_x=self._pin_x if self._pin_side_x else None,
                                    anchor_side_x=self._pin_side_x,
                                    anchor_y=self._pin_y if self._pin_side_y else None,
                                    anchor_side_y=self._pin_side_y)

    # ---- rotation ------------------------------------------------------
    def _start_rotation(self, sprites, center, wx, wy):
        """Begin a rotate gesture. A single sprite turns around its own
        centre; a group turns around the group centre and its members
        orbit around it."""
        self.rotating = list(sprites)
        self._rot_snap = {sp: (sp.angle, sp.x, sp.y) for sp in sprites}
        self._rot_center = (float(center[0]), float(center[1]))
        cx, cy = self._rot_center
        self._rot_start = math.atan2(wy - cy, wx - cx)
        self.dragging_sprites = []
        if self._logging():
            for sp in sprites:
                self.recorder.log_rotate(self._edit_t(), sp, sp.angle,
                                         force=True)

    def _rotate_to(self, wx, wy):
        snaps = self._rot_snap
        if not snaps:
            return
        cx, cy = self._rot_center
        # atan2 in screen space grows clockwise; negate so dragging the
        # mouse counter-clockwise turns the sprite counter-clockwise
        delta = math.degrees(self._rot_start -
                             math.atan2(wy - cy, wx - cx))
        orbit = len(self.rotating) > 1
        for sp, (a0, x0, y0) in snaps.items():
            sp.set_angle(a0 + delta)
            if orbit:
                # the sprite centre orbits the group centre
                c0x, c0y = x0 + sp.w / 2.0, y0 + sp.h / 2.0
                nx, ny = rotate_point(c0x, c0y, cx, cy, delta)
                sp.x = nx - sp.w / 2.0
                sp.y = ny - sp.h / 2.0
            if self._logging():
                self.recorder.log_rotate(self._edit_t(), sp, sp.angle)
                if orbit:
                    self.recorder.log_move(self._edit_t(), sp, sp.x, sp.y,
                                           force=True)

    # ---- group resize (multi-selection) --------------------------------
    def _start_group_resize(self, box, sprites, handle):
        """Begin scaling a group from one of its frame handles.
        The opposite edges of the frame stay pinned, mirroring the
        behaviour of a single-sprite resize."""
        bx1, by1, bx2, by2 = box
        self._group_start_box = box
        # snapshot: sprite -> (x, y, scale_x, scale_y)
        self._group_snap = {sp: (sp.x, sp.y, sp.scale_x, sp.scale_y)
                            for sp in sprites}
        self.resizing = None
        self.resize_handle = handle
        self._pin_x = 0.0
        self._pin_side_x = None
        self._pin_y = 0.0
        self._pin_side_y = None

        if "right" in handle:
            self._pin_x = float(bx1)
            self._pin_side_x = "left"
        elif "left" in handle:
            self._pin_x = float(bx2)
            self._pin_side_x = "right"

        if "bottom" in handle:
            self._pin_y = float(by1)
            self._pin_side_y = "top"
        elif "top" in handle:
            self._pin_y = float(by2)
            self._pin_side_y = "bottom"

    def _group_resize_to(self, wx, wy):
        box = self._group_start_box
        snaps = self._group_snap
        if box is None or not snaps:
            return
        bx1, by1, bx2, by2 = box
        start_w = max(1.0, bx2 - bx1)
        start_h = max(1.0, by2 - by1)

        is_shift = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)

        # desired new frame size
        if self._pin_side_x == "left":
            new_w = max(1.0, float(wx) - self._pin_x)
        elif self._pin_side_x == "right":
            new_w = max(1.0, self._pin_x - float(wx))
        else:
            new_w = start_w
        if self._pin_side_y == "top":
            new_h = max(1.0, float(wy) - self._pin_y)
        elif self._pin_side_y == "bottom":
            new_h = max(1.0, self._pin_y - float(wy))
        else:
            new_h = start_h

        # proportional scaling with Shift on a corner handle
        if is_shift and self._pin_side_x and self._pin_side_y:
            factor = max(new_w / start_w, new_h / start_h)
            new_w = start_w * factor
            new_h = start_h * factor

        factor_x = new_w / start_w if self._pin_side_x else 1.0
        factor_y = new_h / start_h if self._pin_side_y else 1.0

        # new top-left of the frame (the pinned edge does not move)
        if self._pin_side_x == "left":
            new_x1 = self._pin_x
        elif self._pin_side_x == "right":
            new_x1 = self._pin_x - new_w
        else:
            new_x1 = bx1
        if self._pin_side_y == "top":
            new_y1 = self._pin_y
        elif self._pin_side_y == "bottom":
            new_y1 = self._pin_y - new_h
        else:
            new_y1 = by1

        # every sprite is mapped linearly inside the frame
        for sp, (ox, oy, osx, osy) in snaps.items():
            sp.set_scale(osx * factor_x, osy * factor_y)
            sp.x = new_x1 + (ox - bx1) * factor_x
            sp.y = new_y1 + (oy - by1) * factor_y
            if self._logging():
                self.recorder.log_move(self._edit_t(), sp, sp.x, sp.y,
                                       force=True)
                self.recorder.log_scale(self._edit_t(), sp, sp.scale_x,
                                        sp.scale_y)

    # ---- marquee selection --------------------------------------------
    def _start_marquee(self, sx, sy, additive=False):
        self.marquee_selecting = True
        self.marquee_start = (sx, sy)
        self.marquee_end = (sx, sy)
        self.marquee_additive = bool(additive)
        self.marquee_base = list(self.selected_sprites)

    def _finish_marquee(self):
        self.marquee_selecting = False
        sc = self.stage.active
        base = [sp for sp in self.marquee_base if sp in sc.sprites]

        x1, y1 = self.marquee_start
        x2, y2 = self.marquee_end
        if abs(x2 - x1) < 4 and abs(y2 - y1) < 4:
            self.selected_sprites = base if self.marquee_additive else []
            return

        wx1, wy1 = self.view.s2w(x1, y1)
        wx2, wy2 = self.view.s2w(x2, y2)
        rect = pygame.Rect(
            int(min(wx1, wx2)),
            int(min(wy1, wy2)),
            max(1, int(abs(wx2 - wx1))),
            max(1, int(abs(wy2 - wy1))),
        )

        hits = [sp for sp in sc.sprites if sp.rect().colliderect(rect)]
        if self.marquee_additive:
            new_selection = list(base)
            for sp in hits:
                if sp not in new_selection:
                    new_selection.append(sp)
            self.selected_sprites = new_selection
        else:
            self.selected_sprites = hits

    # ---- buttons ------------------------------------------------------
    def on_button(self, key):
        if key == "record":
            if self.mode == MODE_EDIT:
                self.start_recording()
            elif self._in_recording_session():
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
            self._update_layout()
        elif key == "settings":
            self.settings_dialog()

    def start_recording(self):
        self.t = 0.0
        self.scene_changed_in_pause = False
        self.stage.active_index = 0
        # ensure unique sprite names before snapshotting, otherwise duplicate
        # instances of one asset would be merged into a single object
        # during playback (the event log identifies sprites by name)
        self._dedupe_sprite_names()
        self.recorder.start(self._stage_snapshot())
        self.mic.start()
        self.mode = MODE_RECORD
        self.status = "Recording..."

    def stop_recording(self):
        # capture final positions for all sprites. If stopped while paused,
        # extend the timeline past the whole pause transition so the hidden
        # midpoint edits stay inside the recording.
        end_t = self.t
        if self.mode in (MODE_PAUSING, MODE_PAUSED, MODE_RESUMING):
            end_t = (self.pause_start_t + C.TRANSITION_DURATION +
                     self.trans_hold)
        for sc in self.stage.scenes:
            for sp in sc.sprites:
                self.recorder.log_move(end_t, sp, sp.x, sp.y, force=True)
        self.recorder.stop(end_t)
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
        # Pausing/resuming during recording is instantaneous (no freeze).
        # The recorded pause event carries the configured "hold" time, which
        # only affects the transition animation on playback/export.
        if self.mode == MODE_RECORD:
            self._enter_pause()
        elif self.mode == MODE_PAUSED:
            self._resume_from_pause()

    def _enter_pause(self):
        self.pause_start_t = self.t
        self.pause_wall_start = time.perf_counter()
        self.mic.set_capturing(False)
        self.trans_kind = self._default_transition()
        self.trans_hold = self._pause_duration()
        self.scene_changed_in_pause = False
        # anchor positions before pause so idle stretch is not drift
        for sc in self.stage.scenes:
            for sp in sc.sprites:
                self.recorder.log_move(self.t, sp, sp.x, sp.y,
                                       force=True)
        self.recorder.log_pause(self.t, self.trans_kind, self.trans_hold,
                                self.stage.active.name)
        self._pending_pause_event = self.recorder.log.events[-1]
        self.mode = MODE_PAUSED
        self.status = ("Paused. Rearrange objects / switch scene, "
                       "then press Pause to resume.")

    def _resume_from_pause(self):
        # The pause occupies a fixed span on the timeline:
        #   close (anim) + hold (configurable) + open (anim).
        span = C.TRANSITION_DURATION + self.trans_hold
        # advance the recording clock instantly past the transition
        self.t = self.pause_start_t + span
        # keep the microphone track aligned with the recording clock:
        # the pause captured nothing, so insert the transition of silence
        # before resuming capture.
        self.mic.insert_silence(span)
        self.mic.set_capturing(True)
        # teleport all sprites to their (possibly edited) paused positions,
        # logged where the curtain is fully closed so the cover hides the jump
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

    # ---- settings -----------------------------------------------------
    def _default_transition(self):
        kind = self.settings.get("default_pause_transition", "curtain")
        if kind not in C.TRANSITION_KINDS:
            kind = "curtain"
        return kind

    def _pause_duration(self):
        """Configured length (seconds) of a playback pause transition."""
        try:
            value = float(self.settings.get("pause_duration",
                                            C.TRANSITION_DURATION))
        except (TypeError, ValueError):
            value = C.TRANSITION_DURATION
        return max(C.PAUSE_DURATION_MIN,
                   min(C.PAUSE_DURATION_MAX, value))

    @staticmethod
    def _format_duration(value):
        """Render a seconds value for the pause-duration input field."""
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = C.TRANSITION_DURATION
        if value == int(value):
            return str(int(value))
        return f"{value:.3f}".rstrip("0").rstrip(".")

    def _media_initial_dir(self, fallback):
        path = self.settings.get("media_initial_dir") or fallback
        if os.path.isdir(path):
            return path
        return fallback

    def settings_dialog(self):
        box_w, box_h = 560, 360
        box = pygame.Rect((C.WINDOW_W - box_w) // 2,
                          (C.WINDOW_H - box_h) // 2, box_w, box_h)

        path_text = self.settings.get("media_initial_dir", C.ASSETS_DIR)
        transition = self._default_transition()
        pause_text = self._format_duration(self._pause_duration())
        fullscreen = bool(self.settings.get("fullscreen", False))
        pending_fullscreen = None
        input_focused = False
        pause_focused = False
        cursor_pos = len(path_text)
        pause_cursor = len(pause_text)
        cursor_timer = 0
        error_msg = ""

        path_rect = pygame.Rect(box.x + 24, box.y + 70, box_w - 140, 32)
        browse_btn = ui.Button((path_rect.right + 8, path_rect.y, 100, 32),
                               "Browse")
        transition_btns = []
        btn_w = (box_w - 48 - 16) // 3
        for i, kind in enumerate(C.TRANSITION_KINDS):
            label = kind.capitalize()
            btn = ui.Button((box.x + 24 + i * (btn_w + 8), box.y + 150,
                             btn_w, 36), label, toggle=True)
            btn.active = (kind == transition)
            transition_btns.append((btn, kind))

        pause_rect = pygame.Rect(box.x + 24, box.y + 226, 120, 32)

        fullscreen_btn = ui.Button((box.x + 24, box.y + 276, 180, 32),
                                   "На весь экран", toggle=True)
        fullscreen_btn.active = fullscreen

        hitboxes = self.show_hitboxes
        hitboxes_btn = ui.Button((box.x + 212, box.y + 276, 324, 32),
                                 "Хитбоксы всех объектов", toggle=True)
        hitboxes_btn.active = hitboxes

        save_btn = ui.Button((box.right - 184, box.bottom - 44, 80, 32), "Save")
        cancel_btn = ui.Button((box.right - 96, box.bottom - 44, 80, 32),
                               "Cancel")

        dialog_running = True
        while dialog_running:
            self.clock.tick(60)
            mouse = pygame.mouse.get_pos()
            cursor_timer = (cursor_timer + 1) % 60

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    dialog_running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    dialog_running = False
                elif save_btn.handle_event(event, mouse):
                    input_focused = False
                    clean_path = path_text.strip()
                    if not clean_path or not os.path.isdir(clean_path):
                        error_msg = "Folder does not exist"
                        continue
                    window_width, window_height = self.windowed_size or (
                        self.window_w, self.window_h)
                    try:
                        pause_value = float(pause_text)
                    except (TypeError, ValueError):
                        pause_value = self._pause_duration()
                    pause_value = max(C.PAUSE_DURATION_MIN,
                                      min(C.PAUSE_DURATION_MAX, pause_value))
                    saved = S.save_settings({
                        "media_initial_dir": os.path.abspath(clean_path),
                        "default_pause_transition": transition,
                        "pause_duration": round(pause_value, 3),
                        "panel_width": self.panel_width,
                        "fullscreen": fullscreen,
                        "show_hitboxes": hitboxes,
                        "window_width": window_width,
                        "window_height": window_height,
                    })
                    self.settings = saved
                    path_text = saved["media_initial_dir"]
                    cursor_pos = len(path_text)
                    self.show_hitboxes = saved["show_hitboxes"]
                    self.status = "Settings saved."
                    if fullscreen != self.fullscreen:
                        pending_fullscreen = fullscreen
                    dialog_running = False
                elif cancel_btn.handle_event(event, mouse):
                    input_focused = False
                    dialog_running = False
                elif browse_btn.handle_event(event, mouse):
                    input_focused = False
                    chosen = ui.choose_directory(
                        self.screen, self.clock,
                        "Choose initial media folder",
                        initialdir=path_text if os.path.isdir(path_text) else C.ASSETS_DIR)
                    if chosen:
                        path_text = chosen
                        cursor_pos = len(path_text)
                        error_msg = ""
                elif fullscreen_btn.handle_event(event, mouse):
                    input_focused = False
                    fullscreen = not fullscreen
                    fullscreen_btn.active = fullscreen
                elif hitboxes_btn.handle_event(event, mouse):
                    input_focused = False
                    hitboxes = not hitboxes
                    hitboxes_btn.active = hitboxes
                else:
                    for btn, kind in transition_btns:
                        if btn.handle_event(event, mouse):
                            input_focused = False
                            pause_focused = False
                            transition = kind
                            for b, k in transition_btns:
                                b.active = (k == transition)
                            break
                    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                        input_focused = path_rect.collidepoint(event.pos)
                        pause_focused = pause_rect.collidepoint(event.pos)
                        if input_focused:
                            cursor_pos = len(path_text)
                        if pause_focused:
                            pause_cursor = len(pause_text)
                    elif event.type == pygame.KEYDOWN and input_focused:
                        if event.key == pygame.K_BACKSPACE:
                            if cursor_pos > 0:
                                path_text = (path_text[:cursor_pos - 1] +
                                             path_text[cursor_pos:])
                                cursor_pos -= 1
                        elif event.key == pygame.K_DELETE:
                            if cursor_pos < len(path_text):
                                path_text = (path_text[:cursor_pos] +
                                             path_text[cursor_pos + 1:])
                        elif event.key == pygame.K_LEFT:
                            cursor_pos = max(0, cursor_pos - 1)
                        elif event.key == pygame.K_RIGHT:
                            cursor_pos = min(len(path_text), cursor_pos)
                        elif event.key == pygame.K_HOME:
                            cursor_pos = 0
                        elif event.key == pygame.K_END:
                            cursor_pos = len(path_text)
                        elif event.unicode and event.unicode.isprintable():
                            path_text = (path_text[:cursor_pos] +
                                         event.unicode +
                                         path_text[cursor_pos:])
                            cursor_pos += len(event.unicode)
                    elif event.type == pygame.KEYDOWN and pause_focused:
                        if event.key == pygame.K_BACKSPACE:
                            if pause_cursor > 0:
                                pause_text = (pause_text[:pause_cursor - 1] +
                                              pause_text[pause_cursor:])
                                pause_cursor -= 1
                        elif event.key == pygame.K_DELETE:
                            if pause_cursor < len(pause_text):
                                pause_text = (pause_text[:pause_cursor] +
                                              pause_text[pause_cursor + 1:])
                        elif event.key == pygame.K_LEFT:
                            pause_cursor = max(0, pause_cursor - 1)
                        elif event.key == pygame.K_RIGHT:
                            pause_cursor = min(len(pause_text), pause_cursor)
                        elif event.key == pygame.K_HOME:
                            pause_cursor = 0
                        elif event.key == pygame.K_END:
                            pause_cursor = len(pause_text)
                        elif (event.unicode and event.unicode.isprintable()
                              and (event.unicode.isdigit()
                                   or event.unicode == ".")):
                            if event.unicode == "." and "." in pause_text:
                                continue
                            pause_text = (pause_text[:pause_cursor] +
                                          event.unicode +
                                          pause_text[pause_cursor:])
                            pause_cursor += len(event.unicode)

            dim = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
            dim.fill((0, 0, 0, 150))
            self.screen.blit(dim, (0, 0))

            pygame.draw.rect(self.screen, C.COL_PANEL, box, border_radius=8)
            pygame.draw.rect(self.screen, C.COL_ACCENT, box, 2,
                             border_radius=8)
            ui.draw_label(self.screen, "Settings", (box.x + 24, box.y + 16),
                          size=18, bold=True)
            ui.draw_label(self.screen, "Initial media folder",
                          (box.x + 24, box.y + 48), size=15)

            pygame.draw.rect(self.screen, (28, 28, 36), path_rect,
                             border_radius=5)
            border_col = C.COL_ACCENT if input_focused else C.COL_BUTTON
            pygame.draw.rect(self.screen, border_col, path_rect,
                             2 if input_focused else 1, border_radius=5)
            font = ui.get_font(14)
            clip = self.screen.get_clip()
            self.screen.set_clip(path_rect)
            text_surf = font.render(path_text, True, C.COL_TEXT)
            self.screen.blit(text_surf, (path_rect.x + 8, path_rect.y + 7))
            if input_focused and cursor_timer < 30:
                cursor_x = path_rect.x + 8 + font.size(path_text[:cursor_pos])[0]
                pygame.draw.line(self.screen, C.COL_ACCENT,
                                 (cursor_x, path_rect.y + 6),
                                 (cursor_x, path_rect.bottom - 7), 2)
            self.screen.set_clip(clip)

            browse_btn.draw(self.screen)

            ui.draw_label(self.screen, "Default pause transition",
                          (box.x + 24, box.y + 128), size=15)
            for btn, _ in transition_btns:
                btn.draw(self.screen)

            ui.draw_label(self.screen, "Pause hold - curtain closed (s)",
                          (box.x + 24, box.y + 204), size=15)
            pygame.draw.rect(self.screen, (28, 28, 36), pause_rect,
                             border_radius=5)
            pause_border = C.COL_ACCENT if pause_focused else C.COL_BUTTON
            pygame.draw.rect(self.screen, pause_border, pause_rect,
                             2 if pause_focused else 1, border_radius=5)
            pause_surf = font.render(pause_text, True, C.COL_TEXT)
            self.screen.blit(pause_surf,
                             (pause_rect.x + 8, pause_rect.y + 7))
            if pause_focused and cursor_timer < 30:
                pcursor_x = (pause_rect.x + 8 +
                             font.size(pause_text[:pause_cursor])[0])
                pygame.draw.line(self.screen, C.COL_ACCENT,
                                 (pcursor_x, pause_rect.y + 6),
                                 (pcursor_x, pause_rect.bottom - 7), 2)
            ui.draw_label(self.screen, "sec.",
                          (pause_rect.right + 10, pause_rect.y + 9), size=14,
                          color=C.COL_TEXT_DIM)

            fullscreen_btn.draw(self.screen)
            hitboxes_btn.draw(self.screen)

            if error_msg:
                ui.draw_label(self.screen, error_msg,
                              (box.x + 24, box.bottom - 64), size=14,
                              color=(230, 120, 120))

            save_btn.draw(self.screen)
            cancel_btn.draw(self.screen)
            pygame.display.flip()

        if pending_fullscreen is not None:
            self._apply_fullscreen(pending_fullscreen)

    # ---- asset additions ---------------------------------------------
    def add_sprite_dialog(self):
        paths = ui.open_files(self.screen, self.clock, "Add sprite images",
                              exts=C.IMAGE_EXTS,
                              initialdir=self._media_initial_dir(C.SPRITES_DIR))
        count = 0
        for p in paths:
            # copy the file into the asset folder, then load the copy
            dest = C.import_into(p, C.SPRITES_DIR)
            key = self.assets.load_image_file(dest)
            if key and self._logging():
                # unique name so duplicate instances of the same asset stay
                # distinguishable in the event log (image_key = asset key)
                sp = Sprite(self._make_unique_sprite_name(key),
                            self.assets.get_image(key),
                            C.MARGIN + 200, C.MARGIN + 200,
                            image_key=key)
                self.stage.active.add_sprite(sp)
                self.recorder.log_sprite_add(self._edit_t(), sp)
            if key:
                count += 1
        self.refresh_panels()
        self.status = f"Added {count} sprite(s)."

    def add_sound_dialog(self):
        paths = ui.open_files(self.screen, self.clock, "Add sounds",
                              exts=C.SOUND_EXTS,
                              initialdir=self._media_initial_dir(C.SOUNDS_DIR))
        count = 0
        for p in paths:
            dest = C.import_into(p, C.SOUNDS_DIR)
            if self.sm.load(dest):
                count += 1
        self.refresh_panels()
        self.status = f"Added {count} sound(s)."

    def add_bg_dialog(self):
        p = ui.open_file(self.screen, self.clock, "Add background",
                         exts=C.IMAGE_EXTS,
                         initialdir=self._media_initial_dir(C.BACKGROUNDS_DIR))
        if not p:
            return
        dest = C.import_into(p, C.BACKGROUNDS_DIR)
        key = self.assets.load_background_file(dest)
        if key:
            self.refresh_panels()
            self.status = f"Added background '{key}'."

    # ---- panel actions ------------------------------------------------
    def on_panel_action(self, action):
        kind = action[0]
        if kind == "drop":
            _, _, item, pos, _thumb = action
            self.drop_sprite(item, pos)
        elif kind == "item":
            _, panel, item = action
            self.on_item_click(panel, item)
        elif kind == "panel_resize":
            self._set_panel_width(action[1])
        elif kind == "panel_resize_end":
            self._set_panel_width(action[1])
            window_width, window_height = self.windowed_size or (
                self.window_w, self.window_h)
            self.settings["panel_width"] = self.panel_width
            self.settings["window_width"] = window_width
            self.settings["window_height"] = window_height
            self.settings = S.save_settings(self.settings)

    def drop_sprite(self, item, pos):
        if not self._editable():
            return
        sx, sy = pos
        if self._point_in_panel(sx, sy):
            return
        key = item["key"]
        surf = self.assets.get_image(key)
        wx, wy = self.view.s2w(sx, sy)
        # every dropped instance gets its own name so the event log can tell
        # them apart; the picture still comes from image_key (= asset key)
        sp = Sprite(self._make_unique_sprite_name(key), surf,
                    wx - surf.get_width() / 2,
                    wy - surf.get_height() / 2, image_key=key)
        self.stage.active.add_sprite(sp)
        self.selected = sp
        if self._logging():
            self.recorder.log_sprite_add(self._edit_t(), sp)
            self.recorder.log_move(self._edit_t(), sp, sp.x, sp.y,
                                   force=True)

    def on_item_click(self, panel, item):
        key = item["key"]
        if panel == "Sounds":
            self.sm.play(key)
            if self._logging():
                self.recorder.log_sound(self._edit_t(), key)
            self.status = f"Sound: {key}"
        elif panel == "Backgrounds":
            self.stage.active.bg_key = key
            self.stage.active.background = self.assets.get_background(key)
            if self._logging():
                self.recorder.log_background(self._edit_t(), key)
            self.status = f"Background: {key}"
        elif panel == "Scenes":
            if key == "__add__":
                sc = self.stage.add_scene()
                # if recording, register the new scene in the start snapshot
                # so it exists during playback/export
                snap = self.recorder.log.start_state
                if self._logging() and snap is not None:
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

    def _blit_world_centered(self, surf, cx, cy):
        """Blit a world-space surface centred on world point (cx, cy),
        applying view zoom. Used for rotated sprites: `rot_image` turns
        around the centre of the unrotated rectangle."""
        scale = self.view.scale
        if scale != 1.0:
            w = max(1, int(round(surf.get_width() * scale)))
            h = max(1, int(round(surf.get_height() * scale)))
            surf = pygame.transform.smoothscale(surf, (w, h))
        scx, scy = self.view.w2s(cx, cy)
        self.screen.blit(surf, surf.get_rect(center=(scx, scy)))


    def _draw_stage(self):
        stage_rect = pygame.Rect(0, C.UI_TOP_H, self.stage_w, self.stage_h)
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

            # sprites: world-space, rotated around their centre
            for sp in sc.sprites:
                self._blit_world_centered(sp.rot_image, *sp.center)

            # transition overlay over the frame
            cover = self._current_cover()
            if cover > 0.0:
                overlay = pygame.Surface((C.FRAME_W, C.FRAME_H))
                overlay.fill((0, 0, 0))
                transitions.draw(cover, self.trans_kind, overlay)
                if self.view.scale != 1.0:
                    overlay = pygame.transform.smoothscale(overlay, (fw, fh))
                self.screen.blit(overlay, (fx, fy))

            # ---- selection / hitbox frames, handles, flip buttons ----
            sel = [s for s in self.selected_sprites if s in sc.sprites]
            group_box = self._group_box(sel)

            if self.show_hitboxes:
                # every object shows its frame, handles and flip buttons;
                # selected ones turn red
                for sp in sc.sprites:
                    col = COL_SELECTED if sp in sel else COL_HITBOX
                    self._draw_sprite_frame(sp, col,
                                            handles=True, flip=True)
            else:
                for sp in sel:
                    self._draw_sprite_frame(sp, C.COL_ACCENT,
                                            handles=False, flip=False)
                # for a lone selection the sprite's own frame hosts the
                # handles; a group uses its padded frame instead
                if len(sel) == 1:
                    self._draw_sprite_frame(sel[0], C.COL_ACCENT,
                                            handles=True, flip=True)

            # common group frame (2+ selected objects)
            if group_box is not None:
                col = COL_SELECTED if self.show_hitboxes else C.COL_ACCENT
                self._draw_box_frame(group_box, col,
                                     handles=True, flip=True,
                                     flip_h=sel[-1].flip_x,
                                     flip_v=sel[-1].flip_y)

            if self.marquee_selecting:
                x1, y1 = self.marquee_start
                x2, y2 = self.marquee_end
                r = pygame.Rect(min(x1, x2), min(y1, y2),
                                abs(x2 - x1), abs(y2 - y1))
                if r.w > 0 and r.h > 0:
                    fill = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
                    fill.fill((C.COL_ACCENT[0], C.COL_ACCENT[1],
                               C.COL_ACCENT[2], 35))
                    self.screen.blit(fill, r.topleft)
                    pygame.draw.rect(self.screen, C.COL_ACCENT, r, 1)

        # frame border
        pygame.draw.rect(self.screen, C.COL_FRAME,
                        (fx, fy, fw, fh), 2)

    def _draw_handles(self, box, color):
        """8 white-outlined handles around a world-space box."""
        x1, y1, x2, y2 = box
        for hx, hy in self._box_handle_points(x1, y1, x2, y2).values():
            hxs, hys = self.view.w2s(hx, hy)
            r = pygame.Rect(0, 0, 10, 10)
            r.center = (int(hxs), int(hys))
            pygame.draw.rect(self.screen, color, r)
            pygame.draw.rect(self.screen, (255, 255, 255), r, 1)

    def _draw_flip_buttons(self, btn_h, btn_v, color, flip_h, flip_v):
        """Flip H / Flip V buttons at the given screen rectangles."""
        pygame.draw.rect(self.screen, C.COL_BUTTON, btn_h, border_radius=4)
        pygame.draw.rect(self.screen, color if flip_h else (100, 104, 120),
                         btn_h, 1, border_radius=4)
        ui.draw_label(self.screen, "Flip H", (btn_h.x + 8, btn_h.y + 3),
                      size=13, color=color if flip_h else C.COL_TEXT)

        pygame.draw.rect(self.screen, C.COL_BUTTON, btn_v, border_radius=4)
        pygame.draw.rect(self.screen, color if flip_v else (100, 104, 120),
                         btn_v, 1, border_radius=4)
        ui.draw_label(self.screen, "Flip V", (btn_v.x + 8, btn_v.y + 3),
                      size=13, color=color if flip_v else C.COL_TEXT)

    def _draw_sprite_frame(self, sp, color, handles=False, flip=False):
        """Frame (plus optional handles / flip buttons) for one sprite.

        The outline and the handles follow the sprite's rotation; the flip
        buttons stay under the axis-aligned box."""
        pts = sp.handle_points()
        corners = [pts["top_left"], pts["top_right"],
                   pts["bottom_right"], pts["bottom_left"]]
        poly = [self.view.w2s(px, py) for px, py in corners]
        pygame.draw.polygon(self.screen, color, poly, 2)
        if handles:
            for hx, hy in pts.values():
                hxs, hys = self.view.w2s(hx, hy)
                r = pygame.Rect(0, 0, 10, 10)
                r.center = (int(hxs), int(hys))
                pygame.draw.rect(self.screen, color, r)
                pygame.draw.rect(self.screen, (255, 255, 255), r, 1)
        if flip:
            self._draw_flip_buttons(*self._flip_buttons(sp), color,
                                    sp.flip_x, sp.flip_y)

    def _draw_box_frame(self, box, color, handles=False, flip=False,
                        flip_h=False, flip_v=False):
        """Frame around a world-space box: outline, handles, flip buttons."""
        x1, y1, x2, y2 = box
        sx, sy = self.view.w2s(x1, y1)
        ex, ey = self.view.w2s(x2, y2)
        pygame.draw.rect(self.screen, color,
                         (int(sx), int(sy), int(ex - sx), int(ey - sy)), 2)
        if handles:
            self._draw_handles(box, color)
        if flip:
            self._draw_flip_buttons(*self._flip_buttons_rect(*box),
                                    color, flip_h, flip_v)

    def _current_cover(self):
        # No transition overlay while authoring (recording/pausing/resuming):
        # the transition animation is shown ONLY during playback, where the
        # Player renders it from the recorded pause event. So nothing is
        # drawn over the stage while building the scene.
        return 0.0

    def _draw_toolbar(self):
        bar = pygame.Rect(0, 0, C.WINDOW_W, C.UI_TOP_H)
        pygame.draw.rect(self.screen, C.COL_PANEL_HDR, bar)
        # set active states / labels / enablement
        recording = self.mode == MODE_RECORD
        playing = self.mode == MODE_PLAY
        paused_session = self.mode in (MODE_PAUSING, MODE_PAUSED,
                                       MODE_RESUMING)
        in_session = self._in_recording_session()
        self.buttons["record"].active = in_session
        self.buttons["record"].toggle = True
        self.buttons["record"].label = ("Stop Recording"
                                        if in_session else "Record")
        self.buttons["pause"].label = ("Resume"
                                       if self.mode == MODE_PAUSED else "Pause")
        self.buttons["play"].label = "Stop playing" if playing else "Play"
        # enablement: during playback only the play/stop toggle is available;
        # while paused (in a recording session) only Stop Recording and
        # Resume are available; during recording Play/Export/Save/Load are
        # blocked
        for key, btn in self.buttons.items():
            if playing:
                btn.enabled = (key == "play")
            elif paused_session:
                btn.enabled = key in ("record", "pause")
            elif recording:
                btn.enabled = key not in ("play", "export", "save", "load",
                                          "settings")
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
        if self.mode == MODE_PLAY and self.player.runtime is not None:
            cur = self.player.t
            total = self.player.runtime.duration
            time_text = f"t={cur:.1f}/{total:.1f}s"
        else:
            t = self.t if self.mode in (MODE_RECORD, MODE_PAUSING,
                                        MODE_PAUSED, MODE_RESUMING) else 0.0
            time_text = f"t={t:.1f}s"
        text = f"{self.status}    |    {time_text}"
        ui.draw_status(self.screen, text, rect)
        self._draw_zoom_control(rect)

    def _draw_zoom_control(self, rect):
        zoom_text = f"Zoom: {int(round(self.view.scale * 100))}%  \u25be"
        click = pygame.Rect(rect.right - 118, rect.y + 2, 112, rect.h - 4)
        self._zoom_click_rect = click
        hover = click.collidepoint(pygame.mouse.get_pos())
        bg = C.COL_BUTTON_HOVER if (hover or self.zoom_menu_open) \
            else C.COL_PANEL
        pygame.draw.rect(self.screen, bg, click, border_radius=5)
        pygame.draw.rect(self.screen, C.COL_ACCENT, click, 1,
                         border_radius=5)
        font = ui.get_font(14)
        txt = font.render(zoom_text, True, C.COL_ACCENT)
        self.screen.blit(txt, txt.get_rect(center=click.center))

        if self.zoom_menu_open:
            self._draw_zoom_menu(click)

    def _draw_zoom_menu(self, click):
        options = [(1.0, "100%"), (0.75, "75%"), (0.5, "50%"),
                   (0.25, "25%")]
        row_h = 26
        box_w = 112
        box_h = row_h * len(options) + 8
        # drop the menu upwards from the status bar
        box = pygame.Rect(click.right - box_w, click.top - box_h - 4,
                          box_w, box_h)
        self._zoom_menu_box = box
        pygame.draw.rect(self.screen, C.COL_PANEL, box, border_radius=6)
        pygame.draw.rect(self.screen, C.COL_ACCENT, box, 1, border_radius=6)
        self._zoom_menu_rects = []
        font = ui.get_font(14)
        mouse = pygame.mouse.get_pos()
        for i, (factor, label) in enumerate(options):
            r = pygame.Rect(box.x + 4, box.y + 4 + i * row_h,
                            box.w - 8, row_h)
            self._zoom_menu_rects.append((r, factor))
            active = abs(self.view.scale - factor) < 1e-6
            if r.collidepoint(mouse):
                pygame.draw.rect(self.screen, C.COL_BUTTON_HOVER, r,
                                 border_radius=4)
            col = C.COL_ACCENT if (active or r.collidepoint(mouse)) \
                else C.COL_TEXT
            txt = font.render(label, True, col)
            self.screen.blit(txt, (r.x + 10,
                                   r.y + (r.h - txt.get_height()) // 2))
            if active:
                pygame.draw.rect(self.screen, C.COL_ACCENT, r, 1,
                                 border_radius=4)
