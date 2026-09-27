"""Coordinate transforms between the canvas, the on-screen stage and the export frame.

World coordinates are relative to the top-left of the *buffer canvas*
(0..CANVAS_W, 0..CANVAS_H). The visible frame starts at (MARGIN, MARGIN).
The on-screen stage shows a PEEK-wide slice of the buffer around the frame.
"""
from . import config as C


class View:
    def __init__(self):
        self.frame_w = C.FRAME_W
        self.frame_h = C.FRAME_H
        self.stage_w = C.STAGE_W
        self.stage_h = C.STAGE_H
        self.scale = 1.0
        # Screen position of the top-left corner of the visible frame.
        self.frame_x = C.PEEK
        self.frame_y = C.UI_TOP_H + C.PEEK

    def set_frame_size(self, w, h):
        self.frame_w = int(w)
        self.frame_h = int(h)

    def set_stage_size(self, w, h):
        self.stage_w = int(w)
        self.stage_h = int(h)

    def zoom(self, factor, mouse_sx, mouse_sy):
        old_scale = self.scale
        new_scale = max(0.25, min(3.0, round(old_scale * factor, 2)))
        if new_scale == old_scale:
            return
        wx, wy = self.s2w(mouse_sx, mouse_sy)
        self.scale = new_scale
        self.frame_x = mouse_sx - (wx - C.MARGIN) * self.scale
        self.frame_y = mouse_sy - (wy - C.MARGIN) * self.scale

    def reset_view(self):
        self.scale = 1.0
        self.frame_x = max(10.0, (self.stage_w - self.frame_w * self.scale) / 2.0)
        self.frame_y = max(float(C.UI_TOP_H + 10), C.UI_TOP_H + (self.stage_h - self.frame_h * self.scale) / 2.0)

    def pan(self, dx, dy):
        """Shift the view by a screen-space delta (used by middle-drag)."""
        self.frame_x += dx
        self.frame_y += dy

    # world (canvas) -> screen
    def w2s(self, x, y):
        return (self.frame_x + (x - C.MARGIN) * self.scale,
                self.frame_y + (y - C.MARGIN) * self.scale)

    # screen -> world (canvas)
    def s2w(self, sx, sy):
        return ((sx - self.frame_x) / self.scale + C.MARGIN,
                (sy - self.frame_y) / self.scale + C.MARGIN)

    def frame_rect_screen(self):
        return (self.frame_x, self.frame_y,
                self.frame_w * self.scale, self.frame_h * self.scale)

    def stage_rect(self):
        return (0, C.UI_TOP_H, self.stage_w, self.stage_h)

    def in_stage(self, sx, sy):
        return (0 <= sx < self.stage_w and C.UI_TOP_H <= sy < C.UI_TOP_H + self.stage_h)

    def in_frame(self, wx, wy):
        return (C.MARGIN <= wx <= C.MARGIN + self.frame_w and
                C.MARGIN <= wy <= C.MARGIN + self.frame_h)
