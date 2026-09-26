"""Asset library: loads images, backgrounds and sounds, and generates
simple built-in placeholder backgrounds on first run.
"""
import os

import pygame

from . import config as C


class Assets:
    def __init__(self, sound_manager):
        self.root = C.ROOT
        self.sm = sound_manager
        self.images = {}         # key -> pygame.Surface (raw, un-scaled)
        self.backgrounds = {}    # key -> pygame.Surface (scaled to frame)
        self.raw_backgrounds = {}
        self.bg_paths = {}       # key -> filesystem path (for save/load)
        self.image_paths = {}

    # ---- loading ------------------------------------------------------
    def load_image_file(self, path):
        key = os.path.splitext(os.path.basename(path))[0]
        try:
            surf = pygame.image.load(path).convert_alpha()
        except pygame.error as exc:
            print(f"[assets] cannot load image {path}: {exc}")
            return None
        self.images[key] = surf
        self.image_paths[key] = path
        return key

    def load_images_from(self, directory):
        keys = []
        if not os.path.isdir(directory):
            return keys
        for fn in sorted(os.listdir(directory)):
            if fn.lower().endswith(C.IMAGE_EXTS):
                k = self.load_image_file(os.path.join(directory, fn))
                if k:
                    keys.append(k)
        return keys

    def load_background_file(self, path):
        key = os.path.splitext(os.path.basename(path))[0]
        try:
            surf = pygame.image.load(path).convert()
        except pygame.error as exc:
            print(f"[assets] cannot load background {path}: {exc}")
            return None
        self.raw_backgrounds[key] = surf
        self.backgrounds[key] = pygame.transform.smoothscale(
            surf, (C.FRAME_W, C.FRAME_H))
        self.bg_paths[key] = path
        return key

    def load_backgrounds_from(self, directory):
        keys = []
        if not os.path.isdir(directory):
            return keys
        for fn in sorted(os.listdir(directory)):
            if fn.lower().endswith(C.IMAGE_EXTS):
                k = self.load_background_file(os.path.join(directory, fn))
                if k:
                    keys.append(k)
        return keys

    def add_background_surface(self, key, raw_surface, path=None):
        self.raw_backgrounds[key] = raw_surface
        self.backgrounds[key] = pygame.transform.smoothscale(
            raw_surface, (C.FRAME_W, C.FRAME_H))
        if path:
            self.bg_paths[key] = path
        return key

    def rescale_backgrounds(self, w, h):
        for key, raw in self.raw_backgrounds.items():
            self.backgrounds[key] = pygame.transform.smoothscale(raw, (w, h))

    # ---- access -------------------------------------------------------
    def get_image(self, key):
        if key in self.images:
            return self.images[key]
        return _placeholder_sprite()

    def get_background(self, key):
        return self.backgrounds.get(key)

    # ---- built-in placeholders ---------------------------------------
    def ensure_builtin_backgrounds(self):
        """Generate a handful of gradient backgrounds if none exist yet."""
        os.makedirs(C.BUILTIN_DIR, exist_ok=True)
        specs = [
            ("gradient_sky", (25, 60, 120), (120, 190, 240)),
            ("gradient_sunset", (240, 120, 60), (60, 20, 80)),
            ("gradient_forest", (20, 80, 40), (140, 200, 90)),
            ("gradient_night", (10, 10, 30), (60, 40, 90)),
            ("solid_gray", (70, 70, 75), (110, 110, 118)),
            ("solid_black", (0, 0, 0), (0, 0, 0)),
        ]
        for key, top, bottom in specs:
            path = os.path.join(C.BUILTIN_DIR, key + ".png")
            if not os.path.exists(path):
                surf = _vertical_gradient(C.FRAME_W, C.FRAME_H, top, bottom)
                pygame.image.save(surf, path)
            self.load_background_file(path)
        return list(self.backgrounds.keys())


def _vertical_gradient(w, h, top, bottom):
    surf = pygame.Surface((w, h))
    for y in range(h):
        a = y / max(1, h - 1)
        col = (int(top[0] + (bottom[0] - top[0]) * a),
               int(top[1] + (bottom[1] - top[1]) * a),
               int(top[2] + (bottom[2] - top[2]) * a))
        pygame.draw.line(surf, col, (0, y), (w, y))
    return surf


def _placeholder_sprite():
    surf = pygame.Surface((80, 80), pygame.SRCALPHA)
    surf.fill((200, 60, 60, 255))
    pygame.draw.rect(surf, (255, 255, 255), surf.get_rect(), 3)
    return surf