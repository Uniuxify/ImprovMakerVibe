"""Headless smoke test: build the Engine, draw a frame, exercise a few
button actions, then quit. Ensures the UI layer has no import/runtime errors.

Run with:  python tools/smoke_gui.py
"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

from app.engine import Engine  # noqa: E402


def main():
    eng = Engine()
    # draw a frame in EDIT mode
    eng._draw()
    assert eng.mode == "EDIT"

    # start recording, move a sprite via the recorder, pause, resume, stop
    eng.start_recording()
    assert eng.mode == "RECORD"

    # add a sprite from the built-in sprite library path (if any)
    from app.sprite import Sprite
    from app import config as C
    if eng.assets.images:
        key = next(iter(eng.assets.images))
        sp = Sprite(key, eng.assets.get_image(key), C.MARGIN + 50,
                    C.MARGIN + 50, image_key=key)
        eng.stage.active.add_sprite(sp)
        eng.recorder.log_sprite_add(eng.t, sp)

    eng.t = 1.0
    eng.on_pause()
    # force-finish the pause/resume cycle
    eng.mode = "PAUSED"
    eng.on_pause()
    eng.update(1.0)
    assert eng.mode == "RECORD", eng.mode

    eng.stop_recording()
    assert eng.mode == "EDIT"
    assert eng.recorder.log.events, "no events recorded"

    # playback should start and complete without errors
    eng.start_playback()
    assert eng.mode == "PLAY"
    for _ in range(200):
        done = eng.player.update(0.05)
        if done:
            break
    eng.player.stop()
    eng.mode = "EDIT"
    eng._draw()

    # playback can be stopped early via the Play button (toggle)
    eng.start_playback()
    assert eng.mode == "PLAY"
    # status bar reflects moving playback time (current/total)
    duration = eng.player.runtime.duration
    eng.player.t = min(1.5, duration)
    eng._draw()  # must render the current/total time without errors
    assert eng.player.t > 0.0
    eng._draw()
    # during playback only the Play/Stop-playing button stays enabled
    assert eng.buttons["play"].label == "Stop playing"
    assert eng.buttons["play"].enabled is True
    for k in ("record", "pause", "export", "save", "load", "resolution",
              "add_sprite", "add_sound", "add_bg", "panels"):
        assert eng.buttons[k].enabled is False, k
    eng.on_button("play")  # stop playback
    assert eng.mode == "EDIT"
    eng._draw()
    assert eng.buttons["play"].label == "Play"
    # back in EDIT mode all buttons are enabled again
    for k in eng.buttons:
        assert eng.buttons[k].enabled is True, k
    # recording button reads "Stop Recording" while recording
    eng.start_recording()
    eng._draw()
    assert eng.buttons["record"].label == "Stop Recording"
    eng.stop_recording()
    eng._draw()
    assert eng.buttons["record"].label == "Record"

    # pause (during recording) disables everything except Stop Recording and
    # Resume, shows "Stop Recording", and draws no transition cover
    eng.start_recording()
    assert eng._current_cover() == 0.0
    eng.on_pause()  # -> PAUSING
    eng.mode = "PAUSED"
    eng._draw()
    assert eng.buttons["record"].label == "Stop Recording"
    assert eng.buttons["pause"].label == "Resume"
    assert eng.buttons["record"].enabled is True
    assert eng.buttons["pause"].enabled is True
    for k in ("play", "export", "save", "load", "resolution",
              "add_sprite", "add_sound", "add_bg", "panels"):
        assert eng.buttons[k].enabled is False, k
    # no transition animation while authoring
    assert eng._current_cover() == 0.0

    # edits made while paused are logged at the pause midpoint so they appear
    # during playback (which is what the player applies at the transition mid)
    from app.sprite import Sprite
    from app import config as C
    mid = eng.pause_start_t + C.TRANSITION_DURATION / 2.0
    n_before = len(eng.recorder.log.events)
    key = next(iter(eng.assets.images)) if eng.assets.images else None
    if key is not None:
        sp = Sprite("paused_add", eng.assets.get_image(key),
                    C.MARGIN + 60, C.MARGIN + 60, image_key=key)
        eng.stage.active.add_sprite(sp)
        eng.recorder.log_sprite_add(eng._edit_t(), sp)
        added = eng.recorder.log.events[-1]
        assert added["type"] == "sprite_add"
        assert abs(added["t"] - mid) < 1e-6, (added["t"], mid)
    assert eng._edit_t() == mid

    eng.stop_recording()
    assert eng.mode == "EDIT"
    eng._draw()
    assert eng._current_cover() == 0.0

    # test new features:
    # 1. resolution change
    eng.set_scene_resolution(1920, 1080)
    assert eng.frame_w == 1920 and eng.frame_h == 1080

    # 2. zoom
    eng.view.zoom(1.2, 500, 400)
    assert eng.view.scale > 1.0

    # 2b. middle-mouse panning of the view
    fx0, fy0 = eng.view.frame_x, eng.view.frame_y
    down = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=2,
                              pos=(400, 300))
    eng.handle_event(down, (400, 300))
    assert eng.panning is True
    move = pygame.event.Event(pygame.MOUSEMOTION, pos=(450, 320),
                              rel=(50, 20), buttons=(0, 0, 1))
    eng.handle_event(move, (450, 320))
    assert (eng.view.frame_x, eng.view.frame_y) == (fx0 + 50, fy0 + 20)
    up = pygame.event.Event(pygame.MOUSEBUTTONUP, button=2, pos=(450, 320))
    eng.handle_event(up, (450, 320))
    assert eng.panning is False
    # reset so later checks are unaffected
    eng.view.frame_x, eng.view.frame_y = fx0, fy0

    # 3. sprite flip and handles
    if eng.stage.active.sprites:
        sp = eng.stage.active.sprites[0]
        sp.toggle_flip_h()
        assert sp.flip_x is True
        sp.toggle_flip_v()
        assert sp.flip_y is True
        pts = sp.handle_points()
        assert "top_left" in pts and "bottom_right" in pts

        # 4. selection and copy/paste
        eng.selected_sprites = [sp]
        eng.clipboard = [sp.to_dict()]
        eng._paste_clipboard()
        assert len(eng.stage.active.sprites) >= 2

        # 5. z-order
        sp2 = eng.stage.active.sprites[-1]
        eng.stage.active.move_sprite_down(sp2)
        eng.stage.active.move_sprite_up(sp2)

    # 6. asset folders: auto-load on startup + copy-on-add
    import os as _os
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tmp_png = tf.name
    try:
        # copy-on-add places a copy inside the asset folder
        dest = C.import_into(tmp_png, C.BACKGROUNDS_DIR)
        assert _os.path.dirname(_os.path.abspath(dest)) == \
            _os.path.abspath(C.BACKGROUNDS_DIR)
        assert _os.path.exists(dest)
        # importing again from the same folder must not duplicate
        again = C.import_into(dest, C.BACKGROUNDS_DIR)
        assert _os.path.abspath(again) == _os.path.abspath(dest)
    finally:
        if _os.path.exists(tmp_png):
            _os.remove(tmp_png)
        if _os.path.exists(dest):
            _os.remove(dest)

    # auto-load: every file physically present in an asset folder is loaded
    from app import config as C2
    from app.assets_lib import Assets
    from app.sound import SoundManager
    sm2 = SoundManager()
    assets2 = Assets(sm2)
    assets2.load_images_from(C2.SPRITES_DIR)
    assets2.load_backgrounds_from(C2.BACKGROUNDS_DIR)
    sm2.load_all_from(C2.SOUNDS_DIR)
    for f in _os.listdir(C2.BACKGROUNDS_DIR):
        if f.lower().endswith(C2.IMAGE_EXTS):
            key = _os.path.splitext(f)[0]
            assert key in assets2.backgrounds, key

    # right panel resize + adaptive icon grid
    from app import config as C
    assert eng.panels._grid_columns(C.PANEL_W) == 3
    assert eng.panels._grid_columns(C.PANEL_W * 2) == 6
    assert eng.panels._grid_gap(3, C.PANEL_W) >= C.PANEL_GRID_MIN_GAP
    assert eng.panels._grid_gap(6, C.PANEL_W * 2) >= C.PANEL_GRID_MIN_GAP

    assert isinstance(eng.settings["fullscreen"], bool)
    assert eng.window_w >= C.MIN_WINDOW_W
    assert eng.window_h >= C.MIN_WINDOW_H

    old_width = eng.panel_width
    new_width = min(eng.panels.max_width, old_width + 120)
    eng._set_panel_width(new_width)
    assert eng.panel_width == new_width
    assert eng.stage_w == C.WINDOW_W
    assert eng.panels.area.x == C.WINDOW_W - eng.panel_width
    eng._draw()
    eng._set_panel_width(old_width)
    assert eng.panel_width == old_width
    assert eng.stage_w == C.WINDOW_W

    # live panel drag: the panel overlays the stage; the stage width stays fixed
    grab = eng.panels._resize_rect().center
    down = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=grab)
    eng.handle_event(down, grab)
    for dx in (-20, -40, 20, 0):
        pos = (grab[0] + dx, grab[1])
        move = pygame.event.Event(pygame.MOUSEMOTION, pos=pos,
                                  rel=(dx, 0), buttons=(1, 0, 0))
        eng.handle_event(move, pos)
        assert eng.stage_w == C.WINDOW_W
        assert eng.panels.width == eng.panel_width
        assert eng.panels.area.right == C.WINDOW_W
        assert eng.panels.area.x == C.WINDOW_W - eng.panel_width
    eng.panels._resizing = False
    eng._set_panel_width(old_width)
    assert eng.panels.area.x == C.WINDOW_W - eng.panel_width
    eng._draw()

    old_window = (eng.window_w, eng.window_h)
    eng._on_window_resize(2400, 1200)
    assert eng.window_w == 2400 and eng.window_h == 1200
    assert eng.stage_h == C.stage_height(1200)
    assert eng.view.stage_h == eng.stage_h
    assert eng.stage_w == C.WINDOW_W
    assert eng.panels.area.right == C.WINDOW_W
    assert eng.panels.area.bottom == C.WINDOW_H - C.STATUS_H
    assert eng.panels.area.x == C.WINDOW_W - eng.panel_width
    eng._draw()

    eng._on_window_resize(*old_window)
    assert eng.stage_w == C.WINDOW_W
    assert eng.panels.area.right == C.WINDOW_W
    assert eng.panels.area.bottom == C.WINDOW_H - C.STATUS_H
    assert eng.panels.area.x == C.WINDOW_W - eng.panel_width
    eng._draw()

    eng._draw()
    pygame.quit()
    print("[smoke] events:", len(eng.recorder.log.events))
    print("[smoke] GUI OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())