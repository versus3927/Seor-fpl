import asyncio
import colorsys
import hashlib
import io
import os
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
CACHE = Path("data/profile_art")
LOGO = ROOT / "assets" / "seor_logo.png"
W, H = 1536, 1024
WHITE = (242, 243, 248)
MUTED = (165, 168, 184)


def _font(size, bold=False):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _generate_art(prompt, out_path):
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        return False
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=key)
        model = os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
        )
        for part in response.parts:
            if part.inline_data is not None:
                Image.open(io.BytesIO(part.inline_data.data)).convert("RGB").save(out_path, "PNG")
                return True
    except Exception as exc:
        print(f"Gemini profile art error: {exc}", flush=True)
    return False


def _cover(image, size):
    return ImageOps.fit(image.convert("RGB"), size, method=Image.Resampling.LANCZOS)


def _avatar(url):
    if not url:
        return None
    try:
        if str(url).startswith(("/", "file://")):
            path = str(url).removeprefix("file://")
            return Image.open(path).convert("RGB")
        response = requests.get(url, timeout=12)
        response.raise_for_status()
        return Image.open(io.BytesIO(response.content)).convert("RGB")
    except Exception:
        return None


def _mix(a, b, amount):
    return tuple(int(a[i] * (1 - amount) + b[i] * amount) for i in range(3))


def _avatar_palette(avatar):
    fallback = ((124, 58, 237), (236, 72, 153))
    if avatar is None:
        return fallback
    sample = avatar.resize((72, 72)).quantize(colors=12).convert("RGB")
    colors = sample.getcolors(72 * 72) or []
    candidates = []
    for count, rgb in colors:
        r, g, b = [value / 255 for value in rgb]
        _, saturation, value = colorsys.rgb_to_hsv(r, g, b)
        if value < 0.15 or value > 0.96 or saturation < 0.18:
            continue
        candidates.append((count * (0.55 + saturation) * (0.55 + value), rgb))
    if not candidates:
        return fallback
    candidates.sort(reverse=True)
    primary = candidates[0][1]
    secondary = max(
        (item[1] for item in candidates[1:]),
        key=lambda rgb: sum(abs(rgb[i] - primary[i]) for i in range(3)),
        default=_mix(primary, (255, 255, 255), 0.42),
    )
    primary = _mix(primary, (255, 255, 255), 0.12)
    secondary = _mix(secondary, (255, 255, 255), 0.2)
    return primary, secondary


def _fallback_art(seed, primary, secondary):
    image = Image.new("RGB", (W, H), (5, 6, 12))
    pixels = image.load()
    salt = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)
    for y in range(H):
        for x in range(W):
            glow_a = max(0, 1 - (((x - 160) ** 2 + (y - 120) ** 2) ** 0.5) / 920)
            glow_b = max(0, 1 - (((x - 1400) ** 2 + (y - 840) ** 2) ** 0.5) / 760)
            grain = ((x * 13 + y * 7 + salt) % 41) / 41
            pixels[x, y] = tuple(
                int(5 + primary[i] * glow_a * 0.11 + secondary[i] * glow_b * 0.08 + grain * 2)
                for i in range(3)
            )
    return image


def _text(draw, xy, value, size, fill=WHITE, bold=False, anchor=None):
    draw.text(xy, str(value), font=_font(size, bold), fill=fill, anchor=anchor)


def _panel(draw, box, primary, radius=22, alpha=242):
    fill = (*_mix((12, 13, 21), primary, 0.045), alpha)
    outline = (*primary, 72)
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=2)


def _progress(draw, box, ratio, primary, secondary):
    x1, y1, x2, y2 = box
    ratio = max(0, min(1, ratio))
    draw.rounded_rectangle(box, radius=5, fill=(70, 72, 91, 210))
    width = int((x2 - x1) * ratio)
    if width > 4:
        draw.rounded_rectangle((x1, y1, x1 + width, y2), radius=5, fill=(*_mix(primary, secondary, 0.35), 255))


def _paste_round(canvas, image, box, radius):
    x1, y1, x2, y2 = box
    image = _cover(image, (x2 - x1, y2 - y1))
    mask = Image.new("L", image.size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, image.width, image.height), radius=radius, fill=255)
    canvas.paste(image, (x1, y1), mask)


def _league(points):
    if points >= 1600:
        return "PRO", (239, 68, 68)
    if points >= 1350:
        return "DIVISION", (168, 85, 247)
    if points >= 1150:
        return "QUALIFICATIONS", (34, 197, 94)
    return "DEFAULT", (148, 163, 184)


def _match_result(match, user_id):
    if match.get("score_a") is None or match.get("score_b") is None:
        return None
    team_a = str(user_id) in str(match.get("team_a", "")).split(",")
    won_a = match["score_a"] > match["score_b"]
    return "W" if team_a == won_a else "L"


def _map_rows(recent, user_id):
    names = ["Sandstone", "Province", "Rust", "Dune", "Hanami", "Breeze", "Prison"]
    rows = {name: [0, 0] for name in names}
    for match in recent:
        name = match.get("map")
        result = _match_result(match, user_id)
        if name in rows and result:
            rows[name][0 if result == "W" else 1] += 1
    return [(name, *rows[name]) for name in names]


def _compose(player, display_name, avatar_url, recent, art_path):
    avatar = _avatar(avatar_url)
    primary, secondary = _avatar_palette(avatar)

    # The whole theme is derived from the member avatar: blurred backdrop,
    # accent borders, progress bars and result colors all use its palette.
    if avatar:
        backdrop = _cover(avatar, (W, H)).filter(ImageFilter.GaussianBlur(56))
        backdrop = Image.blend(backdrop, Image.new("RGB", (W, H), _mix((3, 4, 9), primary, 0.13)), 0.76)
    else:
        backdrop = _fallback_art(str(player["user_id"]), primary, secondary)
    canvas = backdrop.convert("RGBA")
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rectangle((0, 0, W, H), fill=(2, 3, 8, 188))

    # Avatar-colored ambient glows and restrained geometric accents.
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow, "RGBA")
    gd.ellipse((-260, -300, 720, 620), fill=(*primary, 58))
    gd.ellipse((1030, 580, 1780, 1280), fill=(*secondary, 42))
    glow = glow.filter(ImageFilter.GaussianBlur(105))
    canvas.alpha_composite(glow)
    draw = ImageDraw.Draw(canvas, "RGBA")
    for offset in range(-120, 1700, 230):
        draw.polygon([(offset, 0), (offset + 90, 0), (offset - 170, 250), (offset - 230, 250)], fill=(*primary, 11))

    league, league_color = _league(player["points"])
    short_number = str(player["user_id"])[-5:]
    kills = int(player.get("kills", 0))
    deaths = int(player.get("deaths", 0))
    games = int(player.get("games", 0))
    wins = int(player.get("wins", 0))
    losses = int(player.get("losses", max(0, games - wins)))
    assists = int(player.get("assists", 0))
    mvp = int(player.get("mvp", 0))
    kd = kills / max(1, deaths)
    winrate = wins / max(1, games)
    avg = kills / max(1, games)

    # Header: the requested clear separation between member, ID, league and ELO.
    _panel(draw, (30, 28, 1506, 218), primary, radius=28, alpha=232)
    if avatar:
        _paste_round(canvas, avatar, (52, 49, 210, 197), 28)
    else:
        draw.rounded_rectangle((52, 49, 210, 197), radius=28, fill=(*primary, 70))
        _text(draw, (131, 123), display_name[:1].upper(), 64, WHITE, True, "mm")
    draw.rounded_rectangle((49, 46, 213, 200), radius=31, outline=(*primary, 255), width=4)

    header_cards = [
        ((238, 49, 565, 197), "УЧАСТНИК", display_name[:20], f"Профиль #{short_number}", primary),
        ((583, 49, 890, 197), "STANDOFF 2 ID", player.get("game_id") or "НЕ УКАЗАН", "Игровой аккаунт", secondary),
        ((908, 49, 1213, 197), "ЛИГА", league, "Текущий дивизион", league_color),
        ((1231, 49, 1483, 197), "ELO", str(player["points"]), "Рейтинг игрока", primary),
    ]
    for box, label, value, note, accent in header_cards:
        x1, y1, x2, y2 = box
        draw.rounded_rectangle(box, radius=18, fill=(17, 18, 28, 218), outline=(*accent, 110), width=2)
        draw.rectangle((x1, y1 + 14, x1 + 5, y2 - 14), fill=(*accent, 240))
        _text(draw, (x1 + 22, y1 + 19), label, 16, MUTED, True)
        value_size = 34 if label == "УЧАСТНИК" else 29 if label == "STANDOFF 2 ID" else 23 if label == "ЛИГА" else 31
        _text(draw, (x1 + 22, y1 + 53), value, value_size, WHITE if label != "ЛИГА" else accent, True)
        _text(draw, (x1 + 22, y2 - 31), note, 15, MUTED)

    if LOGO.exists():
        logo = _cover(Image.open(LOGO), (112, 112)).convert("RGBA")
        logo.putalpha(45)
        canvas.alpha_composite(logo, (1380, 724))

    # Main performance area.
    _panel(draw, (30, 240, 1018, 680), primary)
    _text(draw, (62, 270), "ОБЩАЯ СТАТИСТИКА", 27, WHITE, True)
    _text(draw, (62, 307), "Все подтверждённые матчи SEOR FACEIT", 16, MUTED)

    donut_box = (70, 350, 260, 540)
    draw.ellipse(donut_box, outline=(67, 69, 85, 220), width=18)
    kd_ratio = min(1, kd / 2.0)
    draw.arc(donut_box, -90, -90 + 360 * kd_ratio, fill=primary, width=18)
    draw.arc(donut_box, -90 + 360 * kd_ratio, 270, fill=secondary, width=18)
    _text(draw, (165, 434), f"{kd:.2f}", 43, WHITE, True, "mm")
    _text(draw, (165, 478), "K / D", 17, MUTED, True, "mm")
    _text(draw, (69, 568), f"K {kills}", 18, primary, True)
    _text(draw, (180, 568), f"D {deaths}", 18, secondary, True)

    metric_cards = [
        ("МАТЧИ", games, min(1, games / 50)),
        ("ПОБЕДЫ", wins, winrate),
        ("WIN RATE", f"{winrate * 100:.0f}%", winrate),
        ("AVG KILLS", f"{avg:.1f}", min(1, avg / 25)),
        ("ASSISTS", assists, min(1, assists / max(1, games * 8))),
        ("MVP", mvp, min(1, mvp / max(1, games))),
    ]
    for index, (label, value, ratio) in enumerate(metric_cards):
        col, row = index % 3, index // 3
        x, y = 300 + col * 226, 350 + row * 133
        draw.rounded_rectangle((x, y, x + 205, y + 112), radius=15, fill=(27, 28, 40, 228), outline=(*primary, 55), width=1)
        _text(draw, (x + 17, y + 16), label, 15, MUTED, True)
        _text(draw, (x + 188, y + 39), value, 31, WHITE, True, "ra")
        _progress(draw, (x + 17, y + 86, x + 188, y + 94), ratio, primary, secondary)

    # Right: league progress and recent match form.
    _panel(draw, (1038, 240, 1506, 430), primary)
    _text(draw, (1070, 270), "ПРОГРЕСС ЛИГИ", 22, WHITE, True)
    thresholds = [(1000, "DEFAULT"), (1150, "QUALIFICATIONS"), (1350, "DIVISION"), (1600, "PRO")]
    next_item = next(((value, name) for value, name in thresholds if player["points"] < value), None)
    if next_item:
        target, next_name = next_item
        lower = max((value for value, _ in thresholds if value <= player["points"]), default=900)
        ratio = (player["points"] - lower) / max(1, target - lower)
        _text(draw, (1070, 310), league, 29, league_color, True)
        _text(draw, (1472, 314), f"ДО {next_name}", 15, MUTED, True, "ra")
        _progress(draw, (1070, 365, 1472, 378), ratio, primary, secondary)
        _text(draw, (1070, 393), player["points"], 16, primary, True)
        _text(draw, (1472, 393), target, 16, MUTED, True, "ra")
    else:
        _text(draw, (1070, 320), "PRO LEAGUE", 36, league_color, True)
        _text(draw, (1070, 372), "Максимальный дивизион", 17, MUTED)

    _panel(draw, (1038, 450, 1506, 680), primary)
    _text(draw, (1070, 479), "ПОСЛЕДНИЕ МАТЧИ", 22, WHITE, True)
    results = [_match_result(match, player["user_id"]) for match in recent[:20]]
    results = [result for result in results if result]
    for index in range(20):
        col, row = index % 5, index // 5
        x, y = 1070 + col * 80, 526 + row * 38
        result = results[index] if index < len(results) else ""
        accent = (70, 190, 125) if result == "W" else (229, 100, 88) if result == "L" else (59, 61, 75)
        draw.rounded_rectangle((x, y, x + 62, y + 29), radius=7, fill=(25, 26, 37, 235), outline=(*accent, 220), width=2)
        if result:
            _text(draw, (x + 31, y + 14), result, 15, WHITE, True, "mm")

    # Bottom map section, matching the segmented reference while staying compact.
    _panel(draw, (30, 700, 1506, 994), primary)
    _text(draw, (62, 730), "СТАТИСТИКА ПО КАРТАМ", 25, WHITE, True)
    map_rows = _map_rows(recent, player["user_id"])
    for index, (name, map_wins, map_losses) in enumerate(map_rows):
        x = 62 + index * 204
        y = 782
        width = 184
        total = map_wins + map_losses
        map_wr = map_wins / max(1, total)
        draw.rounded_rectangle((x, y, x + width, y + 170), radius=16, fill=(25, 26, 38, 232), outline=(*primary, 58), width=1)
        draw.rounded_rectangle((x + 14, y + 14, x + 54, y + 54), radius=10, fill=(*primary, 42), outline=(*primary, 120), width=1)
        _text(draw, (x + 34, y + 34), name[:1], 20, WHITE, True, "mm")
        _text(draw, (x + 66, y + 19), name.upper(), 15, WHITE, True)
        _text(draw, (x + 66, y + 43), f"{total} матч.", 13, MUTED)
        _text(draw, (x + 16, y + 77), f"{map_wins}W", 23, primary, True)
        _text(draw, (x + 92, y + 77), f"{map_losses}L", 23, secondary, True)
        _progress(draw, (x + 16, y + 119, x + width - 16, y + 128), map_wr, primary, secondary)
        _text(draw, (x + 16, y + 139), f"WR {map_wr * 100:.0f}%", 15, MUTED, True)

    _text(draw, (1474, 972), "SEOR FACEIT", 14, (*primary, 210), True, "ra")
    out = io.BytesIO()
    canvas.convert("RGB").save(out, "PNG", quality=95)
    out.seek(0)
    return out

def build_profile_card_sync(player, display_name, avatar_url, recent):
    CACHE.mkdir(parents=True, exist_ok=True)
    style = os.getenv(
        "PROFILE_IMAGE_PROMPT",
        "Dark competitive esports profile background, black glass panels, subtle futuristic arena lighting, clean negative space, no text, no letters, no numbers, no logos, no UI, premium cinematic, 16:9",
    )
    fingerprint = hashlib.sha256(
        (style + str(player["points"]) + str(player["games"]) + str(player["wins"]) + str(player["kills"]) + str(player["deaths"])).encode()
    ).hexdigest()[:14]
    art_path = CACHE / f"{player['guild_id']}_{player['user_id']}_{fingerprint}.png"
    return _compose(player, display_name, avatar_url, recent, art_path)


async def build_profile_card(player, display_name, avatar_url, recent):
    return await asyncio.to_thread(build_profile_card_sync, player, display_name, avatar_url, recent)
