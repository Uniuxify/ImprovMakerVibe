"""Small immediate-mode UI widgets: buttons, labels and text input.

File dialogs open the native Windows Explorer dialogs (via the Win32
`comdlg32` / `shell32` API through `ctypes`, which needs no third-party
dependency). On non-Windows systems, or if the native call fails, the
built-in pygame `FileBrowser` is used as a fallback so the app still works.
"""
import os
import sys

import pygame

from . import config as C

_IS_WINDOWS = sys.platform.startswith("win")

_font_cache = {}


def get_font(size=18, bold=False):
    key = (size, bold)
    if key not in _font_cache:
        _font_cache[key] = pygame.font.SysFont("segoeui,arial", size, bold=bold)
    return _font_cache[key]


def _button_font(label, rect):
    max_w = max(1, rect.width - 12)
    max_h = max(1, rect.height - 6)
    for size in (18, 16, 14, 12, 10):
        font = get_font(size, bold=True)
        if font.size(label)[0] <= max_w and font.get_height() <= max_h:
            return font
    return get_font(10, bold=True)


def _button_text(label, font, rect):
    max_w = max(1, rect.width - 12)
    if font.size(label)[0] <= max_w:
        return label
    ellipsis = "..."
    while label and font.size(label + ellipsis)[0] > max_w:
        label = label[:-1]
    return (label + ellipsis) if label else ellipsis


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
            font = _button_font(self.label, self.rect)
            txt = font.render(_button_text(self.label, font, self.rect),
                              True, C.COL_TEXT_DISABLED)
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
        font = _button_font(self.label, self.rect)
        txt = font.render(_button_text(self.label, font, self.rect),
                          True, self.text_color)
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


# ---- native Windows Explorer dialogs (ctypes) ------------------------
def _build_filter(exts):
    """Build a Win32 filter string: "Label\\0*.png;*.jpg\\0...\\0\\0"."""
    if not exts:
        return "All files\0*.*\0\0"
    patterns = ";".join("*" + e for e in exts)
    label = " / ".join(e.lstrip(".").upper() for e in exts)
    return f"{label}\0{patterns}\0All files\0*.*\0\0"


def _win_file_dialog(title, exts, initialdir, initialfile, save,
                     multiple=False):
    """Open a native Open/Save dialog. Returns the chosen path (str), a
    list of paths when `multiple`, or None if the dialog was cancelled.
    Raises on API failure so the caller can fall back."""
    import ctypes
    from ctypes import wintypes

    COMDLG = ctypes.WinDLL("comdlg32", use_last_error=True)

    class OPENFILENAMEW(ctypes.Structure):
        _fields_ = [
            ("lStructSize", wintypes.DWORD),
            ("hwndOwner", wintypes.HWND),
            ("hInstance", wintypes.HINSTANCE),
            ("lpstrFilter", wintypes.LPCWSTR),
            ("lpstrCustomFilter", wintypes.LPWSTR),
            ("nMaxCustFilter", wintypes.DWORD),
            ("nFilterIndex", wintypes.DWORD),
            ("lpstrFile", wintypes.LPWSTR),
            ("nMaxFile", wintypes.DWORD),
            ("lpstrFileTitle", wintypes.LPWSTR),
            ("nMaxFileTitle", wintypes.DWORD),
            ("lpstrInitialDir", wintypes.LPCWSTR),
            ("lpstrTitle", wintypes.LPCWSTR),
            ("Flags", wintypes.DWORD),
            ("nFileOffset", wintypes.WORD),
            ("nFileExtension", wintypes.WORD),
            ("lpstrDefExt", wintypes.LPCWSTR),
            ("lCustData", wintypes.LPARAM),
            ("lpfnHook", ctypes.c_void_p),
            ("lpTemplateName", wintypes.LPCWSTR),
            ("pvReserved", ctypes.c_void_p),
            ("dwReserved", wintypes.DWORD),
            ("FlagsEx", wintypes.DWORD),
        ]

    OFN_EXPLORER = 0x00080000
    OFN_FILEMUSTEXIST = 0x00001000
    OFN_PATHMUSTEXIST = 0x00000800
    OFN_HIDEREADONLY = 0x00000004
    OFN_NOCHANGEDIR = 0x00000008
    OFN_OVERWRITEPROMPT = 0x00000002
    OFN_ALLOWMULTISELECT = 0x00000200

    buf_len = 32768
    buffer = ctypes.create_unicode_buffer(buf_len)
    if initialfile:
        buffer.value = initialfile

    ofn = OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
    ofn.hwndOwner = None
    ofn.lpstrFilter = _build_filter(exts)
    ofn.lpstrFile = ctypes.cast(buffer, wintypes.LPWSTR)
    ofn.nMaxFile = buf_len
    ofn.lpstrTitle = title
    if initialdir and os.path.isdir(initialdir):
        ofn.lpstrInitialDir = initialdir

    flags = OFN_EXPLORER | OFN_NOCHANGEDIR | OFN_HIDEREADONLY
    if save:
        flags |= OFN_OVERWRITEPROMPT
    else:
        flags |= OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST
        if multiple:
            flags |= OFN_ALLOWMULTISELECT
    ofn.Flags = flags

    if save:
        ok = COMDLG.GetSaveFileNameW(ctypes.byref(ofn))
    else:
        ok = COMDLG.GetOpenFileNameW(ctypes.byref(ofn))
    if not ok:
        return None  # cancelled

    raw = buffer.value
    if not multiple:
        return raw

    # For multiselect the buffer is "dir\0file1\0file2\0...\0\0".
    parts = raw.split("\0")
    parts = [p for p in parts if p != ""]
    if len(parts) <= 1:
        return parts if parts else []
    folder = parts[0]
    return [os.path.join(folder, name) for name in parts[1:]]


def _win_directory_dialog(title, initialdir):
    """Open the native Windows folder picker. Returns the path or None."""
    import ctypes
    from ctypes import wintypes

    SHELL = ctypes.WinDLL("shell32", use_last_error=True)
    OLE = ctypes.WinDLL("ole32", use_last_error=True)

    class BROWSEINFOW(ctypes.Structure):
        _fields_ = [
            ("hwndOwner", wintypes.HWND),
            ("pidlRoot", ctypes.c_void_p),
            ("pszDisplayName", wintypes.LPWSTR),
            ("lpszTitle", wintypes.LPCWSTR),
            ("ulFlags", ctypes.c_uint),
            ("lpfn", ctypes.c_void_p),
            ("lParam", wintypes.LPARAM),
            ("iImage", ctypes.c_int),
        ]

    BIF_RETURNONLYFSDIRS = 0x00000001
    BIF_NEWDIALOGSTYLE = 0x00000040
    BIF_EDITBOX = 0x00000010

    display = ctypes.create_unicode_buffer(260)
    bi = BROWSEINFOW()
    bi.hwndOwner = None
    bi.pszDisplayName = ctypes.cast(display, wintypes.LPWSTR)
    bi.lpszTitle = title
    bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE | BIF_EDITBOX

    pidl = SHELL.SHBrowseForFolderW(ctypes.byref(bi))
    if not pidl:
        return None  # cancelled

    path_buf = ctypes.create_unicode_buffer(260)
    SHELL.SHGetPathFromIDListW(ctypes.c_void_p(pidl), path_buf)
    OLE.CoTaskMemFree(ctypes.c_void_p(pidl))
    result = path_buf.value
    return result if result else ""


# ---- convenience functions (used by the engine) ----------------------
def open_files(screen, clock, title, exts=None, initialdir=None):
    if _IS_WINDOWS:
        try:
            result = _win_file_dialog(title, exts, initialdir, "",
                                      save=False, multiple=True)
            if result is not None:
                return result
            return []
        except Exception:
            pass
    from .filebrowser import FileBrowser
    fb = FileBrowser(screen, clock, title, mode="open", exts=exts,
                     initialdir=initialdir, multiple=True)
    return fb.run() or []


def open_file(screen, clock, title, exts=None, initialdir=None):
    if _IS_WINDOWS:
        try:
            result = _win_file_dialog(title, exts, initialdir, "",
                                      save=False, multiple=False)
            if result is not None:
                return result
            return ""
        except Exception:
            pass
    from .filebrowser import FileBrowser
    fb = FileBrowser(screen, clock, title, mode="open", exts=exts,
                     initialdir=initialdir, multiple=False)
    return fb.run()


def save_file(screen, clock, title, exts=None, initialdir=None,
              initialfile=""):
    if _IS_WINDOWS:
        try:
            result = _win_file_dialog(title, exts, initialdir, initialfile,
                                      save=True, multiple=False)
            if result is not None:
                return result
            return ""
        except Exception:
            pass
    from .filebrowser import FileBrowser
    fb = FileBrowser(screen, clock, title, mode="save", exts=exts,
                     initialdir=initialdir, initialfile=initialfile)
    return fb.run()


def choose_directory(screen, clock, title, initialdir=None):
    if _IS_WINDOWS:
        try:
            result = _win_directory_dialog(title, initialdir)
            if result is not None:
                return result
            return ""
        except Exception:
            pass
    from .filebrowser import FileBrowser
    fb = FileBrowser(screen, clock, title, mode="directory",
                     initialdir=initialdir)
    return fb.run()