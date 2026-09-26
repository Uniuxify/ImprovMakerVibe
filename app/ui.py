"""Small immediate-mode UI widgets: buttons, labels and text input.

All file dialogs are backed by the built-in pygame `FileBrowser`, so the app
has no external GUI dependency (tkinter is not required).
"""
import pygame

from . import config as C

_font_cache = {}


def get_font(size=18, bold=False):
    key = (size, bold)
    if key not in _font_cache:
        _font_cache[key] = pygame.font.SysFont("segoeui,arial", size, bold=bold)
    return _font_cache[key]


class Button:
    def __init__(self, rect, label, color=None, text_color=None, toggle=False):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.color = color or C.COL_BUTTON
        self.text_color = text_color or C.COL_TEXT
        self.toggle = toggle
        self.active = False
        self.hover = False
        self.enabled = True

    def draw(self, surf):
        if not self.enabled:
            pygame.draw.rect(surf, C.COL_BUTTON_DISABLED, self.rect,
                             border_radius=6)
            font = get_font(18, bold=True)
            txt = font.render(self.label, True, C.COL_TEXT_DISABLED)
            surf.blit(txt, txt.get_rect(center=self.rect.center))
            return
        col = self.color
        if self.hover:
            col = C.COL_BUTTON_HOVER
        if self.toggle and self.active:
            col = C.COL_ACCENT
        pygame.draw.rect(surf, col, self.rect, border_radius=6)
        if self.toggle and self.active:
            pygame.draw.rect(surf, (255, 255, 255), self.rect, 2,
                             border_radius=6)
        font = get_font(18, bold=True)
        txt = font.render(self.label, True, self.text_color)
        surf.blit(txt, txt.get_rect(center=self.rect.center))

    def handle_event(self, event, mouse_pos):
        if event.type == pygame.MOUSEMOTION:
            self.hover = self.enabled and self.rect.collidepoint(mouse_pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if not self.enabled:
                return False
            if self.rect.collidepoint(event.pos):
                if self.toggle:
                    self.active = not self.active
                return True
        return False


def draw_label(surf, text, pos, size=16, color=None, bold=False):
    font = get_font(size, bold)
    img = font.render(text, True, color or C.COL_TEXT)
    surf.blit(img, pos)
    return img.get_rect(topleft=pos)


def draw_status(surf, text, rect):
    pygame.draw.rect(surf, (15, 15, 20), rect)
    draw_label(surf, text, (rect.x + 8, rect.y + (rect.h - 16) // 2),
               size=15, color=C.COL_TEXT_DIM)


# ---- convenience functions (used by the engine) ----------------------
def open_files(screen, clock, title, exts=None, initialdir=None):
    from .filebrowser import FileBrowser
    fb = FileBrowser(screen, clock, title, mode="open", exts=exts,
                     initialdir=initialdir, multiple=True)
    return fb.run() or []


def open_file(screen, clock, title, exts=None, initialdir=None):
    from .filebrowser import FileBrowser
    fb = FileBrowser(screen, clock, title, mode="open", exts=exts,
                     initialdir=initialdir, multiple=False)
    return fb.run()


def save_file(screen, clock, title, exts=None, initialdir=None,
              initialfile=""):
    from .filebrowser import FileBrowser
    fb = FileBrowser(screen, clock, title, mode="save", exts=exts,
                     initialdir=initialdir, initialfile=initialfile)
    return fb.run()