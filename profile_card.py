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
        return "PROSPECT", (34, 197, 94)
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
    if art_path.exists():
        art = _cover(Image.open(art_path), (W, H))
        tint = Image.new("RGB", (W, H), _mix((5, 6, 12), primary, 0.16))
        art = Image.blend(art, tint, 0.76)
    else:
        art = _fallback_art(str(player["user_id"]), primary, secondary)

    canvas = art.convert("RGBA")
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rectangle((0, 0, W, H), fill=(2, 3, 8, 142))

    # Header inspired by the reference, recolored from the member avatar.
    _panel(draw, (30, 26, 1506, 215), primary, radius=28, alpha=226)
    if avatar:
        banner = _cover(avatar, (1260, 189)).filter(ImageFilter.GaussianBlur(18))
        overlay = Image.new("RGBA", banner.size, (*primary, 42))
        banner = Image.alpha_composite(banner.convert("RGBA"), overlay)
        mask = Image.new("L", banner.size)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, banner.width, banner.height), radius=26, fill=205)
        canvas.paste(banner, (246, 26), mask)
        draw.rectangle((246, 26, 1506, 215), fill=(2, 3, 9, 130))
        _paste_round(canvas, avatar, (48, 43, 220, 199), 28)
        draw.rounded_rectangle((45, 40, 223, 202), radius=30, outline=(*primary, 255), width=4)

    league, league_color = _league(player["points"])
    short_number = str(player["user_id"])[-5:]
    _text(draw, (266, 55), f"#{short_number}", 20, MUTED)
    _text(draw, (266, 83), display_name[:26], 38, WHITE, True)
    _text(draw, (266, 137), f"ID: {player.get('game_id') or 'НЕ УКАЗАН'}", 21, MUTED)
    _text(draw, (266, 174), f"{league} LEAGUE  •  {player['points']} ELO", 19, league_color, True)

    if LOGO.exists():
        logo = _cover(Image.open(LOGO), (164, 164)).convert("RGBA")
        logo.putalpha(105)
        canvas.alpha_composite(logo, (1320, 38))

    # Main statistics panel.
    _panel(draw, (30, 240, 1010, 685), primary)
    _text(draw, (64, 275), "▮▮▮  STATISTIC", 25, WHITE, True)
    kills = player["kills"]
    deaths = player["deaths"]
    games = player["games"]
    wins = player["wins"]
    losses = player.get("losses", max(0, games - wins))
    kd = kills / max(1, deaths)
    winrate = wins / max(1, games)

    donut_box = (75, 335, 255, 515)
    draw.ellipse(donut_box, outline=(72, 74, 91, 210), width=16)
    draw.arc(donut_box, -90, -90 + min(360, kd / 2.0 * 360), fill=primary, width=16)
    draw.arc(donut_box, -90 + min(360, kd / 2.0 * 360), 270, fill=secondary, width=16)
    _text(draw, (165, 423), f"{kd:.2f}", 35, WHITE, True, "mm")
    _text(draw, (286, 354), "KILL / DEATHS", 19, MUTED)
    _text(draw, (286, 398), f"K = {kills}", 26, primary, True)
    _text(draw, (460, 398), f"D = {deaths}", 26, secondary, True)

    level = max(1, min(10, 1 + max(0, player["points"] - 900) // 120))
    _text(draw, (660, 345), "LEVEL", 18, MUTED)
    _text(draw, (930, 346), level, 32, league_color, True, "ra")
    _progress(draw, (660, 400, 940, 412), (player["points"] % 120) / 120, primary, secondary)
    _text(draw, (660, 430), player["points"], 17, primary)
    _text(draw, (940, 430), player["points"] + 120, 17, MUTED, anchor="ra")

    metrics = [
        ("RATING", f"{1 + (winrate - 0.5):.2f}", winrate),
        ("AVG", f"{kills / max(1, games):.1f}", min(1, kills / max(1, games) / 25)),
        ("IMPACT", f"{kd + winrate:.2f}", min(1, (kd + winrate) / 2.5)),
        ("KPR", f"{kills / max(1, games):.2f}", min(1, kills / max(1, games) / 25)),
        ("GAMES", games, min(1, games / 50)),
        ("WIN RATE", f"{winrate * 100:.0f}%", winrate),
    ]
    for index, (label, value, ratio) in enumerate(metrics):
        col, row = index % 3, index // 3
        x, y = 64 + col * 312, 520 + row * 78
        draw.rounded_rectangle((x, y, x + 286, y + 64), radius=13, fill=(27, 28, 39, 225), outline=(*primary, 48), width=1)
        _text(draw, (x + 16, y + 13), label, 15, MUTED)
        _text(draw, (x + 270, y + 12), value, 25, WHITE, True, "ra")
        _progress(draw, (x + 16, y + 46, x + 270, y + 52), ratio, primary, secondary)

    # Right column.
    _panel(draw, (1030, 240, 1506, 430), primary)
    _text(draw, (1062, 274), "LEAGUE", 17, MUTED)
    _text(draw, (1062, 309), league.title(), 33, league_color, True)
    _text(draw, (1062, 363), "ELO", 17, MUTED)
    _text(draw, (1120, 363), player["points"], 22, WHITE, True)
    _text(draw, (1290, 274), "PLAYTIME", 17, MUTED)
    _text(draw, (1290, 309), f"{games * 0.6:.1f}h", 27, WHITE, True)
    _text(draw, (1290, 363), f"{wins}W  {losses}L", 19, MUTED)

    _panel(draw, (1030, 450, 1506, 685), primary)
    _text(draw, (1062, 483), "RECENT MATCHES", 22, WHITE, True)
    results = [_match_result(match, player["user_id"]) for match in recent[:15]]
    results = [result for result in results if result]
    for index in range(15):
        col, row = index % 5, index // 5
        x, y = 1062 + col * 82, 528 + row * 48
        result = results[index] if index < len(results) else ""
        border = primary if result == "W" else secondary if result == "L" else (57, 59, 72)
        draw.rounded_rectangle((x, y, x + 62, y + 35), radius=8, fill=(26, 27, 38, 235), outline=(*border, 230), width=2)
        if result:
            _text(draw, (x + 31, y + 17), result, 18, WHITE, True, "mm")

    # Map statistics.
    _panel(draw, (30, 710, 1506, 995), primary)
    _text(draw, (64, 744), "✦  MAP STATISTIC", 24, WHITE, True)
    map_rows = _map_rows(recent, player["user_id"])
    for index, (name, map_wins, map_losses) in enumerate(map_rows):
        col, row = index % 4, index // 4
        x, y = 64 + col * 354, 792 + row * 92
        width = 326
        draw.rounded_rectangle((x, y, x + width, y + 76), radius=14, fill=(26, 27, 38, 235), outline=(*primary, 55), width=1)
        total = map_wins + map_losses
        map_wr = map_wins / max(1, total)
        _text(draw, (x + 18, y + 13), name, 17, WHITE, True)
        _text(draw, (x + 18, y + 42), f"W {map_wins}   L {map_losses}", 15, MUTED)
        _text(draw, (x + width - 18, y + 42), f"WR {map_wr * 100:.0f}%", 15, primary, True, "ra")

    # Avatar-palette signature.
    draw.rounded_rectangle((1378, 944, 1476, 973), radius=14, fill=(*primary, 45), outline=(*primary, 150), width=1)
    _text(draw, (1427, 958), "SEOR", 15, WHITE, True, "mm")

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
    if not art_path.exists():
        _generate_art(style, art_path)
    return _compose(player, display_name, avatar_url, recent, art_path)


async def build_profile_card(player, display_name, avatar_url, recent):
    return await asyncio.to_thread(build_profile_card_sync, player, display_name, avatar_url, recent)
