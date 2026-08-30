import asyncio
import hashlib
import io
import os
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

CACHE = Path("data/profile_art")
W, H = 1536, 1024
PURPLE = (146, 43, 255)
BG = (6, 5, 13)
PANEL = (10, 8, 18, 238)
TEXT = (235, 232, 242)
MUTED = (174, 168, 190)


def _font(size, bold=False):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in paths:
        try: return ImageFont.truetype(path, size)
        except OSError: pass
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


def _fallback_art(seed):
    image = Image.new("RGB", (W, H), BG)
    px = image.load()
    salt = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)
    for y in range(H):
        for x in range(W):
            glow = max(0, 1 - (((x-250)**2 + (y-190)**2) ** .5) / 850)
            wave = ((x * 13 + y * 7 + salt) % 97) / 97
            px[x,y] = (int(6+13*glow), int(5+4*glow), int(13+42*glow+5*wave))
    return image


def _cover(image, size):
    return ImageOps.fit(image.convert("RGB"), size, method=Image.Resampling.LANCZOS)


def _avatar(url):
    if not url: return None
    try:
        r=requests.get(url,timeout=12); r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception:
        return None


def _compose(player, display_name, avatar_url, recent, art_path):
    if art_path.exists():
        art=_cover(Image.open(art_path),(W,H))
        art=Image.blend(art,Image.new("RGB",(W,H),BG),0.72)
    else:
        art=_fallback_art(str(player["user_id"]))
    canvas=art.convert("RGBA"); d=ImageDraw.Draw(canvas,"RGBA")
    d.rectangle((0,0,W,H),fill=(4,3,10,165))
    def panel(box, radius=18): d.rounded_rectangle(box,radius,fill=PANEL,outline=(129,46,210,85),width=2)
    panel((350,150,940,425)); panel((970,150,1510,355)); panel((970,375,1510,510)); panel((970,530,1510,715))
    panel((30,445,955,700)); panel((30,720,955,1000))
    d.ellipse((70,175,315,420),outline=PURPLE,width=6)
    av=_avatar(avatar_url)
    if av:
        av=_cover(av,(225,225)); mask=Image.new("L",(225,225)); ImageDraw.Draw(mask).ellipse((0,0,225,225),fill=255)
        canvas.paste(av,(80,185),mask)
    title=_font(24); big=_font(30); huge=_font(42,bold=True); small=_font(16); label=_font(20)
    league="DEFAULT"
    if player["points"]>=1600: league="PRO"
    elif player["points"]>=1350: league="DIVISION"
    elif player["points"]>=1150: league="PROSPECT"
    d.text((365,175),display_name.upper()[:24],font=small,fill=MUTED)
    d.text((365,230),f"ID: {player.get('game_id') or 'НЕ УКАЗАН'}",font=big,fill=TEXT)
    d.text((365,300),f"{league} LEAGUE",font=huge,fill=PURPLE)
    d.text((365,365),f"ELO: {player['points']}",font=small,fill=TEXT)
    d.text((1010,180),"PLAYTIME",font=label,fill=MUTED); d.text((1010,220),f"{player['games']*0.6:.1f}h",font=small,fill=TEXT)
    d.text((1010,280),"GAMES",font=label,fill=MUTED); d.text((1010,320),str(player['games']),font=small,fill=TEXT)
    d.text((1270,280),"WINS",font=label,fill=MUTED); d.text((1270,320),str(player['wins']),font=small,fill=TEXT)
    kills=player['kills']; deaths=player['deaths']; kd=kills/max(1,deaths); winrate=100*player['wins']/max(1,player['games'])
    stats=[("KILLS",kills),("ASSISTS",0),("DEATHS",deaths),("K/D",f"{kd:.2f}"),("AVG",f"{kills/max(1,player['games']):.2f}"),("KPR",f"{kills/max(1,player['games']):.2f}"),("IMPACT",f"{(kd+winrate/100):.2f}"),("WINRATE",f"{winrate:.0f}%")]
    for i,(name,value) in enumerate(stats):
        x=80+(i%4)*220; y=490+(i//4)*110
        d.text((x,y),name,font=label,fill=MUTED); d.text((x,y+42),str(value),font=small,fill=TEXT)
    d.text((65,748),"MAP STATISTIC",font=big,fill=TEXT)
    maps=["Sandstone","Rust","Province","Prison","Hanami","Dune"]
    for i,name in enumerate(maps):
        x=340+(i%3)*205; y=770+(i//3)*105
        d.rounded_rectangle((x,y,x+185,y+86),12,fill=(8,6,15,245),outline=(129,46,210,180),width=2)
        d.text((x+12,y+12),name,font=small,fill=TEXT); d.text((x+12,y+42),"W:0 L:0  K/D:0.00",font=_font(13),fill=MUTED)
    d.text((1000,405),"RECENT MATCHES",font=label,fill=TEXT)
    if recent:
        lines=[]
        for m in recent[:2]: lines.append(f"#{m['id']}  {m['map']}  {m['score_a'] if m['score_a'] is not None else '?'}:{m['score_b'] if m['score_b'] is not None else '?'}")
        d.multiline_text((1000,450),"\n".join(lines),font=small,fill=MUTED,spacing=8)
    else: d.text((1000,455),"No matches yet",font=small,fill=MUTED)
    d.text((1000,560),f"TOP PLAYERS · {league.title()} League",font=label,fill=TEXT)
    d.text((1010,620),"#1",font=label,fill=PURPLE); d.text((1070,620),display_name[:18],font=label,fill=TEXT); d.text((1370,620),f"{player['points']} ELO",font=small,fill=TEXT)
    d.text((1370,960),"SEOR",font=_font(18,bold=True),fill=PURPLE)
    out=io.BytesIO(); canvas.convert("RGB").save(out,"PNG",quality=95); out.seek(0); return out


def build_profile_card_sync(player, display_name, avatar_url, recent):
    CACHE.mkdir(parents=True,exist_ok=True)
    style=os.getenv("PROFILE_IMAGE_PROMPT","Dark competitive esports profile background, black and deep violet, subtle futuristic arena lighting, clean negative space, no text, no letters, no numbers, no logos, no UI, premium cinematic, 16:9")
    fingerprint=hashlib.sha256((style+str(player['points'])+str(player['games'])+str(player['wins'])+str(player['kills'])+str(player['deaths'])).encode()).hexdigest()[:14]
    art_path=CACHE/f"{player['guild_id']}_{player['user_id']}_{fingerprint}.png"
    if not art_path.exists():
        _generate_art(style,art_path)
    return _compose(player,display_name,avatar_url,recent,art_path)


async def build_profile_card(player, display_name, avatar_url, recent):
    return await asyncio.to_thread(build_profile_card_sync,player,display_name,avatar_url,recent)
