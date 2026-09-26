"""Sound manager: load and play sound effects via pygame.mixer."""
import os
import pygame
from . import config as C


class SoundManager:
    def __init__(self):
        self.sounds = {}   # name -> pygame.mixer.Sound
        self.paths = {}    # name -> filesystem path
        try:
            # mono mixer so the (mono) microphone track is not stretched 2x
            pygame.mixer.init(frequency=C.SAMPLE_RATE, size=-16, channels=1,
                              buffer=512)
        except pygame.error as exc:  # pragma: no cover
            print(f"[sound] mixer init failed: {exc}")

    def load(self, path):
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            snd = pygame.mixer.Sound(path)
        except pygame.error as exc:
            print(f"[sound] cannot load {path}: {exc}")
            return None
        self.sounds[name] = snd
        self.paths[name] = path
        return name

    def load_all_from(self, directory):
        if not os.path.isdir(directory):
            return []
        loaded = []
        for fn in sorted(os.listdir(directory)):
            if fn.lower().endswith(C.SOUND_EXTS):
                name = self.load(os.path.join(directory, fn))
                if name:
                    loaded.append(name)
        return loaded

    def get(self, name):
        return self.sounds.get(name)

    def play(self, name):
        snd = self.sounds.get(name)
        if snd is not None:
            snd.play()
        return snd

    def stop_all(self):
        try:
            pygame.mixer.stop()
        except pygame.error:
            pass