"""Slide-out panels on the right side: Sprites, Sounds, Backgrounds, Scenes.

Each panel shows a scrollable list of items. Items support click actions;
sprite items also support drag-and-drop onto the stage (the engine handles the
actual drop by querying `drag_item`).
"""
import pygame

from . import config as C
from . import ui

TAB_H = 34
ROW_H = 56
THUMB = 40

PANELS = ("Sprites", "Sounds", "Backgrounds", "Scenes")


class Panel:
    def __init__(self, name):
        self.name = name
        self.items = []      # list[dict] with keys: key, label, thumb(Surface|None)
        self.scroll = 0
        self.active_key = None   # key of the currently active item (highlighted)

    def set_items(self, items):
        self.items = items
        # keep scroll in range
        self.scroll = min(self.scroll, self.max_scroll())

    def content_h(self):
        return len(self.items) * ROW_H

    def max_scroll(self):
        view_h = _content_view_h()
        return max(0, self.content_h() - view_h)


def _content_view_h():
    return C.CANVAS_H - TAB_H  # placeholder; recomputed by manager


class PanelManager:
    def __init__(self, area_rect):
        # area_rect: pygame.Rect of the panel region (right side), when open.
        self.area = pygame.Rect(area_rect)
        self.visible = True
        self.panels = {name: Panel(name) for name in PANELS}
        self.active_name = "Sprites"
        self.tab_rects = {}
        self.content_y = self.area.y + len(PANELS) * TAB_H
        self._layout_tabs()
        self.drag_item = None       # (panel_name, item) being dragged
        self.drag_thumb = None
        self.drag_pos = (0, 0)
        self._scrolling = False
        self._scroll_start = (0, 0)

    def _layout_tabs(self):
        x = self.area.x
        y = self.area.y
        w = self.area.w
        self.tab_rects = {}
        for i, name in enumerate(PANELS):
            self.tab_rects[name] = pygame.Rect(x, y + i * TAB_H, w, TAB_H)

    @property
    def active(self):
        return self.panels[self.active_name]

    def toggle(self):
        self.visible = not self.visible

    def _content_rect(self):
        return pygame.Rect(self.area.x, self.area.y,
                           self.area.w, self.area.h)

    def _row_rect(self, i):
        y = self.content_y + i * ROW_H - self.active.scroll
        return pygame.Rect(self.area.x, y, self.area.w, ROW_H)

    def _item_at(self, pos):
        if not self.area.collidepoint(pos):
            return None, None
        for i, item in enumerate(self.active.items):
            if self._row_rect(i).collidepoint(pos):
                return i, item
        return None, None

    # ---- events -------------------------------------------------------
    def handle_event(self, event, mouse_pos):
        """Returns an action tuple or None.

        Click on panel tab -> ("tab", name); item click -> ("item", panel,
        item); drag start -> ("drag_start", panel, item). The engine decides
        what to do based on the panel.
        """
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for name, rect in self.tab_rects.items():
                if rect.collidepoint(event.pos):
                    self.active_name = name
                    return ("tab", name)
            idx, item = self._item_at(event.pos)
            if item is not None:
                if self.active_name == "Sprites":
                    self.drag_item = ("Sprites", item)
                    self.drag_thumb = item.get("thumb")
                    self.drag_pos = event.pos
                    return ("drag_start", "Sprites", item)
                return ("item", self.active_name, item)
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.drag_item is not None:
                item = self.drag_item[1]
                self.drag_item = None
                thumb = self.drag_thumb
                self.drag_thumb = None
                return ("drop", "Sprites", item, event.pos, thumb)
        elif event.type == pygame.MOUSEMOTION:
            if self.drag_item is not None:
                self.drag_pos = event.pos
        elif event.type == pygame.MOUSEWHEEL:
            if self.area.collidepoint(mouse_pos):
                self.active.scroll -= event.y * ROW_H
                self.active.scroll = max(0, min(self.active.scroll,
                                                self.active.max_scroll()))
        return None

    # ---- drawing ------------------------------------------------------
    def draw(self, surf):
        if not self.visible:
            return
        area = self.area
        pygame.draw.rect(surf, C.COL_PANEL, area)
        pygame.draw.line(surf, C.COL_PANEL_HDR, (area.x, area.y),
                         (area.x, area.bottom), 2)
        # tabs
        font = ui.get_font(15, bold=True)
        for name, rect in self.tab_rects.items():
            col = C.COL_ACCENT if name == self.active_name else C.COL_PANEL_HDR
            pygame.draw.rect(surf, col, rect)
            pygame.draw.rect(surf, C.COL_BG, rect, 1)
            txt = font.render(name, True, C.COL_TEXT)
            surf.blit(txt, txt.get_rect(center=rect.center))
        # items
        content_top = self.content_y
        clip = surf.get_clip()
        surf.set_clip(pygame.Rect(area.x, content_top, area.w,
                                  area.bottom - content_top))
        for i, item in enumerate(self.active.items):
            rr = self._row_rect(i)
            if rr.bottom < content_top or rr.y > area.bottom:
                continue
            is_active = (item.get("key") == self.active.active_key)
            hovered = rr.collidepoint(pygame.mouse.get_pos())
            if is_active:
                pygame.draw.rect(surf, C.COL_ACCENT, rr)
            elif hovered:
                pygame.draw.rect(surf, C.COL_PANEL_HDR, rr)
            thumb = item.get("thumb")
            if thumb is not None:
                surf.blit(thumb, (rr.x + 8, rr.y + (ROW_H - THUMB) // 2))
            ui.draw_label(surf, item.get("label", "?"),
                          (rr.x + THUMB + 18, rr.y + (ROW_H - 16) // 2),
                          size=15)
            pygame.draw.line(surf, C.COL_BG, (rr.x, rr.bottom - 1),
                             (rr.right, rr.bottom - 1))
        surf.set_clip(clip)

        # drag ghost
        if self.drag_thumb is not None:
            surf.blit(self.drag_thumb, self.drag_pos)