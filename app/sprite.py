"""Sprite model: an image placed on the stage at world coordinates."""
import os
import pygame

HANDLE_TOL = 9          # world-space tolerance for grabbing a resize handle


class Sprite:
    _next_id = 1

    def __init__(self, name, image, x, y, image_key=None,
                 scale_x=1.0, scale_y=1.0, flip_x=False, flip_y=False):
        self.id = f"s{Sprite._next_id}"
        Sprite._next_id += 1
        self.name = name            # logical name (also key in event log)
        self.orig_image = image     # pygame.Surface (original, un-scaled)
        self.image_key = image_key if image_key is not None else name
        self.x = float(x)           # world coordinate (top-left of image)
        self.y = float(y)
        self.scale_x = float(scale_x)
        self.scale_y = float(scale_y)
        self.flip_x = bool(flip_x)
        self.flip_y = bool(flip_y)
        self.image = self.orig_image
        self._apply_scale()

    def _apply_scale(self):
        ow = max(1, self.orig_image.get_width())
        oh = max(1, self.orig_image.get_height())
        w = max(1, int(round(ow * self.scale_x)))
        h = max(1, int(round(oh * self.scale_y)))
        if w == ow and h == oh:
            base = self.orig_image
        else:
            base = pygame.transform.smoothscale(self.orig_image, (w, h))
        if self.flip_x or self.flip_y:
            self.image = pygame.transform.flip(base, self.flip_x, self.flip_y)
        else:
            self.image = base

    def set_scale(self, sx, sy=None, min_scale=0.05):
        if sy is None:
            sy = sx
        self.scale_x = max(min_scale, float(sx))
        self.scale_y = max(min_scale, float(sy))
        self._apply_scale()

    def set_flip(self, flip_x=None, flip_y=None):
        if flip_x is not None:
            self.flip_x = bool(flip_x)
        if flip_y is not None:
            self.flip_y = bool(flip_y)
        self._apply_scale()

    def toggle_flip_h(self):
        self.set_flip(flip_x=not self.flip_x)

    def toggle_flip_v(self):
        self.set_flip(flip_y=not self.flip_y)

    @property
    def w(self):
        return self.image.get_width()

    @property
    def h(self):
        return self.image.get_height()

    @property
    def orig_w(self):
        return self.orig_image.get_width()

    @property
    def orig_h(self):
        return self.orig_image.get_height()

    def handle_points(self):
        x, y, w, h = self.x, self.y, self.w, self.h
        return {
            "top": (x + w / 2.0, y),
            "bottom": (x + w / 2.0, y + h),
            "left": (x, y + h / 2.0),
            "right": (x + w, y + h / 2.0),
            "top_left": (x, y),
            "top_right": (x + w, y),
            "bottom_left": (x, y + h),
            "bottom_right": (x + w, y + h),
        }

    def hit_handle(self, wx, wy, tol=HANDLE_TOL):
        for name, (hx, hy) in self.handle_points().items():
            if abs(wx - hx) <= tol and abs(wy - hy) <= tol:
                return name
        return None

    def rect(self):
        return pygame.Rect(int(self.x), int(self.y), self.w, self.h)

    def contains(self, wx, wy):
        return self.rect().collidepoint(int(wx), int(wy))

    def draw(self, surf):
        surf.blit(self.image, (int(self.x), int(self.y)))

    @staticmethod
    def from_file(path, x=0, y=0):
        image = pygame.image.load(path).convert_alpha()
        name = os.path.splitext(os.path.basename(path))[0]
        return Sprite(name, image, x, y, image_key=name)

    def to_dict(self):
        return {"name": self.name, "image": self.image_key,
                "x": self.x, "y": self.y,
                "scale_x": self.scale_x, "scale_y": self.scale_y,
                "flip_x": self.flip_x, "flip_y": self.flip_y}

    def __repr__(self):
        return f"Sprite({self.id}:{self.name} @ {self.x:.0f},{self.y:.0f})"