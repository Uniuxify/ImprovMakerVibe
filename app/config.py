"""Global configuration for Scene Puppet."""
import os
import shutil

# --- Window / stage geometry ---
FRAME_W = 1280           # visible scene width
FRAME_H = 720            # visible scene height
MARGIN = 200             # buffer zone (offscreen) on every side of the frame
CANVAS_W = FRAME_W + MARGIN * 2
CANVAS_H = FRAME_H + MARGIN * 2

UI_TOP_H = 48            # top toolbar height
STATUS_H = 26            # bottom status bar height
PEEK = 90                # how much buffer zone is shown around the frame
PANEL_W = 230            # slide-out panel width

STAGE_W = FRAME_W + PEEK * 2
STAGE_H = FRAME_H + PEEK * 2
WINDOW_W = STAGE_W + PANEL_W
WINDOW_H = UI_TOP_H + STAGE_H + STATUS_H

FPS = 30

# --- Colors ---
COL_BG = (24, 24, 30)          # app background
COL_PANEL = (40, 42, 52)
COL_PANEL_HDR = (54, 57, 70)
COL_BUTTON = (60, 64, 80)
COL_BUTTON_HOVER = (82, 88, 110)
COL_TEXT = (235, 235, 240)
COL_TEXT_DIM = (150, 152, 160)
COL_ACCENT = (90, 160, 220)
COL_RECORD = (210, 70, 70)
COL_BUTTON_DISABLED = (44, 46, 56)
COL_TEXT_DISABLED = (108, 110, 120)
COL_FRAME = (255, 255, 255)
COL_BUFFER = (45, 45, 55)

# --- Paths ---
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(ROOT, "assets")
SPRITES_DIR = os.path.join(ASSETS_DIR, "sprites")
SOUNDS_DIR = os.path.join(ASSETS_DIR, "sounds")
BACKGROUNDS_DIR = os.path.join(ASSETS_DIR, "backgrounds")
PROJECTS_DIR = os.path.join(ROOT, "projects")
BUILTIN_DIR = os.path.join(ASSETS_DIR, "builtin")
RECORDINGS_DIR = os.path.join(ROOT, "recordings")

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp")
SOUND_EXTS = (".wav", ".ogg", ".mp3")

# --- Audio ---
SAMPLE_RATE = 44100
MIC_CHANNELS = 1
MIC_BLOCKSIZE = 1024

# --- Export ---
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"
EXPORT_CRF = 23
EXPORT_PRESET = "medium"

# --- Transitions ---
TRANSITION_DURATION = 0.8       # seconds
TRANSITION_KINDS = ("curtain", "fade", "wipe")

# --- Interpolation ---
TRACK_LERP_MAX_GAP = 0.1

def ensure_dirs():
    """Create all asset/project directories if they are missing."""
    for d in (ASSETS_DIR, SPRITES_DIR, SOUNDS_DIR, BACKGROUNDS_DIR,
              PROJECTS_DIR, BUILTIN_DIR, RECORDINGS_DIR):
        os.makedirs(d, exist_ok=True)


def unique_path(directory, filename):
    """Return a path inside `directory` for `filename` that does not exist
    yet, appending a numeric suffix when necessary."""
    base, ext = os.path.splitext(filename)
    candidate = filename
    i = 1
    while os.path.exists(os.path.join(directory, candidate)):
        candidate = f"{base}_{i}{ext}"
        i += 1
    return os.path.join(directory, candidate)


def import_into(src, dest_dir):
    """Copy `src` into `dest_dir`, creating a unique name if needed, and
    return the destination path. If `src` already lives directly in
    `dest_dir`, it is returned unchanged (avoids duplicate copies)."""
    dest_dir = os.path.abspath(dest_dir)
    src = os.path.abspath(src)
    if os.path.dirname(src) == dest_dir:
        return src
    dest = unique_path(dest_dir, os.path.basename(src))
    shutil.copy2(src, dest)
    return dest
