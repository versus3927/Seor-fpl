import asyncio
import colorsys
import hashlib
import io
import os
from pathlib import Path

import requests
from elo_levels import elo_level, elo_bounds
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
CACHE = Path("data/profile_art")
LOGO = ROOT / "assets" / "seor_logo.png"
W, H = 1080, 1600
WHITE = (242, 243, 248)
MUTED = (165, 168, 184)


def _font(size, bold=False):
    paths = [
        str(ROOT / "assets" / "fonts" / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")),
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
    avatar=_avatar(avatar_url); primary,secondary=_avatar_palette(avatar)
    bg=_cover(avatar,(W,H)).filter(ImageFilter.GaussianBlur(72)) if avatar else _fallback_art(str(player["user_id"]),primary,secondary)
    canvas=bg.convert("RGBA"); draw=ImageDraw.Draw(canvas,"RGBA")
    draw.rectangle((0,0,W,H),fill=(3,4,10,205))
    # Neon shards and 3D depth layers.
    for i in range(-200,1300,190):
        draw.polygon([(i,0),(i+90,0),(i-120,290),(i-180,290)],fill=(*primary,38))
        draw.polygon([(i+18,0),(i+55,0),(i-145,290),(i-175,290)],fill=(*secondary,24))
    def card(box,accent=primary,r=24):
        x1,y1,x2,y2=box
        draw.rounded_rectangle((x1+10,y1+14,x2+10,y2+14),radius=r,fill=(0,0,0,125))
        draw.rounded_rectangle(box,radius=r,fill=(15,16,27,235),outline=(*accent,175),width=2)
        draw.line((x1+24,y1+3,x2-24,y1+3),fill=(*_mix(accent,(255,255,255),.35),180),width=3)
    league,league_color=_league(player["points"])
    games=int(player.get('games',0)); wins=int(player.get('wins',0)); losses=int(player.get('losses',max(0,games-wins)))
    kills=int(player.get('kills',0)); deaths=int(player.get('deaths',0)); assists=int(player.get('assists',0)); mvp=int(player.get('mvp',0))
    kd=kills/max(1,deaths); wr=wins/max(1,games); avg=kills/max(1,games)
    # Hero.
    card((32,34,1048,310),primary,30)
    if avatar: _paste_round(canvas,avatar,(62,68,278,278),34)
    draw.rounded_rectangle((58,64,282,282),radius=38,outline=(*primary,255),width=6)
    _text(draw,(320,70),"ПРОФИЛЬ УЧАСТНИКА",23,MUTED,True)
    _text(draw,(320,108),display_name[:19],58,WHITE,True)
    _text(draw,(320,185),f"#{str(player['user_id'])[-5:]}",25,primary,True)
    _text(draw,(320,230),"SEOR FACEIT",22,MUTED,True)
    # 3D league badge.
    cx,cy=910,170
    for rad,col,off in [(92,(0,0,0),14),(86,primary,8),(76,league_color,2),(62,(15,16,26),0)]:
        pts=[(cx+rad*__import__('math').cos(__import__('math').radians(60*k-30)),cy+off+rad*__import__('math').sin(__import__('math').radians(60*k-30))) for k in range(6)]
        draw.polygon(pts,fill=(*col,235) if col!=(0,0,0) else (0,0,0,130),outline=(*_mix(col,(255,255,255),.25),255) if col!=(0,0,0) else None)
    level=elo_level(player["points"])
    _text(draw,(cx,cy-5),str(level),52,WHITE,True,"mm")
    _text(draw,(cx,cy+52),"LVL",17,MUTED,True,"mm")
    # Separate identity sections.
    info=[("УЧАСТНИК",display_name[:16],primary),("STANDOFF 2 ID",player.get('game_id') or 'НЕ УКАЗАН',secondary),("ЛИГА",league,league_color)]
    for i,(label,value,accent) in enumerate(info):
        x=32+i*340; card((x,340,x+322,475),accent,20)
        _text(draw,(x+22,362),label,19,MUTED,True)
        size=31 if label!='ЛИГА' else 25
        _text(draw,(x+22,407),value,size,accent if label=='ЛИГА' else WHITE,True)
    # Rating and performance.
    card((32,505,1048,895),primary,28)
    _text(draw,(64,535),"СТАТИСТИКА",34,WHITE,True)
    _text(draw,(64,580),"Подтверждённые матчи и рейтинг",19,MUTED)
    box=(75,635,285,845); draw.ellipse(box,outline=(65,67,83,230),width=20)
    draw.arc(box,-90,-90+360*min(1,kd/2),fill=primary,width=20)
    draw.arc(box,-90+360*min(1,kd/2),270,fill=secondary,width=20)
    _text(draw,(180,730),f"{kd:.2f}",48,WHITE,True,"mm"); _text(draw,(180,782),"K / D",20,MUTED,True,"mm")
    metrics=[('ELO',player['points']),('МАТЧИ',games),('ПОБЕДЫ',wins),('WIN RATE',f'{wr*100:.0f}%'),('AVG',f'{avg:.1f}'),('MVP',mvp),('KILLS',kills),('ASSISTS',assists)]
    for i,(label,val) in enumerate(metrics):
        col=i%4; row=i//4; x=325+col*174; y=630+row*120
        draw.rounded_rectangle((x,y,x+156,y+100),radius=15,fill=(30,31,45,238),outline=(*primary,65),width=1)
        _text(draw,(x+14,y+14),label,16,MUTED,True); _text(draw,(x+142,y+48),val,30,WHITE,True,'ra')
        _progress(draw,(x+14,y+81,x+142,y+88),min(1,float(val.strip('%'))/100) if isinstance(val,str) and val.endswith('%') else min(1,(i+2)/10),primary,secondary)
    # FACEIT-style Elo level progress.
    card((32,925,1048,1075),league_color,24)
    level,level_floor,next_level_floor,ratio=elo_bounds(player["points"])
    _text(draw,(64,952),"ПРОГРЕСС ELO",23,MUTED,True); _text(draw,(64,990),f"LEVEL {level}",34,league_color,True)
    target_label=next_level_floor if next_level_floor is not None else "MAX"
    _progress(draw,(545,975,1005,991),ratio,primary,secondary); _text(draw,(545,1010),player['points'],19,primary,True); _text(draw,(1005,1010),target_label,19,MUTED,True,'ra')
    # Recent matches.
    card((32,1105,1048,1265),primary,24); _text(draw,(64,1132),"ПОСЛЕДНИЕ МАТЧИ",26,WHITE,True)
    results=[_match_result(m,player['user_id']) for m in recent[:12]]; results=[x for x in results if x]
    for i in range(12):
        x=64+i*80; r=results[i] if i<len(results) else ''; col=(70,190,125) if r=='W' else (229,100,88) if r=='L' else (60,62,78)
        draw.rounded_rectangle((x,1182,x+61,1228),radius=10,fill=(25,26,38,240),outline=(*col,240),width=3)
        if r:_text(draw,(x+30,1204),r,22,WHITE,True,'mm')
    # Maps: large two-column cards.
    _text(draw,(40,1302),"КАРТЫ",30,WHITE,True)
    rows=_map_rows(recent,player['user_id'])
    for i,(name,mw,ml) in enumerate(rows):
        col=i%2; row=i//2; x=32+col*516; y=1345+row*62
        draw.rounded_rectangle((x,y,x+498,y+50),radius=12,fill=(23,24,36,238),outline=(*primary,70),width=1)
        total=mw+ml; mapwr=mw/max(1,total)
        _text(draw,(x+16,y+13),name.upper(),18,WHITE,True); _text(draw,(x+245,y+13),f"{mw}W  {ml}L",18,primary,True)
        _text(draw,(x+472,y+13),f"WR {mapwr*100:.0f}%",18,MUTED,True,'ra')
    _text(draw,(1038,1580),"SEOR FACEIT",16,(*primary,220),True,'ra')
    out=io.BytesIO(); canvas.convert('RGB').save(out,'PNG',quality=95); out.seek(0); return out

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
