"""A minimal pygame file browser used in place of tkinter dialogs.

Tkinter is not always available (e.g. some Python 3.13 installs), so the app
ships its own dependency-free file picker. It supports navigating directories,
filtering by extension, single/multi selection and save-with-filename.
"""
import os

import pygame

from . import config as C
from . import ui

ROW_H = 30
PAD = 12


class FileBrowser:
    def __init__(self, screen, clock, title, mode="open", exts=None,
                 initialdir=None, initialfile="", multiple=False):
        self.screen = screen
        self.clock = clock
        self.title = title
        self.mode = mode               # "open" | "save"
        self.exts = tuple(e.lower() for e in (exts or ()))
        self.multiple = multiple
        self.cwd = os.path.abspath(initialdir or C.ROOT)
        self.filename = initialfile or ""
        self.scroll = 0
        self.selected = set()          # indices for multi-select
        self.entries = []
        self.result = None
        self.running = True
        self._edit_name = (mode == "save")
        self.input_focused = (mode == "save")
        self.cursor_pos = len(self.filename)
        self._cursor_timer = 0
        self._refresh()
        if self.mode == "directory":
            self.filename = os.path.basename(self.cwd) or self.cwd
            self.cursor_pos = len(self.filename)

    # ---- data ---------------------------------------------------------
    def _refresh(self):
        try:
            names = sorted(os.listdir(self.cwd))
        except OSError:
            names = []
        self.entries = []
        dirs, files = [], []
        for n in names:
            full = os.path.join(self.cwd, n)
            if os.path.isdir(full):
                dirs.append(n)
            elif self._matches(n):
                files.append(n)
        self.entries.append("..")
        self.entries += dirs
        self.entries += files
        self.selected.clear()
        self.scroll = 0

    def _matches(self, name):
        if not self.exts:
            return True
        return name.lower().endswith(self.exts)

    def _full(self, name):
        if name == "..":
            return os.path.dirname(self.cwd)
        return os.path.join(self.cwd, name)

    # ---- layout -------------------------------------------------------
    def _rect(self):
        w = min(720, C.WINDOW_W - 80)
        h = min(460, C.WINDOW_H - 80)
        return pygame.Rect((C.WINDOW_W - w) // 2, (C.WINDOW_H - h) // 2, w, h)

    def _list_rect(self, box):
        return pygame.Rect(box.x + PAD, box.y + 68,
                           box.w - 2 * PAD, box.h - 68 - 56)

    def _visible_rows(self, box):
        return max(1, self._list_rect(box).h // ROW_H)

    def _max_scroll(self, box):
        return max(0, len(self.entries) - self._visible_rows(box))

    def _row_index_at(self, box, pos):
        lr = self._list_rect(box)
        if not lr.collidepoint(pos):
            return None
        i = (pos[1] - lr.y) // ROW_H + self.scroll
        if 0 <= i < len(self.entries):
            return i
        return None

    # ---- main loop ----------------------------------------------------
    def run(self):
        while self.running:
            self.clock.tick(60)
            mouse = pygame.mouse.get_pos()
            for event in pygame.event.get():
                self._handle(event, mouse)
            self._draw(mouse)
            pygame.display.flip()
        return self.result

    def _handle(self, event, mouse):
        box = self._rect()
        if event.type == pygame.QUIT:
            self.result = None
            self.running = False
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.result = None
                self.running = False
            elif event.key == pygame.K_RETURN:
                self._confirm()
            elif self._edit_name and self.input_focused:
                if event.key == pygame.K_BACKSPACE:
                    if self.cursor_pos > 0:
                        self.filename = self.filename[:self.cursor_pos - 1] + self.filename[self.cursor_pos:]
                        self.cursor_pos -= 1
                elif event.key == pygame.K_DELETE:
                    if self.cursor_pos < len(self.filename):
                        self.filename = self.filename[:self.cursor_pos] + self.filename[self.cursor_pos + 1:]
                elif event.key == pygame.K_LEFT:
                    self.cursor_pos = max(0, self.cursor_pos - 1)
                elif event.key == pygame.K_RIGHT:
                    self.cursor_pos = min(len(self.filename), self.cursor_pos + 1)
                elif event.key == pygame.K_HOME:
                    self.cursor_pos = 0
                elif event.key == pygame.K_END:
                    self.cursor_pos = len(self.filename)
                elif event.unicode and event.unicode.isprintable():
                    self.filename = self.filename[:self.cursor_pos] + event.unicode + self.filename[self.cursor_pos:]
                    self.cursor_pos += len(event.unicode)
        elif event.type == pygame.MOUSEWHEEL:
            self.scroll = max(0, min(self.scroll - event.y,
                                     self._max_scroll(box)))
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._click(mouse, box)

    def _click(self, mouse, box):
        lr = self._list_rect(box)
        # up button
        if pygame.Rect(box.x + PAD, box.y + 34, 90, 24).collidepoint(mouse):
            self.cwd = os.path.dirname(self.cwd)
            self._refresh()
            if self.mode == "directory":
                self.filename = os.path.basename(self.cwd) or self.cwd
                self.cursor_pos = len(self.filename)
            return
        # action buttons
        if pygame.Rect(box.right - 200, box.bottom - 44, 90, 32).collidepoint(mouse):
            self.result = None
            self.running = False
            return
        if pygame.Rect(box.right - 104, box.bottom - 44, 92, 32).collidepoint(mouse):
            self._confirm()
            return
        # filename box click
        fb = pygame.Rect(box.x + PAD, box.bottom - 46, box.w - 2 * PAD - 220, 32)
        if fb.collidepoint(mouse) and self._edit_name:
            self.input_focused = True
            self.cursor_pos = len(self.filename)
            return

        idx = self._row_index_at(box, mouse)
        if idx is None:
            return
        name = self.entries[idx]
        full = self._full(name)
        if name == ".." or os.path.isdir(full):
            self.cwd = full
            self._refresh()
            if self.mode == "directory":
                self.filename = os.path.basename(self.cwd) or self.cwd
                self.cursor_pos = len(self.filename)
            return
        # file
        if self.mode == "directory":
            return
        if self.multiple:
            if idx in self.selected:
                self.selected.discard(idx)
            else:
                self.selected.add(idx)
            self.filename = name
            self.cursor_pos = len(self.filename)
        else:
            self.filename = name
            self.cursor_pos = len(self.filename)
            self.selected = {idx}

    def _confirm(self):
        if self.mode == "directory":
            self.result = self.cwd
            self.running = False
            return
        if self.multiple and self.selected:
            paths = [self._full(self.entries[i]) for i in sorted(self.selected)]
            self.result = paths
            self.running = False
            return
        if not self.filename:
            return
        if self.mode == "save":
            fname = self.filename
            if self.exts and not any(fname.lower().endswith(ext) for ext in self.exts):
                fname += self.exts[0]
            path = fname
            if not os.path.isabs(path):
                path = os.path.join(self.cwd, path)
            self.result = path
            self.running = False
        else:
            path = self.filename
            if not os.path.isabs(path):
                path = os.path.join(self.cwd, path)
            if os.path.exists(path):
                self.result = path
                self.running = False

    # ---- drawing ------------------------------------------------------
    def _draw(self, mouse):
        dim = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 150))
        self.screen.blit(dim, (0, 0))

        box = self._rect()
        pygame.draw.rect(self.screen, C.COL_PANEL, box, border_radius=8)
        pygame.draw.rect(self.screen, C.COL_ACCENT, box, 2, border_radius=8)
        ui.draw_label(self.screen, self.title, (box.x + PAD, box.y + 10),
                      size=18, bold=True)

        up = pygame.Rect(box.x + PAD, box.y + 34, 90, 24)
        pygame.draw.rect(self.screen, C.COL_BUTTON, up, border_radius=5)
        ui.draw_label(self.screen, ".. up", (up.x + 12, up.y + 4), size=14)
        path_txt = _shorten(self.cwd, 70)
        ui.draw_label(self.screen, path_txt,
                      (up.right + 12, box.y + 38), size=13, color=C.COL_TEXT_DIM)

        lr = self._list_rect(box)
        pygame.draw.rect(self.screen, (18, 18, 24), lr)
        rows = self._visible_rows(box)
        for r in range(rows):
            i = r + self.scroll
            if i >= len(self.entries):
                break
            name = self.entries[i]
            full = self._full(name)
            rr = pygame.Rect(lr.x, lr.y + r * ROW_H, lr.w, ROW_H)
            hovered = rr.collidepoint(mouse)
            chosen = i in self.selected
            if chosen:
                pygame.draw.rect(self.screen, C.COL_ACCENT, rr)
            elif hovered:
                pygame.draw.rect(self.screen, C.COL_PANEL_HDR, rr)
            if name == "..":
                label = ".."
                col = C.COL_TEXT_DIM
            elif os.path.isdir(full):
                label = "[D] " + name
                col = C.COL_TEXT
            else:
                label = "    " + name
                col = C.COL_TEXT
            ui.draw_label(self.screen, _shorten(label, 60),
                          (rr.x + 8, rr.y + 5), size=14, color=col)

        # filename box
        fb = pygame.Rect(box.x + PAD, box.bottom - 46, box.w - 2 * PAD - 220, 32)
        pygame.draw.rect(self.screen, (28, 28, 36), fb, border_radius=5)
        border_col = C.COL_ACCENT if (self._edit_name and self.input_focused) else C.COL_BUTTON
        pygame.draw.rect(self.screen, border_col, fb, 2 if self.input_focused else 1, border_radius=5)
        
        self._cursor_timer = (self._cursor_timer + 1) % 60
        show_cursor = self._edit_name and self.input_focused and (self._cursor_timer < 30)
        
        if self.filename:
            text_surf = ui.get_font(14).render(self.filename, True, C.COL_TEXT)
            self.screen.blit(text_surf, (fb.x + 8, fb.y + 7))
            if show_cursor:
                cursor_x = fb.x + 8 + ui.get_font(14).size(self.filename[:self.cursor_pos])[0]
                pygame.draw.line(self.screen, C.COL_ACCENT, (cursor_x, fb.y + 6), (cursor_x, fb.bottom - 7), 2)
        else:
            ui.draw_label(self.screen, "<type a name>" if self._edit_name else "",
                          (fb.x + 8, fb.y + 6), size=14, color=C.COL_TEXT_DIM)
            if show_cursor:
                pygame.draw.line(self.screen, C.COL_ACCENT, (fb.x + 8, fb.y + 6), (fb.x + 8, fb.bottom - 7), 2)

        cancel = pygame.Rect(box.right - 200, box.bottom - 44, 90, 32)
        accept = pygame.Rect(box.right - 104, box.bottom - 44, 92, 32)
        if self.mode == "directory":
            ok_label = "Choose"
        elif self.mode == "save":
            ok_label = "Save"
        else:
            ok_label = "Open"
        pygame.draw.rect(self.screen, C.COL_BUTTON, cancel, border_radius=6)
        ui.draw_label(self.screen, "Cancel",
                      (cancel.centerx - 24, cancel.y + 8), size=15)
        pygame.draw.rect(self.screen, C.COL_ACCENT, accept, border_radius=6)
        ui.draw_label(self.screen, ok_label,
                      (accept.centerx - len(ok_label) * 4, accept.y + 8),
                      size=15)


def _shorten(text, limit):
    if len(text) <= limit:
        return text
    half = (limit - 3) // 2
    return text[:half] + "..." + text[-half:]