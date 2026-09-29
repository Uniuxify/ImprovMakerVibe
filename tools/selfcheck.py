"""Headless self-check for the Scene Puppet core.

Builds a synthetic event log, verifies move interpolation and transitions via
`Runtime`, then renders a short MP4 through ffmpeg. Run with:

    python tools/selfcheck.py
"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

from app import config as C  # noqa: E402
from app.assets_lib import Assets  # noqa: E402
from app.sound import SoundManager  # noqa: E402
from app.recorder import EventLog  # noqa: E402
from app.player import Runtime  # noqa: E402
from app import exporter  # noqa: E402


def main():
    pygame.init()
    pygame.display.set_mode((64, 64))
    C.ensure_dirs()

    sm = SoundManager()
    assets = Assets(sm)
    assets.ensure_builtin_backgrounds()

    # create a small test sprite image
    hero_path = os.path.join(C.SPRITES_DIR, "hero.png")
    if not os.path.exists(hero_path):
        surf = pygame.Surface((120, 120), pygame.SRCALPHA)
        surf.fill((0, 0, 0, 0))
        pygame.draw.circle(surf, (60, 200, 90), (60, 60), 55)
        pygame.image.save(surf, hero_path)
    assets.load_image_file(hero_path)

    # build an event log
    log = EventLog()
    log.start_state = {
        "scenes": [
            {"name": "scene1", "background": "gradient_sky",
             "sprites": [{"name": "hero", "image": "hero",
                          "x": float(C.MARGIN + 100),
                          "y": float(C.MARGIN + 100)}]},
            {"name": "scene2", "background": "gradient_sunset",
             "sprites": [{"name": "hero", "image": "hero",
                          "x": float(C.MARGIN + 400),
                          "y": float(C.MARGIN + 300)}]},
        ]
    }
    # smooth move across 2 seconds (keyframes every 0.1 s)
    for i in range(21):
        t = i * 0.1
        log.events.append({
            "t": round(t, 3), "type": "move", "sprite": "hero",
            "x": C.MARGIN + 100 + i * 20, "y": C.MARGIN + 100 + i * 5,
        })
    log.events.append({"t": 2.5, "type": "pause", "transition": "fade",
                       "hold": 0.0, "scene": "scene2"})
    log.events.append({"t": 3.4, "type": "background",
                       "background": "gradient_night"})
    log.events.append({"t": 3.5, "type": "scale", "sprite": "hero",
                       "scale_x": 0.5, "scale_y": 2.0})
    log.duration = 4.0

    runtime = Runtime(log, assets)

    # --- verify interpolation -------------------------------------
    runtime.update_to(1.0)
    sp = runtime.active.sprite_by_name("hero")
    exp_x = C.MARGIN + 100 + 10 * 20
    ok_interp = abs(sp.x - exp_x) < 1.5
    print(f"[check] interp@1.0s x={sp.x:.1f} expected~{exp_x} "
          f"-> {'OK' if ok_interp else 'FAIL'}")

    # --- verify transition cover peaks ----------------------------
    runtime.update_to(2.5 + C.TRANSITION_DURATION / 2)
    cover, kind = runtime.transition_cover(2.5 + C.TRANSITION_DURATION / 2)
    ok_cover = cover > 0.9 and kind == "fade"
    print(f"[check] transition cover={cover:.2f} kind={kind} "
          f"-> {'OK' if ok_cover else 'FAIL'}")

    # --- verify scene switch at midpoint --------------------------
    runtime.update_to(2.5 + C.TRANSITION_DURATION / 2 + 0.01)
    ok_scene = runtime.active.name == "scene2"
    print(f"[check] scene@mid = {runtime.active.name} "
          f"-> {'OK' if ok_scene else 'FAIL'}")

    # --- verify background change ---------------------------------
    runtime.update_to(3.5)
    ok_bg = runtime.active.bg_key == "gradient_night"
    print(f"[check] background = {runtime.active.bg_key} "
          f"-> {'OK' if ok_bg else 'FAIL'}")

    # --- verify scaling -------------------------------------------
    runtime.update_to(3.6)
    hsp = runtime.active.sprite_by_name("hero")
    ok_scale = (abs(hsp.scale_x - 0.5) < 1e-3 and
                abs(hsp.scale_y - 2.0) < 1e-3 and
                hsp.w == max(1, int(round(hsp.orig_w * 0.5))) and
                hsp.h == max(1, int(round(hsp.orig_h * 2.0))))
    print(f"[check] scale x={hsp.scale_x} y={hsp.scale_y} "
          f"{hsp.w}x{hsp.h} -> {'OK' if ok_scale else 'FAIL'}")

    # --- verify flip ----------------------------------------------
    hsp.set_flip(True, False)
    ok_flip = hsp.flip_x is True and hsp.flip_y is False
    print(f"[check] flip H={hsp.flip_x} V={hsp.flip_y} -> {'OK' if ok_flip else 'FAIL'}")

    # --- verify pinned edge stays fixed while resizing -------------
    # simulate a left-handle resize: right edge (ax=220) must stay put
    log2 = EventLog()
    log2.start_state = {
        "scenes": [{"name": "scene1", "background": "gradient_sky",
                    "sprites": [{"name": "hero", "image": "hero",
                                 "x": 100.0, "y": 100.0,
                                 "scale_x": 1.0, "scale_y": 1.0}]}]
    }
    for i in range(11):
        t = round(i * 0.1, 3)
        sc = 1.0 - 0.5 * (i / 10.0)          # 1.0 -> 0.5
        w = round(120 * sc)
        log2.events.append({"t": t, "type": "move", "sprite": "hero",
                            "x": 220 - w, "y": 100.0})
        log2.events.append({"t": t, "type": "scale", "sprite": "hero",
                            "scale_x": sc, "scale_y": 1.0,
                            "ax": 220.0, "axs": "right"})
    log2.duration = 1.0
    rt2 = Runtime(log2, assets)
    worst = 0.0
    for i in range(21):
        rt2.update_to(i * 0.05)
        h = rt2.active.sprite_by_name("hero")
        worst = max(worst, abs((h.x + h.w) - 220.0))
    ok_pin = worst <= 1.0
    print(f"[check] pinned right edge drift={worst:.2f}px "
          f"-> {'OK' if ok_pin else 'FAIL'}")

    # --- pause edits (add/remove at midpoint) become visible on playback ---
    log3 = EventLog()
    log3.start_state = {
        "scenes": [
            {"name": "scene1", "background": "gradient_sky", "sprites": []},
            {"name": "scene2", "background": "gradient_sunset", "sprites": []},
        ]
    }
    log3.events.append({"t": 1.0, "type": "pause", "transition": "fade",
                        "duration": C.TRANSITION_DURATION, "scene": "scene2"})
    # sprite added while paused -> logged at the pause midpoint (1.4s)
    mid = 1.0 + C.TRANSITION_DURATION / 2.0
    log3.events.append({"t": mid, "type": "sprite_add", "sprite": "hero",
                        "image": "hero", "x": 150.0, "y": 160.0,
                        "scale_x": 1.0, "scale_y": 1.0})
    log3.duration = 2.0
    rt3 = Runtime(log3, assets)
    rt3.update_to(0.5)
    absent_before = rt3.active.sprite_by_name("hero") is None
    rt3.update_to(1.9)
    present_after = (rt3.active.name == "scene2"
                     and rt3.active.sprite_by_name("hero") is not None)
    ok_pause_add = absent_before and present_after
    print(f"[check] pause sprite_add: before={absent_before} "
          f"after={present_after} -> {'OK' if ok_pause_add else 'FAIL'}")

    # --- pause "hold": curtain stays closed for the configured time ---
    anim = C.TRANSITION_DURATION / 2.0
    hold = 5.0
    log4 = EventLog()
    log4.start_state = {
        "scenes": [{"name": "scene1", "background": "gradient_sky",
                    "sprites": []}]}
    log4.events.append({"t": 1.0, "type": "pause", "transition": "curtain",
                        "hold": hold, "scene": "scene1"})
    log4.duration = 1.0 + C.TRANSITION_DURATION + hold + 0.5
    rt4 = Runtime(log4, assets)
    rt4.update_to(1.0)
    closed_ok = True
    s = 1.0 + anim
    while s < 1.0 + anim + hold - 1e-6:
        cov, _ = rt4.transition_cover(s)
        if cov < 0.999:
            closed_ok = False
            break
        s += hold / 10.0
    mid_cover, _ = rt4.transition_cover(1.0 + anim + hold / 2.0)
    open_cover, _ = rt4.transition_cover(
        1.0 + C.TRANSITION_DURATION + hold + 0.01)
    ok_hold = closed_ok and mid_cover > 0.999 and open_cover < 0.01
    print(f"[check] pause hold={hold}s closed_throughout={closed_ok} "
          f"mid={mid_cover:.2f} after={open_cover:.2f} "
          f"-> {'OK' if ok_hold else 'FAIL'}")

    # --- export ----------------------------------------------------
    out = os.path.join(C.PROJECTS_DIR, "selftest.mp4")
    if not exporter.is_available():
        print("[check] ffmpeg not available -> SKIP export")
        return 0

    print("[check] exporting video...")
    exporter.export(log, assets, out)
    size = os.path.getsize(out) if os.path.exists(out) else 0
    print(f"[check] exported {out} ({size} bytes) "
          f"-> {'OK' if size > 2000 else 'FAIL'}")

    all_ok = (ok_interp and ok_cover and ok_scene and ok_bg and ok_scale
              and ok_flip and ok_pin and ok_pause_add and ok_hold
              and size > 2000)
    print("[result]", "ALL OK" if all_ok else "SOME CHECKS FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())