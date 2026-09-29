"""Sprite model: an image placed on the stage at world coordinates.

A sprite may be rotated around its centre (`angle` in degrees, counter-clockwise
like `pygame.transform.rotate`). `x, y` stay the top-left of the *unrotated*
rectangle and `w/h/scale` are measured on it; `rot_image` is the rotated
surface actually drawn, centred on the same rectangle (identical to `image`
when `angle == 0`).
"""
import math
import os

import pygame

HANDLE_TOL = 9          # world-space tolerance for grabbing a resize handle


def norm_angle(a):
    """Normalise an angle in degrees into (-180, 180]."""
    a = math.fmod(float(a), 360.0)
    if a <= -180.0:
        a += 360.0
    elif a > 180.0:
        a -= 360.0
    return a


def rotate_point(px, py, cx, cy, angle_deg):
    """Rotate (px, py) around (cx, cy) by `angle_deg` degrees.

    Positive angles turn counter-clockwise on screen, matching
    `pygame.transform.rotate`. Screen space has y pointing down, so the
    counter-clockwise matrix is transposed compared to the math convention.
    """
    a = math.radians(angle_deg)
    cos_a, sin_a = math.cos(a), math.sin(a)
    dx, dy = px - cx, py - cy
    return (cx + dx * cos_a + dy * sin_a,
            cy - dx * sin_a + dy * cos_a)


class Sprite:
    _next_id = 1

    def __init__(self, name, image, x, y, image_key=None,
                 scale_x=1.0, scale_y=1.0, flip_x=False, flip_y=False,
                 angle=0.0):
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
        self.angle = norm_angle(angle)   # degrees, CCW, around the centre
        self.image = self.orig_image
        self.rot_image = self.orig_image
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
        self._update_rot()

    def _update_rot(self):
        """Rebuild the rotated render surface (`image` stays unrotated)."""
        if abs(self.angle) < 1e-9:
            self.rot_image = self.image
        else:
            self.rot_image = pygame.transform.rotate(self.image, self.angle)

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

    def set_angle(self, angle):
        self.angle = norm_angle(angle)
        self._update_rot()

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

    @property
    def center(self):
        """Centre of the (unrotated) rectangle in world space."""
        return (self.x + self.w / 2.0, self.y + self.h / 2.0)

    def handle_points(self):
        """8 resize handles, rotated around the centre together with the
        sprite (axis-aligned box when angle == 0)."""
        x, y, w, h = self.x, self.y, self.w, self.h
        pts = {
            "top": (x + w / 2.0, y),
            "bottom": (x + w / 2.0, y + h),
            "left": (x, y + h / 2.0),
            "right": (x + w, y + h / 2.0),
            "top_left": (x, y),
            "top_right": (x + w, y),
            "bottom_left": (x, y + h),
            "bottom_right": (x + w, y + h),
        }
        if abs(self.angle) < 1e-9:
            return pts
        cx, cy = self.center
        return {k: rotate_point(px, py, cx, cy, self.angle)
                for k, (px, py) in pts.items()}

    def hit_handle(self, wx, wy, tol=HANDLE_TOL):
        for name, (hx, hy) in self.handle_points().items():
            if abs(wx - hx) <= tol and abs(wy - hy) <= tol:
                return name
        return None

    def rect(self):
        return pygame.Rect(int(self.x), int(self.y), self.w, self.h)

    def contains(self, wx, wy):
        """Point test in the sprite's local (unrotated) space, so the hitbox
        matches the visible rotated image."""
        if abs(self.angle) < 1e-9:
            return self.rect().collidepoint(int(wx), int(wy))
        cx, cy = self.center
        lx, ly = rotate_point(wx, wy, cx, cy, -self.angle)
        return self.rect().collidepoint(int(lx), int(ly))

    def blit(self, surf, dx=0, dy=0):
        """Draw the (possibly rotated) image onto `surf`, shifted by (dx, dy).

        The rotated surface is centred on the unrotated rectangle, so for
        angle == 0 this is identical to blitting `image` at (x, y).
        """
        if abs(self.angle) < 1e-9:
            surf.blit(self.image, (int(self.x) + dx, int(self.y) + dy))
        else:
            cx = self.x + self.w / 2.0 + dx
            cy = self.y + self.h / 2.0 + dy
            surf.blit(self.rot_image, self.rot_image.get_rect(center=(cx, cy)))

    def draw(self, surf):
        self.blit(surf)

    @staticmethod
    def from_file(path, x=0, y=0):
        image = pygame.image.load(path).convert_alpha()
        name = os.path.splitext(os.path.basename(path))[0]
        return Sprite(name, image, x, y, image_key=name)

    def to_dict(self):
        return {"name": self.name, "image": self.image_key,
                "x": self.x, "y": self.y,
                "scale_x": self.scale_x, "scale_y": self.scale_y,
                "flip_x": self.flip_x, "flip_y": self.flip_y,
                "angle": self.angle}

    def __repr__(self):
        return f"Sprite({self.id}:{self.name} @ {self.x:.0f},{self.y:.0f})"
