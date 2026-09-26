"""Built-in transitions drawn as overlays on the frame surface.

`cover` is 0.0 (transition fully open, scene visible) .. 1.0 (fully closed).
"""
import pygame
from . import config as C

BLACK = (0, 0, 0)
CURTAIN_COL = (140, 20, 30)
CURTAIN_EDGE = (90, 12, 20)


def draw(cover, kind, surface):
    """Draw transition `kind` onto `surface` (FRAME_W x FRAME_H)."""
    cover = max(0.0, min(1.0, cover))
    if cover <= 0.0:
        return
    if kind == "fade":
        _fade(cover, surface)
    elif kind == "wipe":
        _wipe(cover, surface)
    else:  # "curtain" and any unknown -> curtain
        _curtain(cover, surface)


def _fade(cover, surface):
    overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, int(255 * cover)))
    surface.blit(overlay, (0, 0))


def _wipe(cover, surface):
    w = surface.get_width()
    h = surface.get_height()
    edge = int(w * cover)
    pygame.draw.rect(surface, BLACK, (0, 0, edge, h))
    pygame.draw.line(surface, C.COL_ACCENT, (edge, 0), (edge, h), 3)


def _curtain(cover, surface):
    w = surface.get_width()
    h = surface.get_height()
    half = int((w / 2) * cover)
    pygame.draw.rect(surface, CURTAIN_COL, (0, 0, half, h))
    pygame.draw.rect(surface, CURTAIN_COL, (w - half, 0, half, h))
    for i in range(0, max(half, 1), 40):
        pygame.draw.line(surface, CURTAIN_EDGE, (i, 0), (i, h), 2)
        pygame.draw.line(surface, CURTAIN_EDGE, (w - i, 0), (w - i, h), 2)
    if half > 0:
        pygame.draw.line(surface, CURTAIN_EDGE, (half, 0), (half, h), 4)
        pygame.draw.line(surface, CURTAIN_EDGE, (w - half, 0), (w - half, h), 4)