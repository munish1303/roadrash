#!/usr/bin/env python3
"""
road_rash_pygame.py - Full arcade-style Road Rash (improved)
"""
import os, pygame, time, random
from collections import deque


LANES = 3
TRACK_LENGTH = 220.0
TICK = 0.14
MAX_SPEED = 14.0
ACCEL = 3.0
BRAKE = -5.0
ATTACK_RANGE = 3.5
ATTACK_DAMAGE = 0.28
MAX_HEALTH = 1.0
ATTACK_COOLDOWN_TICKS = int(1.8 / TICK)
BOOST_DURATION_TICKS = int(2.0 / TICK)
BOOST_SPEED_MULT = 5.0
DEPTH_AGGRESSIVE = 2
DEPTH_BALANCED = 1
ACTIONS = ["ACCEL", "BRAKE", "LEFT", "RIGHT", "ATTACK", "MAINTAIN"]
HAZARD_COUNT = 8
HAZARD_SLIP_FACTOR = 0.55
HAZARD_DAMAGE = 0.05
NEUTRAL_COUNT = 3
NEUTRAL_MAX_SPEED = 8.0

SCREEN_W = 1000
SCREEN_H = 600
LANE_PAD = 80
TOP_MARGIN = 120
TRACK_H = SCREEN_H - TOP_MARGIN - 80
PLAYER_SPR_W = 120
PLAYER_SPR_H = 120
NEUTRAL_SPR_W = 120
NEUTRAL_SPR_H = 120
HAZARD_SPR_W = 100
HAZARD_SPR_H = 90
FONT_SIZE = 18
WHITE      = (255, 255, 255)
BLACK      = (0,   0,   0)
GRAY       = (40,  40,  40)
LANE_COLOR = (50,  50,  50)
TEXT_COLOR = (230, 230, 230)
HEALTH_BG  = (80,  80,  80)
HEALTH_FG  = (20,  220, 20)
BOOST_COLOR = (255, 200, 0)
HIT_FLASH  = (255, 0,   0)
LANE_LINE_COLOR = (200, 200, 200)

OPP_SPR_W = PLAYER_SPR_W
OPP_SPR_H = PLAYER_SPR_H

# ── cached fonts (fix: no more per-frame SysFont calls) ──────────────────────
_font_cache: dict = {}

def get_font(size: int) -> pygame.font.Font:
    if size not in _font_cache:
        _font_cache[size] = pygame.font.SysFont(None, size)
    return _font_cache[size]


def clamp(v, a, b): return max(a, min(b, v))


def try_beep():
    try:
        import winsound
        winsound.Beep(800, 70)
    except Exception:
        pass


class State:
    __slots__ = (
        "p_pos","p_speed","p_lane","p_health",
        "o_pos","o_speed","o_lane","o_health",
        "tick","p_last_attack_tick","o_last_attack_tick",
        "p_boost_avail","p_boost_ticks_left",
        "hazards","neutrals",
        "_last_hit_by_player","_last_hit_by_opponent",
        "_last_hazard_hit_player","_last_hazard_hit_opponent",
        "_attack_animation"
    )
    def __init__(self, p_pos=0.0, p_speed=3.0, p_lane=2, p_health=MAX_HEALTH,
                 o_pos=0.0, o_speed=3.0, o_lane=2, o_health=MAX_HEALTH,
                 tick=0, p_last_attack_tick=-999, o_last_attack_tick=-999,
                 p_boost_avail=True, p_boost_ticks_left=BOOST_DURATION_TICKS,
                 hazards=None, neutrals=None):
        self.p_pos = p_pos; self.p_speed = p_speed; self.p_lane = p_lane; self.p_health = p_health
        self.o_pos = o_pos; self.o_speed = o_speed; self.o_lane = o_lane; self.o_health = o_health
        self.tick = tick
        self.p_last_attack_tick = p_last_attack_tick; self.o_last_attack_tick = o_last_attack_tick
        self.p_boost_avail = p_boost_avail; self.p_boost_ticks_left = p_boost_ticks_left
        self.hazards = hazards if hazards else []
        self.neutrals = neutrals if neutrals else []
        self._last_hit_by_player = False; self._last_hit_by_opponent = False
        self._last_hazard_hit_player = False; self._last_hazard_hit_opponent = False
        self._attack_animation = None

    def copy(self):
        s = State(self.p_pos,self.p_speed,self.p_lane,self.p_health,
                  self.o_pos,self.o_speed,self.o_lane,self.o_health,
                  self.tick,self.p_last_attack_tick,self.o_last_attack_tick,
                  self.p_boost_avail,self.p_boost_ticks_left,
                  list(self.hazards), [n.copy() for n in self.neutrals])
        s._last_hit_by_player    = self._last_hit_by_player
        s._last_hit_by_opponent  = self._last_hit_by_opponent
        s._last_hazard_hit_player   = self._last_hazard_hit_player
        s._last_hazard_hit_opponent = self._last_hazard_hit_opponent
        s._attack_animation = self._attack_animation
        return s


class Neutral:
    __slots__ = ("pos","lane","speed","health","id","tick_last_dir")
    def __init__(self, pos, lane, speed, health, id):
        self.pos=pos; self.lane=lane; self.speed=speed; self.health=health; self.id=id; self.tick_last_dir=0
    def copy(self):
        n = Neutral(self.pos, self.lane, self.speed, self.health, self.id)
        n.tick_last_dir = self.tick_last_dir
        return n


def spawn_hazards():
    hazards = []
    for _ in range(HAZARD_COUNT):
        pos  = random.uniform(20.0, TRACK_LENGTH - 20.0)
        lane = random.randrange(0, LANES)
        typ  = random.choice(["pothole", "oil"])
        hazards.append((pos, lane, typ))
    return hazards


def spawn_neutrals():
    neutrals = []
    for i in range(NEUTRAL_COUNT):
        pos    = random.uniform(10.0, TRACK_LENGTH - 30.0)
        lane   = random.randrange(0, LANES)
        speed  = random.uniform(2.0, NEUTRAL_MAX_SPEED)
        health = 0.6 + random.random() * 0.4
        neutrals.append(Neutral(pos, lane, speed, health, i + 1))
    return neutrals


def simulate_one_tick(s: State, pa: str, oa: str, dt=TICK):
    s2 = s.copy()

    def apply_speed(speed, act, is_player=False):
        if act == "ACCEL": speed += ACCEL * dt
        elif act == "BRAKE": speed += BRAKE * dt
        if is_player and s2.p_boost_ticks_left > 0:
            speed = clamp(speed, 0.0, MAX_SPEED * BOOST_SPEED_MULT)
        else:
            speed = clamp(speed, 0.0, MAX_SPEED)
        return speed

    s2.p_speed = apply_speed(s2.p_speed, pa, True)
    s2.o_speed = apply_speed(s2.o_speed, oa, False)

    for n in s2.neutrals:
        if s2.tick - n.tick_last_dir > int(0.6 / TICK) and random.random() < 0.25:
            n.lane = clamp(n.lane + random.choice([-1, 0, 1]), 0, LANES - 1)
            n.tick_last_dir = s2.tick
        n.speed += random.uniform(-0.6, 0.6) * dt
        n.speed  = clamp(n.speed, 0.5, NEUTRAL_MAX_SPEED)
        n.pos   += n.speed * dt

    if pa == "LEFT":  s2.p_lane = clamp(s2.p_lane - 1, 0, LANES - 1)
    if pa == "RIGHT": s2.p_lane = clamp(s2.p_lane + 1, 0, LANES - 1)
    if oa == "LEFT":  s2.o_lane = clamp(s2.o_lane - 1, 0, LANES - 1)
    if oa == "RIGHT": s2.o_lane = clamp(s2.o_lane + 1, 0, LANES - 1)

    s2.p_pos += s2.p_speed * dt
    s2.o_pos += s2.o_speed * dt

    if s2.p_boost_ticks_left > 0:
        s2.p_boost_ticks_left -= 1
        if s2.p_boost_ticks_left == 0:
            s2.p_speed = clamp(s2.p_speed, 0, MAX_SPEED)

    s2._last_hit_by_player      = False
    s2._last_hit_by_opponent    = False
    s2._last_hazard_hit_player  = False
    s2._last_hazard_hit_opponent = False
    s2._attack_animation        = None

    if pa == "ATTACK" and (s2.tick - s2.p_last_attack_tick) >= ATTACK_COOLDOWN_TICKS:
        s2.p_last_attack_tick = s2.tick
        if s2.p_lane == s2.o_lane and abs(s2.p_pos - s2.o_pos) <= ATTACK_RANGE:
            s2.o_health = clamp(s2.o_health - ATTACK_DAMAGE, 0.0, MAX_HEALTH)
            s2._last_hit_by_player = True; try_beep()
        else:
            for n in s2.neutrals:
                if n.health > 0 and n.lane == s2.p_lane and abs(n.pos - s2.p_pos) <= ATTACK_RANGE:
                    n.health = clamp(n.health - ATTACK_DAMAGE, 0.0, MAX_HEALTH)
                    s2._last_hit_by_player = True; try_beep(); break

    if oa == "ATTACK" and (s2.tick - s2.o_last_attack_tick) >= ATTACK_COOLDOWN_TICKS:
        s2.o_last_attack_tick = s2.tick
        if s2.p_lane == s2.o_lane and abs(s2.p_pos - s2.o_pos) <= ATTACK_RANGE:
            s2.p_health = clamp(s2.p_health - ATTACK_DAMAGE, 0.0, MAX_HEALTH)
            s2._last_hit_by_opponent = True; try_beep()
        else:
            for n in s2.neutrals:
                if n.health > 0 and n.lane == s2.o_lane and abs(n.pos - s2.o_pos) <= ATTACK_RANGE:
                    n.health = clamp(n.health - ATTACK_DAMAGE, 0.0, MAX_HEALTH)
                    s2._last_hit_by_opponent = True; try_beep(); break

    for pos, lane, typ in s2.hazards:
        if lane == s2.p_lane and abs(s2.p_pos - pos) < 1.5:
            s2._last_hazard_hit_player = True
            s2.p_speed = s2.p_speed * HAZARD_SLIP_FACTOR
            s2.p_health = clamp(s2.p_health - HAZARD_DAMAGE, 0, MAX_HEALTH)
        if lane == s2.o_lane and abs(s2.o_pos - pos) < 1.5:
            s2._last_hazard_hit_opponent = True
            s2.o_speed = s2.o_speed * HAZARD_SLIP_FACTOR
            s2.o_health = clamp(s2.o_health - HAZARD_DAMAGE, 0, MAX_HEALTH)

    s2.tick += 1
    return s2


def is_terminal(s: State):
    return s.p_health <= 0 or s.o_health <= 0 or s.p_pos >= TRACK_LENGTH or s.o_pos >= TRACK_LENGTH


def world_to_screen(pos, player_pos, lane):
    VIEWPORT_UNITS = 40.0
    rel = pos - player_pos
    bottom_y = TOP_MARGIN + TRACK_H - 10
    top_y    = TOP_MARGIN + 10
    rel_clamped = clamp(rel, -20.0, VIEWPORT_UNITS)
    t = (rel_clamped + 20) / (VIEWPORT_UNITS + 20)
    y = bottom_y - t * (bottom_y - top_y)
    lane_w = (SCREEN_W - 2 * LANE_PAD) / LANES
    x = LANE_PAD + lane * lane_w + lane_w / 2
    return int(x), int(y)


# ── UI drawing helpers ────────────────────────────────────────────────────────

def draw_lane_lines(surf, player_pos):
    """Draw visible lane dividers on the track area."""
    lane_w = (SCREEN_W - 2 * LANE_PAD) / LANES
    bottom_y = TOP_MARGIN + TRACK_H - 10
    top_y    = TOP_MARGIN + 10
    for i in range(1, LANES):
        x = int(LANE_PAD + i * lane_w)
        # dashed line
        dash_len = 18
        gap_len  = 12
        total    = bottom_y - top_y
        y = top_y
        while y < bottom_y:
            end_y = min(y + dash_len, bottom_y)
            pygame.draw.line(surf, LANE_LINE_COLOR, (x, int(y)), (x, int(end_y)), 1)
            y += dash_len + gap_len


def draw_health_bar(surf, x, y, w, h, pct, label=None):
    font = get_font(FONT_SIZE)
    pygame.draw.rect(surf, HEALTH_BG, (x, y, w, h))
    inner_w = int(w * clamp(pct, 0.0, 1.0))
    # colour shifts red as health drops
    r = int(255 * (1.0 - clamp(pct, 0.0, 1.0)))
    g = int(220 * clamp(pct, 0.0, 1.0))
    pygame.draw.rect(surf, (r, g, 20), (x, y, inner_w, h))
    pygame.draw.rect(surf, WHITE, (x, y, w, h), 1)
    if label:
        txt = font.render(f"{label}: {int(pct * 100)}%", True, TEXT_COLOR)
        surf.blit(txt, (x + 4, y - FONT_SIZE - 2))


def draw_distance_bar(surf, x, y, w, h, p_pos, o_pos, track_length):
    """Progress bar showing both player and opponent positions."""
    font = get_font(FONT_SIZE)
    pygame.draw.rect(surf, (100, 100, 100), (x, y, w, h))
    # player marker
    p_pct = clamp(p_pos / track_length, 0.0, 1.0)
    pygame.draw.rect(surf, (255, 200, 0), (x, y, int(w * p_pct), h))
    # opponent marker (small red tick)
    o_pct = clamp(o_pos / track_length, 0.0, 1.0)
    ox = x + int(w * o_pct)
    pygame.draw.rect(surf, (255, 60, 60), (ox - 2, y - 3, 4, h + 6))
    pygame.draw.rect(surf, WHITE, (x, y, w, h), 1)
    txt = font.render(f"Distance: {int((1.0 - p_pct) * track_length)} units", True, TEXT_COLOR)
    surf.blit(txt, (x + 4, y - FONT_SIZE - 2))


def draw_speedometer(surf, x, y, speed, max_speed):
    """Simple speed gauge in the HUD."""
    font  = get_font(20)
    label = get_font(16)
    w, h  = 120, 14
    pct   = clamp(speed / max_speed, 0.0, 1.0)
    pygame.draw.rect(surf, (60, 60, 60), (x, y, w, h))
    r = int(255 * pct)
    g = int(200 * (1.0 - pct))
    pygame.draw.rect(surf, (r, g, 0), (x, y, int(w * pct), h))
    pygame.draw.rect(surf, WHITE, (x, y, w, h), 1)
    spd_txt = font.render(f"{speed:.1f} u/s", True, WHITE)
    surf.blit(spd_txt, (x + w + 6, y - 2))
    cap_txt = label.render("SPEED", True, (180, 180, 180))
    surf.blit(cap_txt, (x, y - 16))


def draw_boost_widget(surf, x, y, boost_avail, boost_ticks_left):
    """Shows BOOST status: ready, active, or used."""
    font = get_font(20)
    if boost_avail:
        color = (0, 255, 180)
        label = "BOOST [B] READY"
    elif boost_ticks_left > 0:
        color = BOOST_COLOR
        label = f"BOOSTING! {boost_ticks_left}"
    else:
        color = (120, 120, 120)
        label = "BOOST USED"
    txt = font.render(label, True, color)
    surf.blit(txt, (x, y))


def draw_attack_cooldown(surf, x, y, tick, last_attack_tick):
    """Visual cooldown bar under the attack button hint."""
    font = get_font(18)
    elapsed = tick - last_attack_tick
    pct     = clamp(elapsed / ATTACK_COOLDOWN_TICKS, 0.0, 1.0)
    w, h    = 100, 8
    pygame.draw.rect(surf, (60, 60, 60), (x, y, w, h))
    ready_color = (0, 220, 80) if pct >= 1.0 else (200, 100, 0)
    pygame.draw.rect(surf, ready_color, (x, y, int(w * pct), h))
    pygame.draw.rect(surf, WHITE, (x, y, w, h), 1)
    label = "ATK [K]" + (" READY" if pct >= 1.0 else " CD")
    lbl_txt = font.render(label, True, TEXT_COLOR)
    surf.blit(lbl_txt, (x, y - 16))


def draw_menu_box(screen, x, y, w, h):
    box_surf = pygame.Surface((w, h), pygame.SRCALPHA)
    box_surf.fill((0, 0, 0, 180))
    pygame.draw.rect(box_surf, WHITE, box_surf.get_rect(), 2)
    screen.blit(box_surf, (x, y))
    return pygame.Rect(x, y, w, h)


def draw_controls_overlay(surf):
    """Semi-transparent controls cheat-sheet drawn in the bottom-left."""
    lines = [
        "W / S  — Accel / Brake",
        "A / D  — Lane Left / Right",
        "K      — Attack",
        "B      — Boost (once)",
        "ESC    — Pause",
    ]
    font   = get_font(18)
    pad    = 8
    lh     = 20
    box_w  = 210
    box_h  = pad * 2 + lh * len(lines)
    bx, by = 10, SCREEN_H - box_h - 10
    overlay = pygame.Surface((box_w, box_h), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 140))
    surf.blit(overlay, (bx, by))
    for i, line in enumerate(lines):
        txt = font.render(line, True, (200, 200, 200))
        surf.blit(txt, (bx + pad, by + pad + i * lh))


# ── asset loading ─────────────────────────────────────────────────────────────

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

def load_image_or_placeholder(path, w, h, draw_fn=None):
    try:
        img = pygame.image.load(path).convert_alpha()
        img = pygame.transform.smoothscale(img, (w, h))
        return img
    except Exception:
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        if draw_fn:
            draw_fn(surf)
        return surf


def make_player_placeholder(surf):
    surf.fill((0, 0, 0, 0))
    pygame.draw.polygon(surf, (30, 200, 30),
        [(8, surf.get_height()-6), (surf.get_width()-8, surf.get_height()-6), (surf.get_width()//2, 8)])
    pygame.draw.rect(surf, (20, 120, 20),
        (surf.get_width()//4, surf.get_height()-18, surf.get_width()//2, 8))
    pygame.draw.circle(surf, (0,0,0), (12, surf.get_height()-2), 4)
    pygame.draw.circle(surf, (0,0,0), (surf.get_width()-12, surf.get_height()-2), 4)


def make_opponent_placeholder(surf):
    surf.fill((0, 0, 0, 0))
    pygame.draw.polygon(surf, (200, 30, 30),
        [(8, surf.get_height()-6), (surf.get_width()-8, surf.get_height()-6), (surf.get_width()//2, 8)])
    pygame.draw.rect(surf, (150, 20, 20),
        (surf.get_width()//4, surf.get_height()-18, surf.get_width()//2, 8))
    pygame.draw.circle(surf, (0,0,0), (12, surf.get_height()-2), 4)
    pygame.draw.circle(surf, (0,0,0), (surf.get_width()-12, surf.get_height()-2), 4)


def make_neutral_placeholder(surf):
    surf.fill((0, 0, 0, 0))
    pygame.draw.rect(surf, (30, 130, 200),
        (4, surf.get_height()-14, surf.get_width()-8, 8))
    pygame.draw.polygon(surf, (20, 100, 170),
        [(surf.get_width()//2, 6), (6, surf.get_height()-6), (surf.get_width()-6, surf.get_height()-6)])


def make_hazard_oil(surf):
    surf.fill((0, 0, 0, 0))
    pygame.draw.circle(surf, (30, 30, 30),
        (surf.get_width()//2, surf.get_height()//2), min(surf.get_width(), surf.get_height())//3)
    pygame.draw.ellipse(surf, (10, 10, 10),
        (2, surf.get_height()//2-6, surf.get_width()-4, 12))


def make_hazard_pothole(surf):
    surf.fill((0, 0, 0, 0))
    pygame.draw.ellipse(surf, (80, 40, 20),  (2, 4, surf.get_width()-4,  surf.get_height()-8))
    pygame.draw.ellipse(surf, (40, 20, 10),  (6, 8, surf.get_width()-12, surf.get_height()-16))


def load_sprites():
    os.makedirs(ASSETS_DIR, exist_ok=True)
    return {
        "player":   load_image_or_placeholder(os.path.join(ASSETS_DIR, "player_bike.png"),   PLAYER_SPR_W,       PLAYER_SPR_H,       make_player_placeholder),
        "opponent": load_image_or_placeholder(os.path.join(ASSETS_DIR, "opponent_bike.png"), PLAYER_SPR_W,       PLAYER_SPR_H,       make_opponent_placeholder),
        "neutral":  load_image_or_placeholder(os.path.join(ASSETS_DIR, "neutral_bike.png"),  NEUTRAL_SPR_W,      NEUTRAL_SPR_H,      make_neutral_placeholder),
        "oil":      load_image_or_placeholder(os.path.join(ASSETS_DIR, "hazard_oil.png"),    HAZARD_SPR_W,       HAZARD_SPR_H,       make_hazard_oil),
        "pothole":  load_image_or_placeholder(os.path.join(ASSETS_DIR, "hazard_pothole.png"),HAZARD_SPR_W + 8,   HAZARD_SPR_H,       make_hazard_pothole),
    }


def build_initial_state():
    return State(
        p_pos=0.0, p_speed=3.0, p_lane=1, p_health=MAX_HEALTH,
        o_pos=0.0, o_speed=3.0, o_lane=1, o_health=MAX_HEALTH,   # fix: opponent starts at full health
        hazards=spawn_hazards(), neutrals=spawn_neutrals()
    )


# ── screens ───────────────────────────────────────────────────────────────────

def show_intro(screen, font):
    clock = pygame.time.Clock()

    bg = None  # black background for splash

    # Actual logo asset
    try:
        logo_img  = pygame.image.load(os.path.join(ASSETS_DIR, "roadrash_logo.png")).convert_alpha()
        logo_w    = min(logo_img.get_width(), 500)
        logo_h    = int(logo_img.get_height() * (logo_w / logo_img.get_width()))
        logo_surf = pygame.transform.smoothscale(logo_img, (logo_w, logo_h))
    except Exception:
        # Fallback drawn panel if asset missing
        logo_w, logo_h = 500, 200
        logo_surf = pygame.Surface((logo_w, logo_h), pygame.SRCALPHA)
        logo_surf.fill((0, 0, 0, 200))
        pygame.draw.rect(logo_surf, (220, 50, 0), logo_surf.get_rect(), 4)
        title_txt = get_font(80).render("ROAD RASH", True, (255, 80, 0))
        logo_surf.blit(title_txt, (logo_w // 2 - title_txt.get_width() // 2,
                                   logo_h // 2 - title_txt.get_height() // 2))

    # Start off-screen above the top
    logo_x   = SCREEN_W // 2 - logo_w // 2
    logo_y   = float(-logo_h)
    target_y = float(SCREEN_H // 2 - logo_h // 2)

    alpha       = 0
    flash_timer = 0
    waiting     = True

    while waiting:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); exit()
            elif event.type == pygame.KEYDOWN:
                waiting = False

        # Draw background
        if bg:
            screen.blit(bg, (0, 0))
        else:
            screen.fill(BLACK)

        # Slide logo down
        if logo_y < target_y:
            logo_y = min(logo_y + 8, target_y)

        # Fade in
        if alpha < 255:
            alpha = min(alpha + 5, 255)

        logo_surf.set_alpha(alpha)
        screen.blit(logo_surf, (logo_x, int(logo_y)))

        # Blinking "press any key" once logo has landed
        if logo_y >= target_y:
            flash_timer += 1
            if (flash_timer // 30) % 2 == 0:
                press_txt = get_font(28).render("Press any key to start", True, WHITE)
                screen.blit(press_txt, (SCREEN_W // 2 - press_txt.get_width() // 2, SCREEN_H - 90))

        pygame.display.flip()
        clock.tick(60)


def _menu_screen(screen, title_text, options, bg_path):
    """Generic arrow-key menu. Returns the chosen option string."""
    selected = 0
    clock    = pygame.time.Clock()
    try:
        bg_img = pygame.image.load(bg_path).convert()
        bg_img = pygame.transform.scale(bg_img, (SCREEN_W, SCREEN_H))
    except Exception:
        bg_img = None

    title_font  = get_font(34)
    option_font = get_font(28)

    while True:
        if bg_img:
            screen.blit(bg_img, (0, 0))
        else:
            screen.fill(BLACK)

        box_w, box_h = 440, 80 + len(options) * 52 + 20
        box_rect = draw_menu_box(screen,
                                 SCREEN_W//2 - box_w//2,
                                 SCREEN_H//2 - box_h//2,
                                 box_w, box_h)

        title_surf = title_font.render(title_text, True, WHITE)
        screen.blit(title_surf, (SCREEN_W//2 - title_surf.get_width()//2, box_rect.top + 18))

        for i, opt in enumerate(options):
            is_sel = (i == selected)
            color  = BOOST_COLOR if is_sel else WHITE
            prefix = "> " if is_sel else "  "
            txt    = option_font.render(prefix + opt.upper(), True, color)
            screen.blit(txt, (SCREEN_W//2 - txt.get_width()//2, box_rect.top + 72 + i * 52))

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); exit()
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    if options[selected].upper() == "QUIT":
                        pygame.quit(); exit()
                    return options[selected]
                elif event.key in (pygame.K_UP, pygame.K_w):
                    selected = (selected - 1) % len(options)
                elif event.key in (pygame.K_DOWN, pygame.K_s):
                    selected = (selected + 1) % len(options)

        pygame.display.flip()
        clock.tick(60)


def select_racetrack(screen, font):
    return _menu_screen(screen, "SELECT RACETRACK",
                        ["City", "Desert", "Forest", "QUIT"],
                        os.path.join(ASSETS_DIR, "track_select_bg.png"))


def select_opponent_type(screen, font):
    return _menu_screen(screen, "SELECT OPPONENT AI TYPE",
                        ["balanced", "aggressive", "random", "QUIT"],
                        os.path.join(ASSETS_DIR, "ai_background.png"))


def determine_winner(state):
    if state.p_health <= 0: return "OPPONENT"
    if state.o_health <= 0: return "PLAYER"
    return "PLAYER" if state.p_pos > state.o_pos else "OPPONENT"


def show_results(screen, font, state):
    winner     = determine_winner(state)
    player_won = (winner == "PLAYER")
    img_path   = os.path.join(ASSETS_DIR, "winner.png" if player_won else "loser.PNG")
    try:
        result_img = pygame.image.load(img_path).convert_alpha()
        result_img = pygame.transform.smoothscale(result_img, (SCREEN_W, SCREEN_H))
    except Exception:
        result_img = pygame.Surface((SCREEN_W, SCREEN_H))
        result_img.fill((255, 255, 255))

    clock          = pygame.time.Clock()
    alpha          = 0
    fade_in_speed  = 8
    fade_out_speed = 4

    while alpha < 255:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); exit()
        alpha = min(alpha + fade_in_speed, 255)
        img_copy = result_img.copy(); img_copy.set_alpha(alpha)
        screen.blit(img_copy, (0, 0))
        pygame.display.flip(); clock.tick(60)

    pygame.time.wait(800)

    while alpha > 0:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); exit()
        alpha = max(alpha - fade_out_speed, 0)
        screen.fill(BLACK)
        img_copy = result_img.copy(); img_copy.set_alpha(alpha)
        screen.blit(img_copy, (0, 0))
        pygame.display.flip(); clock.tick(60)

    bg_path = os.path.join(ASSETS_DIR, "results_bg.png")
    try:
        results_bg = pygame.image.load(bg_path).convert()
        results_bg = pygame.transform.scale(results_bg, (SCREEN_W, SCREEN_H))
    except Exception:
        results_bg = pygame.Surface((SCREEN_W, SCREEN_H)); results_bg.fill(GRAY)

    options      = ["RESTART", "MAIN MENU", "QUIT"]
    selected     = 0
    option_font  = get_font(28)
    title_font   = get_font(36)

    while True:
        screen.blit(results_bg, (0, 0))
        box_w, box_h = 500, 370
        box_rect = draw_menu_box(screen,
                                 SCREEN_W//2 - box_w//2,
                                 SCREEN_H//2 - box_h//2,
                                 box_w, box_h)

        txt = title_font.render(f"RACE OVER!  Winner: {winner}", True,
                                (255, 220, 0) if player_won else (255, 80, 80))
        screen.blit(txt, (SCREEN_W//2 - txt.get_width()//2, box_rect.top + 24))

        draw_health_bar(screen, SCREEN_W//2 - 160, box_rect.top + 80,  320, 24, state.p_health, "PLAYER")
        draw_health_bar(screen, SCREEN_W//2 - 160, box_rect.top + 124, 320, 24, state.o_health, "OPPONENT")

        # distance summary
        dist_font = get_font(20)
        d_txt = dist_font.render(
            f"You: {state.p_pos:.1f}  |  Opponent: {state.o_pos:.1f}  /  {TRACK_LENGTH:.0f} units",
            True, (200, 200, 200))
        screen.blit(d_txt, (SCREEN_W//2 - d_txt.get_width()//2, box_rect.top + 162))

        for i, opt in enumerate(options):
            is_sel = (i == selected)
            color  = BOOST_COLOR if is_sel else WHITE
            prefix = "> " if is_sel else "  "
            opt_txt = option_font.render(prefix + opt, True, color)
            screen.blit(opt_txt, (SCREEN_W//2 - opt_txt.get_width()//2, box_rect.top + 200 + i * 40))

        pygame.display.flip()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); exit()
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_UP, pygame.K_w):
                    selected = (selected - 1) % len(options)
                elif event.key in (pygame.K_DOWN, pygame.K_s):
                    selected = (selected + 1) % len(options)
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    if options[selected] == "QUIT":
                        pygame.quit(); exit()
                    return options[selected]

        clock.tick(60)


def show_pause_screen(screen):
    """Overlay pause menu. Returns True to resume, False to quit to main menu."""
    overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 160))
    screen.blit(overlay, (0, 0))

    options  = ["RESUME", "MAIN MENU", "QUIT"]
    selected = 0
    clock    = pygame.time.Clock()
    title_f  = get_font(48)
    opt_f    = get_font(30)

    while True:
        # redraw overlay each frame so it stays on top
        screen.blit(overlay, (0, 0))
        box_w, box_h = 360, 260
        box_rect = draw_menu_box(screen,
                                 SCREEN_W//2 - box_w//2,
                                 SCREEN_H//2 - box_h//2,
                                 box_w, box_h)
        t = title_f.render("PAUSED", True, WHITE)
        screen.blit(t, (SCREEN_W//2 - t.get_width()//2, box_rect.top + 20))

        for i, opt in enumerate(options):
            color  = BOOST_COLOR if i == selected else WHITE
            prefix = "> " if i == selected else "  "
            txt    = opt_f.render(prefix + opt, True, color)
            screen.blit(txt, (SCREEN_W//2 - txt.get_width()//2, box_rect.top + 90 + i * 46))

        pygame.display.flip()
        clock.tick(60)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return "RESUME"
                elif event.key in (pygame.K_UP, pygame.K_w):
                    selected = (selected - 1) % len(options)
                elif event.key in (pygame.K_DOWN, pygame.K_s):
                    selected = (selected + 1) % len(options)
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    if options[selected] == "QUIT":
                        pygame.quit(); exit()
                    return options[selected]


# ── AI ────────────────────────────────────────────────────────────────────────

def evaluate_state(state: State):
    return (state.p_pos - state.o_pos) + (state.p_health - state.o_health) * 5


def minimax(state: State, depth, maximizing_player, alpha=-float('inf'), beta=float('inf')):
    if depth == 0 or is_terminal(state):
        return evaluate_state(state), None
    if maximizing_player:
        max_eval = -float('inf'); best_action = None
        for act in ACTIONS:
            next_state = simulate_one_tick(state, act, "MAINTAIN")
            ev, _      = minimax(next_state, depth - 1, False, alpha, beta)
            if ev > max_eval:
                max_eval = ev; best_action = act
            alpha = max(alpha, ev)
            if beta <= alpha: break
        return max_eval, best_action
    else:
        min_eval = float('inf'); best_action = None
        for act in ACTIONS:
            next_state = simulate_one_tick(state, "MAINTAIN", act)
            ev, _      = minimax(next_state, depth - 1, True, alpha, beta)
            if ev < min_eval:
                min_eval = ev; best_action = act
            beta = min(beta, ev)
            if beta <= alpha: break
        return min_eval, best_action


def opponent_choose_action(state, opponent_type="balanced"):
    if opponent_type == "random":
        return random.choice(ACTIONS)
    depth    = DEPTH_BALANCED if opponent_type == "balanced" else DEPTH_AGGRESSIVE
    _, action = minimax(state, depth, False)
    return action if action else "MAINTAIN"


# ── main game loop ────────────────────────────────────────────────────────────

def run_game(opponent_type, track):
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption("Road Rash")
    clock   = pygame.time.Clock()
    sprites = load_sprites()

    bg_path = os.path.join(ASSETS_DIR, f"{track.lower()}_track.png")
    try:
        bg_img = pygame.image.load(bg_path).convert()
        bg_img = pygame.transform.scale(bg_img, (SCREEN_W, SCREEN_H))
    except Exception:
        bg_img = None

    def reset():
        return build_initial_state(), "MAINTAIN", "MAINTAIN", time.time(), "", 0

    state, last_pa, last_oa, last_time, flash_msg, flash_count = reset()
    show_controls = True   # show controls overlay until player moves

    while True:
        now = time.time()

        # ── events ──
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    # snapshot current screen for pause backdrop
                    snap = screen.copy()
                    result = show_pause_screen(snap)
                    if result == "RESUME":
                        last_time = time.time()   # avoid tick burst after unpause
                    elif result == "MAIN MENU":
                        return "MAIN MENU"
                if event.key == pygame.K_b and state.p_boost_avail:
                    state.p_boost_avail      = False
                    state.p_boost_ticks_left = BOOST_DURATION_TICKS
                    flash_msg   = "BOOST ACTIVATED!"
                    flash_count = int(0.7 * 60)

        keys = pygame.key.get_pressed()
        pa   = "MAINTAIN"
        if keys[pygame.K_w] and not keys[pygame.K_s]:   pa = "ACCEL"
        elif keys[pygame.K_s] and not keys[pygame.K_w]: pa = "BRAKE"
        if keys[pygame.K_a] and not keys[pygame.K_d]:   pa = "LEFT"
        elif keys[pygame.K_d] and not keys[pygame.K_a]: pa = "RIGHT"
        if keys[pygame.K_k]: pa = "ATTACK"

        if pa != "MAINTAIN":
            show_controls = False   # hide hint once player acts

        # ── tick ──
        if now - last_time >= TICK:
            last_time = now
            oa    = opponent_choose_action(state, opponent_type)
            state = simulate_one_tick(state, pa, oa)
            last_pa = pa; last_oa = oa

            if state._last_hit_by_player:
                flash_msg = "HIT OPPONENT!";    flash_count = int(0.9 * 60)
            elif state._last_hit_by_opponent:
                flash_msg = "YOU GOT HIT!";     flash_count = int(0.9 * 60)
            elif state._last_hazard_hit_player:
                flash_msg = "SLIPPED ON HAZARD!"; flash_count = int(0.9 * 60)
            elif state._last_hazard_hit_opponent:
                flash_msg = "OPPONENT SLIPPED!"; flash_count = int(0.9 * 60)

        # ── draw background ──
        if bg_img:
            screen.blit(bg_img, (0, 0))
        else:
            screen.fill((60, 180, 60))

        # ── lane dividers ──
        draw_lane_lines(screen, state.p_pos)

        # ── finish line ──
        FINISH_VIEWPORT_DISTANCE = 50.0
        dist_to_finish = TRACK_LENGTH - state.p_pos
        if dist_to_finish <= FINISH_VIEWPORT_DISTANCE:
            bottom_y = TOP_MARGIN + TRACK_H - 10
            top_y    = TOP_MARGIN + 10
            t        = clamp(dist_to_finish / FINISH_VIEWPORT_DISTANCE, 0.0, 1.0)
            finish_y = top_y + (1.0 - t) * (bottom_y - top_y)
            pygame.draw.line(screen, (255, 255, 0),
                             (LANE_PAD - 20, finish_y), (SCREEN_W - LANE_PAD + 20, finish_y), 4)
            ft = get_font(32).render("FINISH", True, (255, 255, 0))
            screen.blit(ft, (SCREEN_W//2 - ft.get_width()//2, finish_y - 30))

        # ── hazards ──
        HAZARD_VIEW_DISTANCE = 45.0
        for hz in state.hazards:
            hz_pos, hz_lane, hz_type = hz
            rel = hz_pos - state.p_pos
            if -2.0 <= rel <= HAZARD_VIEW_DISTANCE:
                x, y = world_to_screen(hz_pos, state.p_pos, hz_lane)
                screen.blit(sprites[hz_type], (x - HAZARD_SPR_W//2, y - HAZARD_SPR_H//2))

        # ── neutrals ──
        NEUTRAL_VIEW_DISTANCE = 50.0
        for n in state.neutrals:
            if n.health <= 0: continue
            rel = n.pos - state.p_pos
            if -2.0 <= rel <= NEUTRAL_VIEW_DISTANCE:
                x, y = world_to_screen(n.pos, state.p_pos, n.lane)
                screen.blit(sprites["neutral"], (x - NEUTRAL_SPR_W//2, y - NEUTRAL_SPR_H//2))

        # ── sprites ──
        px, py = world_to_screen(state.p_pos, state.p_pos, state.p_lane)
        screen.blit(sprites["player"], (px - PLAYER_SPR_W//2, py - PLAYER_SPR_H//2))
        ox, oy = world_to_screen(state.o_pos, state.p_pos, state.o_lane)
        screen.blit(sprites["opponent"], (ox - OPP_SPR_W//2, oy - OPP_SPR_H//2))

        # ── HUD ──
        # health bars
        draw_health_bar(screen, 20, 20, 200, 24, state.p_health, "PLAYER")
        draw_health_bar(screen, SCREEN_W - 220, 20, 200, 24, state.o_health, "OPPONENT")

        # speedometer (player)
        draw_speedometer(screen, 20, 80, state.p_speed, MAX_SPEED * BOOST_SPEED_MULT if state.p_boost_ticks_left > 0 else MAX_SPEED)

        # boost widget
        draw_boost_widget(screen, 20, 58, state.p_boost_avail, state.p_boost_ticks_left)

        # attack cooldown
        draw_attack_cooldown(screen, SCREEN_W - 220, 58, state.tick, state.p_last_attack_tick)

        # distance / minimap bar (shows both riders)
        draw_distance_bar(screen, SCREEN_W//2 - 150, SCREEN_H - 40, 300, 18,
                          state.p_pos, state.o_pos, TRACK_LENGTH)

        # last action labels
        act_font = get_font(22)
        p_txt = act_font.render(f"Player: {last_pa}", True, WHITE)
        o_txt = act_font.render(f"Opponent: {last_oa}", True, WHITE)
        screen.blit(p_txt, (20, SCREEN_H - 65))
        screen.blit(o_txt, (SCREEN_W - o_txt.get_width() - 20, SCREEN_H - 65))

        # flash message
        if flash_count > 0 and flash_msg:
            color    = HIT_FLASH if (flash_count // 6) % 2 == 0 else WHITE
            msg_surf = get_font(42).render(flash_msg, True, color)
            screen.blit(msg_surf, (SCREEN_W//2 - msg_surf.get_width()//2,
                                   TOP_MARGIN//2 - msg_surf.get_height()//2))
            flash_count -= 1

        # controls overlay (shown until first input)
        if show_controls:
            draw_controls_overlay(screen)

        pygame.display.flip()
        clock.tick(60)

        # ── terminal check ──
        if is_terminal(state):
            result = show_results(screen, get_font(32), state)
            if result == "RESTART":
                state, last_pa, last_oa, last_time, flash_msg, flash_count = reset()
                show_controls = False
            elif result == "MAIN MENU":
                return "MAIN MENU"
            else:
                return


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption("Road Rash")
    font = get_font(FONT_SIZE)

    show_intro(screen, font)

    # main menu loop — no recursion, no stack overflow
    while True:
        track         = select_racetrack(screen, font)
        opponent_type = select_opponent_type(screen, font)
        result        = run_game(opponent_type, track)
        if result != "MAIN MENU":
            break
