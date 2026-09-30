"""Headless focus test for the sprite rotation feature.

Exercises the engine rotate gesture (single sprite + group orbit), the
rotated hitbox / handle points, rotated resizing (correct edges, no
jitter), flip-button anchoring and the project save/load round-trip.
Run with:

    python tools/test_rotation.py
"""
import math
import os
import shutil
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

from app import config as C  # noqa: E402
from app import project_io  # noqa: E402
from app.engine import Engine  # noqa: E402
from app.player import Runtime  # noqa: E402
from app.sprite import Sprite, rotate_point  # noqa: E402


def _ensure_hero(eng):
    """Make sure the 120x120 hero asset exists and is loaded."""
    hero_path = os.path.join(C.SPRITES_DIR, "hero.png")
    if not os.path.exists(hero_path):
        surf = pygame.Surface((120, 120), pygame.SRCALPHA)
        surf.fill((0, 0, 0, 0))
        pygame.draw.circle(surf, (60, 200, 90), (60, 60), 55)
        pygame.image.save(surf, hero_path)
    if "hero" not in eng.assets.images:
        eng.assets.load_image_file(hero_path)
    return eng.assets.get_image("hero")


def _press(eng, wx, wy):
    sx, sy = eng.view.w2s(wx, wy)
    ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(int(sx), int(sy)),
                            button=1)
    eng.handle_event(ev, (int(sx), int(sy)))


def _motion(eng, wx, wy):
    sx, sy = eng.view.w2s(wx, wy)
    ev = pygame.event.Event(pygame.MOUSEMOTION, pos=(int(sx), int(sy)),
                            rel=(0, 0), buttons=(1, 0, 0))
    eng.handle_event(ev, (int(sx), int(sy)))


def _release(eng, wx, wy):
    sx, sy = eng.view.w2s(wx, wy)
    ev = pygame.event.Event(pygame.MOUSEBUTTONUP, pos=(int(sx), int(sy)),
                            button=1)
    eng.handle_event(ev, (int(sx), int(sy)))


def _report(name, checks):
    """checks: list of (label, ok). Prints one line, returns overall ok."""
    bad = [label for label, ok in checks if not ok]
    status = "OK" if not bad else f"FAIL ({', '.join(bad)})"
    print(f"[rot] {name}: {status}")
    return not bad


def test_single_rotation(eng):
    """Single sprite: drag near a corner turns it around its own centre,
    the position stays put, the gesture is recorded and replays."""
    hero = _ensure_hero(eng)
    wx, wy = eng.view.s2w(300, 400)
    sp = Sprite("rot_single", hero, wx, wy, image_key="hero")
    eng.stage.active.add_sprite(sp)
    eng.selected_sprites = [sp]
    eng.start_recording()

    cx, cy = sp.center
    corner = sp.handle_points()["bottom_right"]
    start = (corner[0] + 15.0, corner[1] + 15.0)   # outside handle, in rot zone
    _press(eng, *start)
    ok_started = eng.rotating is not None

    # advance the recording clock so the keyframes span real time
    eng.t = 0.5
    target = rotate_point(start[0], start[1], cx, cy, 90.0)
    _motion(eng, *target)
    ok_angle = abs(sp.angle - 90.0) < 2.0
    ok_pos = abs(sp.x - wx) < 1.0 and abs(sp.y - wy) < 1.0
    eng.t = 0.6
    _release(eng, *target)
    ok_ended = eng.rotating is None
    # render the rotated selection frame / handles (must not crash)
    eng._draw()
    eng.stop_recording()

    rot_events = [e for e in eng.recorder.log.events if e["type"] == "rotate"]
    ok_logged = len(rot_events) >= 2
    rt = Runtime(eng.recorder.log, eng.assets)
    rt.update_to(eng.recorder.log.duration)
    sp_rt = rt.active.sprite_by_name("rot_single")
    ok_playback = sp_rt is not None and abs(sp_rt.angle - 90.0) < 2.0

    eng.stage.active.remove_sprite(sp)
    eng.selected_sprites = []
    return _report("single rotation gesture", [
        ("gesture started", ok_started),
        ("angle ~90", ok_angle),
        ("position unchanged", ok_pos),
        ("gesture ended", ok_ended),
        ("rotate events logged", ok_logged),
        ("replays rotated", ok_playback),
    ])


def test_group_rotation(eng):
    """Group (2+): drag near the group frame corner turns every member
    around the group centre; members orbit it and their angles add up."""
    hero = _ensure_hero(eng)
    wx, wy = eng.view.s2w(300, 400)
    a = Sprite("grp_a", hero, wx, wy, image_key="hero")
    b = Sprite("grp_b", hero, wx + 200, wy, image_key="hero")
    eng.stage.active.add_sprite(a)
    eng.stage.active.add_sprite(b)
    eng.selected_sprites = [a, b]

    bx1, by1, bx2, by2 = eng._group_bounds([a, b])
    gc = ((bx1 + bx2) / 2.0, (by1 + by2) / 2.0)
    # group frame corner (padded by GROUP_BOX_PAD=20 at scale 1) + outward
    corner = (bx2 + 20.0, by2 + 20.0)
    start = (corner[0] + 15.0, corner[1] + 15.0)
    _press(eng, *start)
    ok_started = eng.rotating is not None and len(eng.rotating) == 2

    target = rotate_point(start[0], start[1], gc[0], gc[1], 90.0)
    _motion(eng, *target)
    ok_angles = (abs(a.angle - 90.0) < 2.0 and abs(b.angle - 90.0) < 2.0)
    # render rotated members + group AABB frame (must not crash)
    eng._draw()

    ca0 = (wx + 60.0, wy + 60.0)
    cb0 = (wx + 200.0 + 60.0, wy + 60.0)
    ca_exp = rotate_point(ca0[0], ca0[1], gc[0], gc[1], 90.0)
    cb_exp = rotate_point(cb0[0], cb0[1], gc[0], gc[1], 90.0)
    ok_orbit = (abs(a.center[0] - ca_exp[0]) < 1.5 and
                abs(a.center[1] - ca_exp[1]) < 1.5 and
                abs(b.center[0] - cb_exp[0]) < 1.5 and
                abs(b.center[1] - cb_exp[1]) < 1.5)
    _release(eng, *target)
    ok_ended = eng.rotating is None

    eng.stage.active.remove_sprite(a)
    eng.stage.active.remove_sprite(b)
    eng.selected_sprites = []
    return _report("group rotation gesture", [
        ("group gesture started", ok_started),
        ("both angles ~90", ok_angles),
        ("centres orbit group centre", ok_orbit),
        ("gesture ended", ok_ended),
    ])


def test_rotated_resize(eng):
    """Resizing a rotated object follows the VISIBLE edges: the pinned
    corner stays where it is on screen, the dragged edge follows the mouse."""
    hero = _ensure_hero(eng)

    # -- 180 degrees: grabbing the east handle and dragging east must grow
    #    the east edge, not the west one
    x0, y0 = (int(v) for v in eng.view.s2w(300, 400))
    sp = Sprite("rs180", hero, x0, y0, image_key="hero", angle=180.0)
    eng.stage.active.add_sprite(sp)
    eng.selected_sprites = [sp]
    east = sp.handle_points()["left"]          # rotated: "left" sits east
    _press(eng, *east)
    ok_grab = eng.resize_handle == "left"
    _motion(eng, east[0] + 40.0, east[1])
    # footprint at 180 deg is still [x, x+w] in x: west (anchor) fixed,
    # east grew by the drag amount
    ok_180 = (abs(sp.x - x0) < 2.0 and
              abs(sp.x + sp.w - (x0 + 120.0 + 40.0)) < 2.0)
    _release(eng, east[0] + 40.0, east[1])
    ok_ended1 = eng.resizing is None
    eng.stage.active.remove_sprite(sp)

    # -- 90 degrees: non-square sprite, the "right" handle points NORTH;
    #    the south edge is pinned, the north edge must follow the mouse
    surf = pygame.Surface((200, 100), pygame.SRCALPHA)
    surf.fill((200, 60, 60, 255))
    sp2 = Sprite("rs90", surf, x0, y0, angle=90.0)
    eng.stage.active.add_sprite(sp2)
    eng.selected_sprites = [sp2]
    north = sp2.handle_points()["right"]
    a0 = rotate_point(x0, y0 + 50.0, *sp2.center, 90.0)   # south anchor
    _press(eng, *north)
    ok_grab2 = eng.resize_handle == "right"
    target = (north[0], north[1] - 30.0)                  # drag north
    _motion(eng, *target)
    anchor_now = rotate_point(sp2.x, sp2.y + sp2.h / 2.0, *sp2.center, 90.0)
    dragged = rotate_point(sp2.x + sp2.w, sp2.y + sp2.h / 2.0,
                           *sp2.center, 90.0)
    ok_90 = (abs(anchor_now[0] - a0[0]) < 2.0 and
             abs(anchor_now[1] - a0[1]) < 2.0 and
             abs(dragged[0] - target[0]) < 2.0 and
             abs(dragged[1] - target[1]) < 2.0)
    _release(eng, *target)
    ok_ended2 = eng.resizing is None
    eng.stage.active.remove_sprite(sp2)

    # -- 0 degrees regression: dragging bottom-right moves that corner only
    sp3 = Sprite("rs0", hero, x0, y0, image_key="hero", angle=0.0)
    eng.stage.active.add_sprite(sp3)
    eng.selected_sprites = [sp3]
    br = sp3.handle_points()["bottom_right"]
    _press(eng, *br)
    ok_grab3 = eng.resize_handle == "bottom_right"
    t3 = (br[0] + 30.0, br[1] + 20.0)
    _motion(eng, *t3)
    ok_0 = (abs(sp3.x - x0) < 2.0 and abs(sp3.y - y0) < 2.0 and
            abs(sp3.w - 150.0) < 2.0 and abs(sp3.h - 140.0) < 2.0)
    _release(eng, *t3)
    eng.stage.active.remove_sprite(sp3)
    eng.selected_sprites = []
    return _report("rotated resize", [
        ("180 deg handle grabbed", ok_grab),
        ("180 deg east drag grows east", ok_180),
        ("180 deg gesture ended", ok_ended1),
        ("90 deg handle grabbed", ok_grab2),
        ("90 deg anchor fixed + edge follows mouse", ok_90),
        ("90 deg gesture ended", ok_ended2),
        ("0 deg regression: corner drag", ok_0),
        ("0 deg handle grabbed", ok_grab3),
    ])


def test_resize_no_jitter(eng):
    """Resizing a rotated object must not jitter: the new size and the
    anchor are derived from the gesture snapshot + current mouse only, so
    repeated motion events at the SAME point never change them."""
    surf = pygame.Surface((200, 100), pygame.SRCALPHA)
    surf.fill((60, 120, 200, 255))
    x0, y0 = (int(v) for v in eng.view.s2w(300, 400))
    sp = Sprite("jit", surf, x0, y0, angle=45.0)
    eng.stage.active.add_sprite(sp)
    eng.selected_sprites = [sp]
    corner = sp.handle_points()["bottom_right"]
    anchor0 = sp.handle_points()["top_left"]          # pinned opposite corner
    target = (corner[0] + 40.0, corner[1] + 15.0)
    _press(eng, *corner)
    ws, hs, anchors = [], [], []
    held = []          # (w, h, anchor) samples while the mouse is held
    steps = 6
    for i in range(1, steps + 1):
        t = i / steps
        _motion(eng, corner[0] + (target[0] - corner[0]) * t,
                corner[1] + (target[1] - corner[1]) * t)
        ws.append(sp.w)
        hs.append(sp.h)
        anchors.append(sp.handle_points()["top_left"])
    # hold: same mouse point, several extra motion events
    for _ in range(4):
        _motion(eng, *target)
        ws.append(sp.w)
        hs.append(sp.h)
        anchors.append(sp.handle_points()["top_left"])
        held.append((sp.w, sp.h, sp.handle_points()["top_left"]))
    _release(eng, *target)
    # stability is only meaningful while the mouse does not move: repeated
    # motion events at the same point must not change the size at all
    held_w = [s[0] for s in held]
    held_h = [s[1] for s in held]
    ok_size = (max(held_w) - min(held_w) <= 1.0 and
               max(held_h) - min(held_h) <= 1.0)
    drift = max(math.hypot(p[0] - anchor0[0], p[1] - anchor0[1])
                for p in anchors)
    ok_anchor = drift <= 2.0
    ok_growth = ws[-1] > 200      # the gesture actually resized the sprite
    eng.stage.active.remove_sprite(sp)
    eng.selected_sprites = []
    return _report("rotated resize anti-jitter (45 deg)", [
        ("size stable at a held point", ok_size),
        ("anchor does not drift", ok_anchor),
        ("gesture resized the sprite", ok_growth),
    ])


def test_flip_buttons_follow_bottom(eng):
    """Flip H/V buttons are anchored to the sprite's CURRENT bottom edge
    (rotated), not to the angle-0 AABB."""
    surf = pygame.Surface((200, 100), pygame.SRCALPHA)
    surf.fill((60, 200, 120, 255))
    x0, y0 = (int(v) for v in eng.view.s2w(300, 400))
    sp = Sprite("btns", surf, x0, y0, angle=90.0)
    eng.stage.active.add_sprite(sp)
    eng.selected_sprites = [sp]

    # expected: under the rotated bottom-edge midpoint
    bx, by = sp.handle_points()["bottom"]
    esx, esy = eng.view.w2s(bx, by)
    btn_h, btn_v = eng._flip_buttons(sp)
    mid_x = (btn_h.left + btn_v.right) / 2.0
    ok_pos = abs(mid_x - esx) <= 2.0 and abs(btn_h.centery - (esy + 19)) <= 2.0

    # at 90 deg the local bottom sits on the RIGHT side, far from the
    # angle-0 AABB bottom position -> the buttons must have moved
    flat = Sprite("btns0", surf, x0, y0)
    a_sx, a_sy = eng.view.w2s(*flat.handle_points()["bottom"])
    r_sx, r_sy = eng.view.w2s(*sp.handle_points()["bottom"])
    moved = math.hypot(r_sx - a_sx, r_sy - a_sy) > 20.0

    # clicking the button still toggles the flip
    cx, cy = btn_h.center
    ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(int(cx), int(cy)),
                            button=1)
    eng.handle_event(ev, (int(cx), int(cy)))
    ok_click = sp.flip_x is True
    eng.stage.active.remove_sprite(sp)
    eng.selected_sprites = []
    return _report("flip buttons follow rotated bottom edge", [
        ("anchored under rotated bottom", ok_pos),
        ("moves with the rotation", moved),
        ("button click toggles flip", ok_click),
    ])


def test_project_roundtrip(eng):
    """angle survives save_project -> load_project."""
    hero = _ensure_hero(eng)
    wx, wy = eng.view.s2w(300, 400)
    sp = Sprite("rot_saved", hero, wx, wy, image_key="hero", angle=37.5)
    eng.stage.active.add_sprite(sp)
    tmp = os.path.join(C.PROJECTS_DIR, "rot_roundtrip")
    path = os.path.join(tmp, "project.json")
    try:
        project_io.save_project(path, eng.stage, eng.recorder.log,
                                eng.assets, eng.sm)
        stage2, _log2 = project_io.load_project(path, eng.assets, eng.sm)
        sp2 = stage2.active.sprite_by_name("rot_saved")
        ok = sp2 is not None and abs(sp2.angle - 37.5) < 1e-6
    finally:
        eng.stage.active.remove_sprite(sp)
        shutil.rmtree(tmp, ignore_errors=True)
    return _report("project round-trip", [("angle preserved", ok)])


def test_contains_and_handles():
    """Rotated hitbox matches the visible image; handles rotate too."""
    surf = pygame.Surface((200, 100), pygame.SRCALPHA)
    surf.fill((255, 0, 0, 255))
    sp = Sprite("math", surf, 100, 100, angle=90.0)
    # rotated footprint: 100 wide x 200 tall centred on (200, 150)
    ok_above = sp.contains(200, 60)         # inside rotated, outside AABB
    ok_outside = not sp.contains(110, 110)  # inside AABB, outside rotated
    tl = sp.handle_points()["top_left"]
    ok_handles = abs(tl[0] - 150.0) < 1.0 and abs(tl[1] - 250.0) < 1.0
    sp0 = Sprite("math0", surf, 100, 100)   # angle 0 -> plain AABB
    ok_ident = sp0.contains(110, 110) and not sp0.contains(200, 60)
    return _report("contains()/handle_points()", [
        ("point in rotated box", ok_above),
        ("point outside rotated box", ok_outside),
        ("handles rotated", ok_handles),
        ("angle=0 identity", ok_ident),
    ])


def main():
    pygame.init()
    eng = Engine()
    eng.panels.visible = False   # keep synthetic clicks off the panel area
    results = [
        test_contains_and_handles(),
        test_single_rotation(eng),
        test_group_rotation(eng),
        test_rotated_resize(eng),
        test_resize_no_jitter(eng),
        test_flip_buttons_follow_bottom(eng),
        test_project_roundtrip(eng),
    ]
    pygame.quit()
    print("[rot]", "ALL OK" if all(results) else "SOME CHECKS FAILED")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
