"""Scene and Stage: background + sprites; supports multiple scenes."""
import pygame
from . import config as C
from .sprite import Sprite


class Scene:
    def __init__(self, name="scene1", background=None, bg_key=None):
        self.name = name
        self.background = background   # pygame.Surface (scaled to frame) or None
        self.bg_key = bg_key           # logical id/name of background asset
        self.sprites = []              # list[Sprite]

    def add_sprite(self, sprite):
        self.sprites.append(sprite)
        return sprite

    def remove_sprite(self, sprite):
        if sprite in self.sprites:
            self.sprites.remove(sprite)

    def move_sprite_up(self, sprite):
        if sprite in self.sprites:
            idx = self.sprites.index(sprite)
            if idx < len(self.sprites) - 1:
                self.sprites[idx], self.sprites[idx + 1] = self.sprites[idx + 1], self.sprites[idx]
                return True
        return False

    def move_sprite_down(self, sprite):
        if sprite in self.sprites:
            idx = self.sprites.index(sprite)
            if idx > 0:
                self.sprites[idx], self.sprites[idx - 1] = self.sprites[idx - 1], self.sprites[idx]
                return True
        return False

    def bring_to_front(self, sprite):
        if sprite in self.sprites:
            self.sprites.remove(sprite)
            self.sprites.append(sprite)
            return True
        return False

    def send_to_back(self, sprite):
        if sprite in self.sprites:
            self.sprites.remove(sprite)
            self.sprites.insert(0, sprite)
            return True
        return False

    def find_sprite(self, wx, wy):
        # top-most first (last drawn is on top)
        for sp in reversed(self.sprites):
            if sp.contains(wx, wy):
                return sp
        return None

    def sprite_by_name(self, name):
        for sp in self.sprites:
            if sp.name == name:
                return sp
        return None

    def draw_frame(self, dest):
        """Draw the scene into a surface sized FRAME_W x FRAME_H."""
        if self.background is not None:
            dest.blit(self.background, (0, 0))
        else:
            dest.fill((0, 0, 0))
        for sp in self.sprites:
            # rotation-aware: the rotated surface is centred on the sprite's
            # rectangle, identical to blitting image at (x, y) when angle == 0
            sp.blit(dest, -C.MARGIN, -C.MARGIN)

    def to_dict(self):
        return {
            "name": self.name,
            "background": self.bg_key,
            "sprites": [sp.to_dict() for sp in self.sprites],
        }


class Stage:
    """Holds all scenes plus the currently active one."""

    def __init__(self):
        self.scenes = [Scene("scene1")]
        self.active_index = 0

    @property
    def active(self):
        return self.scenes[self.active_index]

    def get_scene(self, name):
        for s in self.scenes:
            if s.name == name:
                return s
        return None

    def add_scene(self, name=None):
        if name is None:
            name = f"scene{len(self.scenes) + 1}"
        sc = Scene(name)
        self.scenes.append(sc)
        return sc

    def switch_to(self, name):
        sc = self.get_scene(name)
        if sc is not None:
            self.active_index = self.scenes.index(sc)
        return sc