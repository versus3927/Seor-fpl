import io
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
import requests
from elo_levels import elo_level

ROOT=Path(__file__).resolve().parent
W,H=1080,1280
PALETTES={
 "Default":((100,116,139),(56,189,248)),
 "Qualifications":((34,197,94),(250,204,21)),
 "Division":((168,85,247),(236,72,153)),
 "Pro":((239,68,68),(249,115,22)),
}

def font(size,bold=False):
 p=ROOT/'assets'/'fonts'/('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf')
 return ImageFont.truetype(str(p),size)

def avatar(url,size):
 try:
  r=requests.get(str(url),timeout=10); r.raise_for_status()
  im=Image.open(io.BytesIO(r.content)).convert('RGB')
  return ImageOps.fit(im,(size,size),method=Image.Resampling.LANCZOS)
 except Exception:
  return Image.new('RGB',(size,size),(30,32,46))

def round_paste(canvas,im,xy,size,radius):
 mask=Image.new('L',(size,size)); ImageDraw.Draw(mask).rounded_rectangle((0,0,size,size),radius=radius,fill=255)
 canvas.paste(im,xy,mask)

def build_leaderboard(rows,league):
 primary,secondary=PALETTES.get(league,PALETTES['Default'])
 bg=Image.new('RGB',(W,H),(5,7,14)); d=ImageDraw.Draw(bg)
 for y in range(H):
  t=y/H; d.line((0,y,W,y),fill=(int(7+primary[0]*.10*(1-t)),int(8+primary[1]*.08*(1-t)),int(16+secondary[2]*.08*t)))
 glow=Image.new('RGBA',(W,H),(0,0,0,0)); gd=ImageDraw.Draw(glow)
 gd.ellipse((-260,-230,660,560),fill=(*primary,85)); gd.ellipse((650,700,1370,1450),fill=(*secondary,55)); glow=glow.filter(ImageFilter.GaussianBlur(120))
 canvas=bg.convert('RGBA'); canvas.alpha_composite(glow); d=ImageDraw.Draw(canvas,'RGBA')
 for x in range(-120,1200,170): d.polygon([(x,0),(x+75,0),(x-80,220),(x-135,220)],fill=(*primary,28))
 # Header
 d.rounded_rectangle((30,28,1050,214),radius=30,fill=(14,16,28,235),outline=(*primary,190),width=3)
 d.text((65,62),'SEOR FACEIT',font=font(22,True),fill=(*primary,255))
 d.text((65,99),f'ТОП ЛИГИ {league.upper()}',font=font(43,True),fill=(246,247,252,255))
 d.text((65,160),'В рейтинге только участники с ролью этой лиги',font=font(18),fill=(169,172,190,255))
 # 3D trophy
 for off,col in [(14,(0,0,0)),(8,secondary),(0,primary)]:
  d.rounded_rectangle((855+off,55+off,996+off,187+off),radius=34,fill=(*col,210),outline=(255,255,255,90),width=2)
 # Vector crown avoids missing emoji fonts on Railway.
 d.polygon([(878,103),(900,132),(925,91),(950,132),(974,103),(963,157),(888,157)],fill=(255,220,92,255),outline=(255,247,190,255))
 d.rounded_rectangle((888,151,963,166),radius=6,fill=(249,115,22,255))
 d.ellipse((918,73,932,87),fill=(255,236,128,255))
 # Podium top 3
 top=rows[:3]; centers=[540,250,830]; heights=[245,190,165]
 for rank,(item,cx,h) in enumerate(zip(top,centers,heights),1):
  actual_rank=[1,2,3][rank-1]
  size=116 if actual_rank==1 else 94
  av=avatar(item.get('avatar_url'),size); round_paste(canvas,av,(cx-size//2,272-size//2),size,size//3)
  d.rounded_rectangle((cx-size//2-4,272-size//2-4,cx+size//2+4,272+size//2+4),radius=size//3+4,outline=(*primary,255),width=4)
  base_y=350
  d.polygon([(cx-105,base_y),(cx+105,base_y),(cx+88,base_y+h),(cx-88,base_y+h)],fill=(22,24,38,245),outline=(*secondary,170))
  d.text((cx,base_y+34),f'#{actual_rank}',font=font(28,True),anchor='mm',fill=(*primary,255))
  d.text((cx,base_y+77),item['name'][:14],font=font(22,True),anchor='mm',fill=(245,246,250,255))
  d.text((cx,base_y+116),f"LVL {elo_level(item['points'])} · {item['points']} ELO",font=font(18,True),anchor='mm',fill=(*secondary,255))
  d.text((cx,base_y+151),f"{item['wins']}W · {item['games']} игр",font=font(16),anchor='mm',fill=(169,172,190,255))
 # Remaining rows
 start=650
 if not rows:
  d.text((540,520),'В этой лиге пока нет участников',font=font(28,True),anchor='mm',fill=(220,222,232,255))
 for idx,item in enumerate(rows[3:10],4):
  y=start+(idx-4)*76
  d.rounded_rectangle((44,y,1036,y+62),radius=17,fill=(20,22,35,238),outline=(*primary,72),width=1)
  av=avatar(item.get('avatar_url'),46); round_paste(canvas,av,(63,y+8),46,14)
  d.text((128,y+31),f'#{idx}',font=font(19,True),anchor='lm',fill=(*primary,255))
  d.text((190,y+31),item['name'][:25],font=font(20,True),anchor='lm',fill=(244,245,250,255))
  d.text((760,y+31),f"{item['wins']}W",font=font(18,True),anchor='rm',fill=(70,190,125,255))
  d.text((1005,y+31),f"LVL {elo_level(item['points'])} · {item['points']} ELO",font=font(18,True),anchor='rm',fill=(*secondary,255))
 d.text((540,1244),f'{league.upper()} LEAGUE  •  SEOR CYBER',font=font(16,True),anchor='mm',fill=(*primary,200))
 out=io.BytesIO(); canvas.convert('RGB').save(out,'PNG',quality=95); out.seek(0); return out
