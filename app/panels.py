"""Slide-out panels on the right side: Sprites, Sounds, Backgrounds, Scenes.

Sprites and backgrounds are shown as an adaptive icon grid. Sounds and scenes
remain full-width list rows. The panel can be resized by dragging its left
edge; it overlays the stage and does not change the stage layout.
"""
import pygame

from . import config as C
from . import ui

TAB_H = 34
ROW_H = 56
THUMB = 40

PANELS = ("Sprites", "Sounds", "Backgrounds", "Scenes")
GRID_PANELS = {"Sprites", "Backgrounds"}


class Panel:
    def __init__(self, name):
        self.name = name
        self.items = []      # list[dict] with keys: key, label, thumb(Surface|None)
        self.scroll = 0
        self.active_key = None   # key of the currently active item (highlighted)

    def set_items(self, items):
        self.items = items


def _truncate(text, font, max_width):
    if font.size(text)[0] <= max_width:
        return text
    ellipsis = "..."
    while text and font.size(text + ellipsis)[0] > max_width:
        text = text[:-1]
    return (text + ellipsis) if text else ellipsis


class PanelManager:
    def __init__(self, area_rect, min_width=C.PANEL_MIN_W,
                 max_width=C.PANEL_MIN_W):
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

        self.min_width = int(min_width)
        self.max_width = max(self.min_width, int(max_width))
        self.width = int(self.area.w)
        self._right = int(self.area.right)
        self._resizing = False
        self.set_width(self.width)

    def _layout_tabs(self):
        x = self.area.x
        y = self.area.y
        w = self.area.w
        self.tab_rects = {}
        for i, name in enumerate(PANELS):
            self.tab_rects[name] = pygame.Rect(x, y + i * TAB_H, w, TAB_H)
        self.content_y = y + len(PANELS) * TAB_H

    @property
    def active(self):
        return self.panels[self.active_name]

    def toggle(self):
        self.visible = not self.visible

    def set_bounds(self, right=None, height=None):
        changed = False

        if right is not None:
            new_right = int(right)
            if self._right != new_right:
                self._right = new_right
                changed = True

        if self.area.y != C.UI_TOP_H:
            self.area.y = C.UI_TOP_H
            changed = True

        if height is not None:
            new_h = max(0, int(height))
            if self.area.h != new_h:
                self.area.h = new_h
                changed = True

        new_x = self._right - self.width
        if self.area.x != new_x or self.area.w != self.width:
            self.area.x = new_x
            self.area.w = self.width
            changed = True

        if changed:
            self._layout_tabs()
            self._clamp_scroll(self.active)

        return changed

    def set_width(self, width):
        width = max(self.min_width, min(self.max_width, int(width)))
        changed = False
        if self.width != width:
            self.width = width
            changed = True
        return self.set_bounds() or changed

    def set_items(self, panel_name, items):
        panel = self.panels[panel_name]
        panel.set_items(items)
        self._clamp_scroll(panel)

    def _resize_rect(self):
        grab = max(6, C.PANEL_RESIZE_GRAB)
        return pygame.Rect(self.area.x - grab // 2, self.area.y, grab,
                           self.area.h)

    def _view_h(self):
        return max(0, self.area.bottom - self.content_y)

    def _content_h(self, panel):
        if panel.name in GRID_PANELS:
            if not panel.items:
                return 0
            cols = self._grid_columns()
            rows = (len(panel.items) + cols - 1) // cols
            return rows * C.PANEL_GRID_ROW_H
        return len(panel.items) * ROW_H

    def _max_scroll(self, panel):
        return max(0, self._content_h(panel) - self._view_h())

    def _clamp_scroll(self, panel):
        panel.scroll = max(0, min(panel.scroll, self._max_scroll(panel)))

    def _grid_columns(self, width=None):
        width = self.area.w if width is None else int(width)
        available = max(0, width - 2 * C.PANEL_GRID_PADDING)
        icon = C.PANEL_ICON_SIZE
        min_gap = C.PANEL_GRID_MIN_GAP
        if available < icon:
            return 1
        cols = (available + min_gap) // (icon + min_gap)
        return max(1, min(int(cols), C.PANEL_GRID_MAX_COLUMNS))

    def _grid_gap(self, columns, width=None):
        width = self.area.w if width is None else int(width)
        if columns <= 1:
            return 0
        available = max(0, width - 2 * C.PANEL_GRID_PADDING)
        gap = (available - columns * C.PANEL_ICON_SIZE) / (columns - 1)
        return max(C.PANEL_GRID_MIN_GAP, gap)

    def _grid_layout(self):
        cols = self._grid_columns()
        if cols <= 1:
            gap = 0
            total = C.PANEL_ICON_SIZE
        else:
            gap = self._grid_gap(cols)
            total = cols * C.PANEL_ICON_SIZE + (cols - 1) * gap
        x0 = self.area.x + (self.area.w - total) / 2.0
        return cols, gap, x0

    def _grid_rect(self, index, columns, gap, x0):
        row = index // columns
        col = index % columns
        x = int(x0 + col * (C.PANEL_ICON_SIZE + gap))
        y = (self.content_y + row * C.PANEL_GRID_ROW_H +
             (C.PANEL_GRID_ROW_H - C.PANEL_ICON_SIZE) // 2 -
             self.active.scroll)
        return pygame.Rect(x, y, C.PANEL_ICON_SIZE, C.PANEL_ICON_SIZE)

    def _row_rect(self, i):
        y = self.content_y + i * ROW_H - self.active.scroll
        return pygame.Rect(self.area.x, y, self.area.w, ROW_H)

    def _item_at(self, pos):
        if not self.area.collidepoint(pos):
            return None, None, None

        if self.active_name in GRID_PANELS:
            cols, gap, x0 = self._grid_layout()
            for i, item in enumerate(self.active.items):
                rect = self._grid_rect(i, cols, gap, x0)
                if rect.collidepoint(pos):
                    return i, item, rect
        else:
            for i, item in enumerate(self.active.items):
                rect = self._row_rect(i)
                if rect.collidepoint(pos):
                    return i, item, rect
        return None, None, None

    # ---- events -------------------------------------------------------
    def handle_event(self, event, mouse_pos):
        """Returns an action tuple or None.

        Click on panel tab -> ("tab", name); item click -> ("item", panel,
        item); drag start -> ("drag_start", panel, item); panel resize ->
        ("panel_resize", width) / ("panel_resize_end", width). The engine
        decides what to do based on the panel.
        """
        if not self.visible:
            return None

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._resize_rect().collidepoint(event.pos):
                self._resizing = True
                return ("panel_resize", self.width)

            for name, rect in self.tab_rects.items():
                if rect.collidepoint(event.pos):
                    self.active_name = name
                    self._clamp_scroll(self.active)
                    return ("tab", name)

            idx, item, rect = self._item_at(event.pos)
            if item is not None:
                if self.active_name == "Sprites":
                    self.drag_item = ("Sprites", item)
                    self.drag_thumb = item.get("thumb")
                    self.drag_pos = event.pos
                    return ("drag_start", "Sprites", item)
                return ("item", self.active_name, item)

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self._resizing:
                self._resizing = False
                return ("panel_resize_end", self.width)

            if self.drag_item is not None:
                item = self.drag_item[1]
                self.drag_item = None
                thumb = self.drag_thumb
                self.drag_thumb = None
                return ("drop", "Sprites", item, event.pos, thumb)

        elif event.type == pygame.MOUSEMOTION:
            if self._resizing:
                desired_width = int(self._right - event.pos[0])
                return ("panel_resize", desired_width)
            if self.drag_item is not None:
                self.drag_pos = event.pos

        elif event.type == pygame.MOUSEWHEEL:
            if self.area.collidepoint(mouse_pos):
                step = (C.PANEL_GRID_ROW_H if self.active_name in GRID_PANELS
                        else ROW_H)
                self.active.scroll -= event.y * step
                self._clamp_scroll(self.active)

        return None

    # ---- drawing ------------------------------------------------------
    def draw(self, surf):
        if not self.visible:
            return

        area = self.area
        mouse = pygame.mouse.get_pos()
        pygame.draw.rect(surf, C.COL_PANEL, area)

        handle_hover = self._resize_rect().collidepoint(mouse)
        handle_col = (C.COL_ACCENT if self._resizing or handle_hover
                      else C.COL_PANEL_HDR)
        pygame.draw.line(surf, handle_col, (area.x, area.y),
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
        tooltip_text = None
        tooltip_pos = mouse

        if self.active_name in GRID_PANELS:
            cols, gap, x0 = self._grid_layout()
            for i, item in enumerate(self.active.items):
                rr = self._grid_rect(i, cols, gap, x0)
                if rr.bottom < content_top or rr.y > area.bottom:
                    continue

                is_active = (item.get("key") == self.active.active_key)
                hovered = rr.collidepoint(mouse)
                cell = rr.inflate(8, 8)
                if is_active:
                    pygame.draw.rect(surf, C.COL_ACCENT, cell, 2,
                                     border_radius=6)
                elif hovered:
                    pygame.draw.rect(surf, C.COL_PANEL_HDR, cell,
                                     border_radius=6)

                thumb = item.get("thumb")
                if thumb is not None:
                    surf.blit(thumb, rr.topleft)

                if hovered:
                    tooltip_text = item.get("label", "?")
                    tooltip_pos = mouse
        else:
            for i, item in enumerate(self.active.items):
                rr = self._row_rect(i)
                if rr.bottom < content_top or rr.y > area.bottom:
                    continue

                is_active = (item.get("key") == self.active.active_key)
                hovered = rr.collidepoint(mouse)
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

        if tooltip_text:
            self._draw_tooltip(surf, tooltip_text, tooltip_pos)

        # drag ghost
        if self.drag_thumb is not None:
            surf.blit(self.drag_thumb, self.drag_pos)

    def _draw_tooltip(self, surf, text, pos):
        font = ui.get_font(14)
        max_w = min(320, max(40, C.WINDOW_W - 20))
        text = _truncate(text, font, max_w)
        img = font.render(text, True, C.COL_TEXT)
        pad = 6
        w = img.get_width() + pad * 2
        h = img.get_height() + pad * 2
        x = pos[0] + 14
        y = pos[1] + 18
        if x + w > C.WINDOW_W:
            x = pos[0] - w - 14
        if y + h > C.WINDOW_H:
            y = pos[1] - h - 18
        x = max(2, min(x, C.WINDOW_W - w - 2))
        y = max(2, min(y, C.WINDOW_H - h - 2))

        rect = pygame.Rect(x, y, w, h)
        pygame.draw.rect(surf, (20, 20, 26), rect, border_radius=4)
        pygame.draw.rect(surf, C.COL_ACCENT, rect, 1, border_radius=4)
        surf.blit(img, (x + pad, y + pad))