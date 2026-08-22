"""Share-card text + PNG for completed Action Console runs.

Text extends Daily's existing builders (`daily._build_share_card` /
frontend `buildActionModeShareCard`): same 🔐 header / Score — OUTCOME
lines, link swapped from `breachreplay.com/daily` to
`breachreplay.com/r/{token}`. Daily Action Console never shipped a host
emoji grid (🟩🟥⬛); the decision-gate card uses ✅❌ per gate, which
does not apply here — do not invent a new grid.

PNG is Pillow (already in requirements for CMMC branding / MFA QR), not
Playwright. Input is ONLY a public replay DTO — same lock as
`build_public_replay_dto`. The renderer never receives seed, action_log,
hidden IOCs, or unknown-host identity.
"""
from io import BytesIO
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageFont

# Same labels RunDebrief / Daily's action-mode card uppercases.
OUTCOME_SHARE_LABELS = {
    "contained": "CONTAINED",
    "contained_at_cost": "CONTAINED AT COST",
    "overreacted": "OVERREACTED",
    "breached_spread_limited": "BREACHED — SPREAD LIMITED",
    "breached": "BREACHED",
}

# Design tokens (frontend/src/theme/tokens.ts) as RGB — keep the PNG on
# the same palette as the public replay page.
_VOID = (11, 15, 20)
_PANEL = (18, 26, 35)
_PHOSPHOR = (255, 180, 84)
_BLEED = (229, 72, 77)
_CONTAIN = (61, 214, 140)
_DIM = (138, 151, 165)
_UNKNOWN = (58, 69, 80)
_WHITE = (249, 250, 251)

_OUTCOME_COLOR = {
    "contained": _CONTAIN,
    "contained_at_cost": _PHOSPHOR,
    "overreacted": _BLEED,
    "breached_spread_limited": _PHOSPHOR,
    "breached": _BLEED,
}

OG_WIDTH = 1200
OG_HEIGHT = 630


def format_share_clock(seconds: int) -> str:
    safe = max(0, int(seconds or 0))
    minutes, secs = divmod(safe, 60)
    return f"{minutes}:{secs:02d}"


def outcome_share_label(outcome: str) -> str:
    return OUTCOME_SHARE_LABELS.get(outcome, outcome.replace("_", " ").upper())


def build_share_card_text(
    *,
    scenario_title: str,
    outcome: str,
    score: int,
    duration_seconds: int,
    share_token: str,
    mode: str,
    challenge_number: Optional[int] = None,
    streak: Optional[int] = None,
) -> str:
    """Wordle-style plaintext. `share_token` is the only identifier that
    may appear in the link — never a run_id. Streak is Daily-only flavor
    (same `> 1` gate as `buildActionModeShareCard`); omitted on scenario
    cards and never written onto the public DTO / PNG."""
    if mode == "daily" and challenge_number is not None:
        header = f"🔐 BreachReplay Daily #{challenge_number}"
    else:
        header = "🔐 BreachReplay"
    lines = [
        header,
        scenario_title,
        f"Score: {int(score):,} — {outcome_share_label(outcome)}",
        f"Time: {format_share_clock(duration_seconds)}",
    ]
    if mode == "daily" and streak is not None and streak > 1:
        lines.append(f"🔥 {streak}-day streak")
    lines.append(f"breachreplay.com/r/{share_token}")
    return "\n".join(lines)


def _host_dot_color(host: dict) -> tuple[int, int, int]:
    """Known/unknown rendering matching ActionConsole.hostNodeState —
    unknown is a silhouette color only. Never reads hostname."""
    if host.get("visibility") == "unknown":
        return _UNKNOWN
    if host.get("isolated"):
        return _CONTAIN
    level = host.get("compromise_level")
    if level == "none":
        return _DIM
    if level == "foothold":
        return _BLEED
    return _BLEED


def _draw_map(draw: ImageDraw.ImageDraw, hosts: list, box: tuple[int, int, int, int]) -> None:
    """Dots only — no host labels, so unknown-tier identity cannot leak
    even if a poisoned snapshot still had a hostname key (the DTO builder
    strips it; this is defense in depth)."""
    left, top, right, bottom = box
    positioned = [
        h for h in hosts
        if isinstance(h, dict) and isinstance(h.get("x"), (int, float)) and isinstance(h.get("y"), (int, float))
    ]
    if not positioned:
        return
    xs = [float(h["x"]) for h in positioned]
    ys = [float(h["y"]) for h in positioned]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)
    pad = 28
    width = right - left - pad * 2
    height = bottom - top - pad * 2
    for h in positioned:
        px = left + pad + ((float(h["x"]) - min_x) / span_x) * width
        py = top + pad + ((float(h["y"]) - min_y) / span_y) * height
        color = _host_dot_color(h)
        r = 9
        draw.ellipse((px - r, py - r, px + r, py + r), fill=color)


def render_share_card_png(dto: dict[str, Any]) -> bytes:
    """1200×630 OG image from a public DTO only. Raises ValueError if
    required public fields are missing so a caller cannot silently render
    a partial leak from a raw ActionRun row."""
    title = dto.get("scenario_title")
    outcome = dto.get("outcome")
    score = dto.get("score")
    duration = dto.get("duration_seconds")
    if not isinstance(title, str) or not isinstance(outcome, str):
        raise ValueError("public DTO missing scenario_title/outcome")
    if not isinstance(score, int) or isinstance(score, bool):
        raise ValueError("public DTO missing integer score")
    if not isinstance(duration, int) or isinstance(duration, bool):
        raise ValueError("public DTO missing integer duration_seconds")

    img = Image.new("RGB", (OG_WIDTH, OG_HEIGHT), _VOID)
    draw = ImageDraw.Draw(img)
    draw.rectangle((40, 40, OG_WIDTH - 40, OG_HEIGHT - 40), outline=_PANEL, width=2)

    font = _load_font()
    draw.text((72, 72), "BREACHREPLAY", fill=_PHOSPHOR, font=font)
    draw.text((72, 160), title[:48], fill=_WHITE, font=font)
    draw.text((72, 260), outcome_share_label(outcome), fill=_OUTCOME_COLOR.get(outcome, _DIM), font=font)
    draw.text((72, 360), f"{score:,} pts", fill=_WHITE, font=font)
    draw.text((72, 440), format_share_clock(duration), fill=_DIM, font=font)

    hosts = dto.get("hosts") if isinstance(dto.get("hosts"), list) else []
    _draw_map(draw, hosts, (620, 80, OG_WIDTH - 72, OG_HEIGHT - 80))

    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _load_font():
    try:
        return ImageFont.truetype("DejaVuSans.ttf", 36)
    except OSError:
        return ImageFont.load_default()
