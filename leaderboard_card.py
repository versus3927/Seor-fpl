import io
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from elo_levels import elo_level

ROOT=Path(__file__).resolve().parent
W,H=1200,1400
BG=(4,3,12); PANEL=(14,12,27); PANEL_2=(22,19,38)
PURPLE=(132,74,255); VIOLET=(190,123,255); CYAN=(70,210,242)
WHITE=(247,245,252); MUTED=(164,158,184); GREEN=(62,210,137)
LEAGUE_COLORS={'Default':(190,194,210),'Qualifications':(55,218,145),'Division':(170,82,255),'Pro':(255,70,101)}
LEAGUE_NAMES={'Default':'DEFAULT LEAGUE','Qualifications':'DOMINION RISE','Division':'DOMINION ASCEND','Pro':'PRO LEAGUE'}


def font(size,bold=False):
    local=ROOT/'assets'/'fonts'/('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf')
    system=Path('/usr/share/fonts/google-noto-vf/NotoSans[wght].ttf')
    path=local if local.exists() else system
    return ImageFont.truetype(str(path),size) if path.exists() else ImageFont.load_default()


def avatar(url,size):
    try:
        response=requests.get(str(url),timeout=8); response.raise_for_status()
        return ImageOps.fit(Image.open(io.BytesIO(response.content)).convert('RGB'),(size,size),Image.Resampling.LANCZOS)
    except Exception:
        image=Image.new('RGB',(size,size),(28,23,48)); d=ImageDraw.Draw(image)
        d.ellipse((size*.28,size*.14,size*.72,size*.58),fill=(80,69,105))
        d.rounded_rectangle((size*.17,size*.57,size*.83,size*.96),radius=int(size*.2),fill=(80,69,105))
        return image


def round_paste(canvas,image,xy,size,radius):
    mask=Image.new('L',(size,size)); ImageDraw.Draw(mask).rounded_rectangle((0,0,size-1,size-1),radius=radius,fill=255)
    canvas.paste(image,xy,mask)


def brand_mark(draw,x,y):
    draw.polygon([(x,y+13),(x+18,y+38),(x+40,y+4),(x+62,y+38),(x+80,y+13),(x+69,y+64),(x+11,y+64)],fill=(*VIOLET,245),outline=(*WHITE,150))
    draw.rounded_rectangle((x+12,y+72,x+68,y+124),radius=15,fill=(*PURPLE,100),outline=(*CYAN,220),width=3)
    draw.text((x+40,y+98),'D',font=font(27,True),anchor='mm',fill=WHITE)


def panel(draw,box,radius=28,fill=PANEL,outline=(63,48,96),width=2):
    x1,y1,x2,y2=box
    draw.rounded_rectangle((x1+8,y1+10,x2+8,y2+10),radius=radius,fill=(0,0,0,110))
    draw.rounded_rectangle(box,radius=radius,fill=(*fill,245),outline=(*outline,220),width=width)


def build_leaderboard(rows,league):
    league_color=LEAGUE_COLORS.get(league,VIOLET); league_name=LEAGUE_NAMES.get(league,str(league).upper())
    canvas=Image.new('RGBA',(W,H),(*BG,255)); d=ImageDraw.Draw(canvas,'RGBA')
    for y in range(H):
        t=y/H; d.line((0,y,W,y),fill=(4+int(3*t),3+int(3*t),12+int(11*t),255))
    glow=Image.new('RGBA',(W,H),(0,0,0,0)); gd=ImageDraw.Draw(glow)
    gd.ellipse((-300,-260,810,650),fill=(*PURPLE,78)); gd.ellipse((650,780,1450,1550),fill=(*CYAN,22))
    canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(145))); d=ImageDraw.Draw(canvas,'RGBA')
    for x in range(-180,1400,210): d.polygon([(x,0),(x+78,0),(x-88,230),(x-155,230)],fill=(*VIOLET,20))

    panel(d,(38,34,1162,220),32,fill=(9,8,20),outline=PURPLE,width=3)
    brand_mark(d,68,59)
    d.text((178,69),'DOMINION FACEIT',font=font(31,True),fill=WHITE)
    d.text((178,113),league_name,font=font(20,True),fill=(*league_color,255))
    d.text((178,151),'COMPETITIVE LEADERBOARD',font=font(14,True),fill=(*MUTED,255))
    d.text((1118,82),'TOP 10',font=font(45,True),anchor='ra',fill=WHITE)
    d.text((1118,143),'ELO  •  RANK  •  RECORD',font=font(15,True),anchor='ra',fill=(*VIOLET,255))

    # Podium layout borrowed from the previous server: three featured players above the list.
    panel(d,(38,250,1162,733),32,fill=PANEL,outline=(59,45,91))
    positions={1:(600,300,230),2:(300,348,182),3:(900,372,158)}
    medals={1:(255,214,92),2:(202,211,229),3:(207,132,79)}
    for rank in (2,3,1):
        if len(rows)<rank: continue
        item=rows[rank-1]; cx,avatar_y,podium_h=positions[rank]; medal=medals[rank]
        size=132 if rank==1 else 108
        av=avatar(item.get('avatar_url'),size); round_paste(canvas,av,(cx-size//2,avatar_y),size,size//3)
        d.rounded_rectangle((cx-size//2-5,avatar_y-5,cx+size//2+5,avatar_y+size+5),radius=size//3+5,outline=(*medal,255),width=5)
        base=avatar_y+size+28
        d.polygon([(cx-132,base),(cx+132,base),(cx+110,base+podium_h),(cx-110,base+podium_h)],fill=(*PANEL_2,255),outline=(*medal,205))
        d.rounded_rectangle((cx-35,base-23,cx+35,base+25),radius=15,fill=(*medal,255))
        d.text((cx,base+1),f'#{rank}',font=font(21,True),anchor='mm',fill=(12,10,21,255))
        d.text((cx,base+62),str(item['name'])[:16],font=font(25,True),anchor='mm',fill=WHITE)
        d.text((cx,base+105),f"{int(item['points'])} ELO",font=font(25,True),anchor='mm',fill=(*league_color,255))
        d.text((cx,base+142),f"{elo_level(int(item['points']))}",font=font(22,True),anchor='mm',fill=(*VIOLET,255))
        d.text((cx,base+178),f"{int(item.get('wins',0))}W  •  {int(item.get('games',0))} MATCHES",font=font(14,True),anchor='mm',fill=(*MUTED,255))

    if not rows:
        d.text((600,495),'В этой лиге пока нет игроков',font=font(27,True),anchor='mm',fill=(*MUTED,255))

    # Places 4–10 retain the compact rows from the previous server.
    start_y=760
    for index,item in enumerate(rows[3:10],4):
        y=start_y+(index-4)*76
        d.rounded_rectangle((44,y,1156,y+63),radius=18,fill=(*PANEL_2,246),outline=(*PURPLE,105),width=1)
        d.rounded_rectangle((53,y+8,103,y+55),radius=14,fill=(*PURPLE,38),outline=(*PURPLE,190),width=2)
        d.text((78,y+32),f'#{index}',font=font(16,True),anchor='mm',fill=(*VIOLET,255))
        size=45; av=avatar(item.get('avatar_url'),size); round_paste(canvas,av,(121,y+9),size,14)
        d.text((188,y+31),str(item['name'])[:25],font=font(20,True),anchor='lm',fill=WHITE)
        d.text((690,y+31),f"{int(item.get('wins',0))}W / {int(item.get('games',0))}G",font=font(16,True),anchor='rm',fill=(*GREEN,255))
        d.text((885,y+31),f"{elo_level(int(item['points']))}",font=font(20,True),anchor='rm',fill=(*VIOLET,255))
        d.text((1122,y+31),f"{int(item['points'])} ELO",font=font(21,True),anchor='rm',fill=(*league_color,255))

    d.text((600,1360),'DOMINION FACEIT  •  RISE  •  ASCEND  •  DOMINATE',font=font(15,True),anchor='mm',fill=(*VIOLET,245))
    out=io.BytesIO(); canvas.convert('RGB').save(out,'PNG',quality=96); out.seek(0); return out
