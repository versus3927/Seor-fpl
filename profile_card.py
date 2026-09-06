import asyncio
import io
import math
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from elo_levels import elo_bounds, elo_level

ROOT=Path(__file__).resolve().parent
W,H=1200,1500
BG=(5,4,14); PANEL=(17,14,35); PURPLE=(132,74,255); VIOLET=(192,132,255); CYAN=(70,220,255)
WHITE=(246,244,255); MUTED=(166,158,192); GREEN=(65,220,145); RED=(255,91,119)


def font(size,bold=False):
    paths=[ROOT/'assets'/'fonts'/('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'),Path('/usr/share/fonts/google-noto-vf/NotoSans[wght].ttf')]
    for path in paths:
        if path.exists(): return ImageFont.truetype(str(path),size)
    return ImageFont.load_default()


def fetch_image(url,size):
    try:
        response=requests.get(str(url),timeout=10); response.raise_for_status()
        return ImageOps.fit(Image.open(io.BytesIO(response.content)).convert('RGB'),size,Image.Resampling.LANCZOS)
    except Exception:
        return Image.new('RGB',size,(29,24,54))


def logo(size=130):
    path=ROOT/'assets'/'dominion-logo.png'
    if not path.exists(): return None
    return ImageOps.fit(Image.open(path).convert('RGBA'),(size,size),Image.Resampling.LANCZOS)


def panel(draw,box,r=28,outline=(111,69,190),fill=PANEL):
    x1,y1,x2,y2=box
    draw.rounded_rectangle((x1+8,y1+12,x2+8,y2+12),radius=r,fill=(0,0,0,95))
    draw.rounded_rectangle(box,radius=r,fill=(*fill,235),outline=(*outline,190),width=2)


def text(draw,xy,value,size,color=WHITE,bold=False,anchor=None):
    draw.text(xy,str(value),font=font(size,bold),fill=(*color,255),anchor=anchor)


def progress(draw,box,ratio):
    x1,y1,x2,y2=box; ratio=max(0,min(1,float(ratio)))
    draw.rounded_rectangle(box,radius=10,fill=(48,39,76,255))
    if ratio>0:
        draw.rounded_rectangle((x1,y1,max(x1+16,x1+(x2-x1)*ratio),y2),radius=10,fill=(*PURPLE,255))
        draw.ellipse((max(x1,x1+(x2-x1)*ratio-8),y1-4,min(x2,x1+(x2-x1)*ratio+8),y2+4),fill=(*CYAN,255))


def round_paste(canvas,image,box,radius):
    x1,y1,x2,y2=box; image=ImageOps.fit(image,(x2-x1,y2-y1),Image.Resampling.LANCZOS)
    mask=Image.new('L',image.size); ImageDraw.Draw(mask).rounded_rectangle((0,0,*image.size),radius=radius,fill=255)
    canvas.paste(image,(x1,y1),mask)


def match_result(match,user_id):
    if match.get('score_a') is None or match.get('score_b') is None: return None
    team_a=str(user_id) in str(match.get('team_a','')).split(',')
    won_a=match['score_a']>match['score_b']
    return 'W' if team_a==won_a else 'L'


def build_profile_card_sync(player,display_name,avatar_url,recent):
    canvas=Image.new('RGBA',(W,H),(*BG,255)); d=ImageDraw.Draw(canvas,'RGBA')
    # Dominion neon background.
    for y in range(H):
        t=y/H; d.line((0,y,W,y),fill=(7+int(18*t),5+int(8*t),19+int(30*t),255))
    glow=Image.new('RGBA',(W,H),(0,0,0,0)); gd=ImageDraw.Draw(glow)
    gd.ellipse((-280,-220,780,700),fill=(*PURPLE,90)); gd.ellipse((620,700,1450,1600),fill=(*CYAN,35))
    canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(130))); d=ImageDraw.Draw(canvas,'RGBA')
    for x in range(-200,1400,210): d.polygon([(x,0),(x+90,0),(x-130,330),(x-210,330)],fill=(*VIOLET,25))

    # Brand header.
    brand=logo(112)
    if brand: canvas.alpha_composite(brand,(48,38))
    text(d,(180,55),'DOMINION',38,WHITE,True); text(d,(180,102),'FACEIT • COMPETITIVE NETWORK',18,VIOLET,True)
    text(d,(1148,76),'PLAYER ID  '+str(player['user_id'])[-6:],17,MUTED,True,'ra')

    # Hero identity.
    panel(d,(42,180,1158,520),34)
    avatar=fetch_image(avatar_url,(280,280)); round_paste(canvas,avatar,(78,216,350,488),48)
    d.rounded_rectangle((72,210,356,494),radius=54,outline=(*PURPLE,255),width=6)
    text(d,(396,232),'PLAYER PROFILE',19,VIOLET,True)
    text(d,(396,274),display_name[:21],50,WHITE,True)
    points=int(player.get('points',0))
    league='Pro' if points>=1600 else 'Division' if points>=1350 else 'Qualifications' if points>=1150 else 'Default'
    text(d,(396,346),f"STANDOFF 2 ID  •  {player.get('game_id') or 'NOT LINKED'}",20,MUTED,True)
    text(d,(396,396),f"{league.upper()} LEAGUE",22,CYAN,True)
    level=elo_level(player['points'])
    cx,cy=1010,350
    for radius,color,alpha in [(108,PURPLE,70),(87,VIOLET,210),(72,(11,9,27),255)]:
        pts=[(cx+radius*math.cos(math.radians(60*i-30)),cy+radius*math.sin(math.radians(60*i-30))) for i in range(6)]
        d.polygon(pts,fill=(*color,alpha),outline=(*CYAN,170))
    text(d,(cx,cy-8),level,60,WHITE,True,'mm'); text(d,(cx,cy+47),'LEVEL',16,MUTED,True,'mm')

    games=int(player.get('games',0)); wins=int(player.get('wins',0)); losses=int(player.get('losses',max(0,games-wins)))
    kills=int(player.get('kills',0)); deaths=int(player.get('deaths',0)); assists=int(player.get('assists',0)); mvp=int(player.get('mvp',0))
    kd=kills/max(1,deaths); wr=wins/max(1,games)*100; avg=kills/max(1,games)

    # Elo focus.
    panel(d,(42,550,1158,760),30,outline=PURPLE)
    text(d,(78,584),'RATING',18,MUTED,True); text(d,(78,622),f"{player['points']} ELO",56,WHITE,True)
    level,floor,next_floor,ratio=elo_bounds(player['points'])
    target='MAX LEVEL' if next_floor is None else f'{next_floor-player["points"]} ELO ДО LVL {level+1}'
    text(d,(1118,607),target,19,CYAN,True,'ra')
    progress(d,(78,696,1118,718),ratio)
    text(d,(78,730),f'LVL {level} • {floor} ELO',16,MUTED,True)
    text(d,(1118,730),('2000+ ELO' if next_floor is None else f'{next_floor} ELO'),16,MUTED,True,'ra')

    # Performance grid.
    text(d,(44,807),'PERFORMANCE',25,WHITE,True)
    stats=[('MATCHES',games),('WINS',wins),('LOSSES',losses),('WIN RATE',f'{wr:.0f}%'),('K / D',f'{kd:.2f}'),('AVG KILLS',f'{avg:.1f}'),('ASSISTS',assists),('MVP',mvp)]
    for i,(label,value) in enumerate(stats):
        col=i%4; row=i//4; x=42+col*284; y=850+row*150
        panel(d,(x,y,x+264,y+126),22,outline=(80,58,128),fill=(15,13,31))
        text(d,(x+20,y+20),label,15,MUTED,True); text(d,(x+20,y+55),value,34,WHITE,True)

    # Form strip.
    panel(d,(42,1170,1158,1370),28,outline=CYAN)
    text(d,(76,1203),'RECENT FORM',20,MUTED,True)
    results=[match_result(match,player['user_id']) for match in recent[:10]]; results=[x for x in results if x]
    for i in range(10):
        x=76+i*103; result=results[i] if i<len(results) else '—'; color=GREEN if result=='W' else RED if result=='L' else (65,59,84)
        d.rounded_rectangle((x,1260,x+76,1324),radius=17,fill=(*color,55),outline=(*color,230),width=3)
        text(d,(x+38,1292),result,25,WHITE,True,'mm')
    text(d,(600,1440),'DOMINION FACEIT  •  OWN THE RANK',17,VIOLET,True,'mm')
    out=io.BytesIO(); canvas.convert('RGB').save(out,'PNG',quality=96); out.seek(0); return out


async def build_profile_card(player,display_name,avatar_url,recent):
    return await asyncio.to_thread(build_profile_card_sync,player,display_name,avatar_url,recent)
