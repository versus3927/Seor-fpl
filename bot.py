import asyncio
import io
import os
import random
from collections import defaultdict

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

import db

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0") or 0)
BOT_NAME = os.getenv("BOT_NAME", "Arena Queue")
ACCENT = int(os.getenv("ACCENT_COLOR", "7C3AED"), 16)
LEAGUES = {
    "Default": ("⚪", 1000),
    "Prospect": ("🟢", 1150),
    "Division": ("🟣", 1350),
    "Pro": ("🔴", 1600),
}
MAPS = ["Sandstone", "Province", "Rust", "Dune", "Hanami"]

intents = discord.Intents.default()
intents.members = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)
queue_messages = {}
starting = set()
room_owners = {}


def color():
    return discord.Color(ACCENT)


def league_of(channel: discord.abc.GuildChannel):
    if not channel.category:
        return None
    for name in LEAGUES:
        if name.lower() in channel.category.name.lower():
            return name
    return None


def is_lobby(channel):
    return isinstance(channel, discord.VoiceChannel) and channel.name.lower().startswith("lobby")


def live_members(channel):
    return [m for m in channel.members if not m.bot]


def queue_embed(channel):
    league = league_of(channel) or "Default"
    emoji, _ = LEAGUES[league]
    members = live_members(channel)
    lines = "\n".join(f"`{i:02}` {m.mention}" for i, m in enumerate(members, 1)) or "Пока никого. Зайди в голосовой канал — бот добавит автоматически."
    e = discord.Embed(
        title=f"⚔️ {league.upper()} · {channel.name}",
        description=f"{emoji} **Очередь открыта.** Зайдите в голосовой канал, чтобы участвовать.\n\n**Подтверждённые игроки:** `{len(members)}/10`\n**Голосовой канал:** {channel.mention}\n\n**В очереди**\n{lines}\n\n**До старта:** `{max(0, 10-len(members))}`",
        color=color(),
    )
    e.set_footer(text="Матч до 13 победных раундов · очередь обновляется автоматически")
    return e


class QueueView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Войти", emoji="✅", style=discord.ButtonStyle.success, custom_id="queue:join")
    async def join(self, interaction, button):
        await interaction.response.send_message("Зайди в указанный голосовой Lobby — регистрация произойдёт автоматически.", ephemeral=True)

    @discord.ui.button(label="Выйти", emoji="✖️", style=discord.ButtonStyle.secondary, custom_id="queue:leave")
    async def leave(self, interaction, button):
        if interaction.user.voice and is_lobby(interaction.user.voice.channel):
            await interaction.user.move_to(None)
            await interaction.response.send_message("Ты вышел из очереди.", ephemeral=True)
        else:
            await interaction.response.send_message("Ты сейчас не в очереди.", ephemeral=True)

    @discord.ui.button(label="Профиль", emoji="📊", style=discord.ButtonStyle.primary, custom_id="queue:profile")
    async def profile(self, interaction, button):
        await send_profile(interaction)


class RoomPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def owned(self, interaction):
        ch = interaction.user.voice.channel if interaction.user.voice else None
        if not ch or room_owners.get(ch.id) != interaction.user.id:
            await interaction.response.send_message("Эта кнопка доступна владельцу своей приватной комнаты.", ephemeral=True)
            return None
        return ch

    @discord.ui.button(emoji="✏️", label="Название", style=discord.ButtonStyle.secondary, custom_id="room:rename")
    async def rename(self, interaction, button):
        ch = await self.owned(interaction)
        if ch: await interaction.response.send_modal(RenameRoom(ch))

    @discord.ui.button(emoji="🔒", label="Закрыть/открыть", style=discord.ButtonStyle.secondary, custom_id="room:lock")
    async def lock(self, interaction, button):
        ch = await self.owned(interaction)
        if not ch: return
        current = ch.overwrites_for(interaction.guild.default_role)
        current.connect = not (current.connect is False)
        await ch.set_permissions(interaction.guild.default_role, overwrite=current)
        await interaction.response.send_message("Доступ комнаты переключён.", ephemeral=True)

    @discord.ui.button(emoji="👥", label="Лимит", style=discord.ButtonStyle.secondary, custom_id="room:limit")
    async def limit(self, interaction, button):
        ch = await self.owned(interaction)
        if ch: await interaction.response.send_modal(RoomLimit(ch))

    @discord.ui.button(emoji="👁️", label="Скрыть/показать", style=discord.ButtonStyle.secondary, custom_id="room:hide")
    async def hide(self, interaction, button):
        ch = await self.owned(interaction)
        if not ch: return
        ow = ch.overwrites_for(interaction.guild.default_role)
        ow.view_channel = not (ow.view_channel is False)
        await ch.set_permissions(interaction.guild.default_role, overwrite=ow)
        await interaction.response.send_message("Видимость комнаты переключена.", ephemeral=True)


class RenameRoom(discord.ui.Modal, title="Название комнаты"):
    name = discord.ui.TextInput(label="Новое название", max_length=80)
    def __init__(self, channel):
        super().__init__(); self.channel = channel
    async def on_submit(self, interaction):
        await self.channel.edit(name=str(self.name))
        await interaction.response.send_message("Название изменено.", ephemeral=True)


class RoomLimit(discord.ui.Modal, title="Лимит комнаты"):
    limit = discord.ui.TextInput(label="Число участников (0–99)", max_length=2)
    def __init__(self, channel):
        super().__init__(); self.channel = channel
    async def on_submit(self, interaction):
        try: value = max(0, min(99, int(str(self.limit))))
        except ValueError:
            return await interaction.response.send_message("Нужно указать число.", ephemeral=True)
        await self.channel.edit(user_limit=value)
        await interaction.response.send_message(f"Лимит: {value or 'без ограничений'}.", ephemeral=True)


class GameIdModal(discord.ui.Modal, title="Игровой профиль"):
    game_id = discord.ui.TextInput(label="Standoff 2 ID", placeholder="Например: 245507174", max_length=30)
    async def on_submit(self, interaction):
        db.set_game_id(interaction.guild_id, interaction.user.id, str(self.game_id))
        await interaction.response.send_message("Игровой ID сохранён.", ephemeral=True)


class LobbyModal(discord.ui.Modal, title="Ссылка на лобби"):
    url = discord.ui.TextInput(label="Ссылка", placeholder="https://...", max_length=300)
    def __init__(self, match_id):
        super().__init__(); self.match_id = match_id
    async def on_submit(self, interaction):
        m = db.match(self.match_id)
        if not m or interaction.user.id != m["host_id"]:
            return await interaction.response.send_message("Ссылку может отправить только хост.", ephemeral=True)
        db.set_lobby(self.match_id, str(self.url))
        ids = [int(x) for x in (m["team_a"]+","+m["team_b"]).split(",")]
        await interaction.response.send_message(" ".join(f"<@{x}>" for x in ids)+f"\n🔗 Лобби матча **#{self.match_id}**: {self.url}")


class ResultModal(discord.ui.Modal, title="Результат матча"):
    score = discord.ui.TextInput(label="Счёт", placeholder="13:9", max_length=7)
    def __init__(self, match_id):
        super().__init__(); self.match_id = match_id
    async def on_submit(self, interaction):
        try:
            a,b = [int(x.strip()) for x in str(self.score).replace("-",":").split(":",1)]
            assert (a == 13 or b == 13) and a != b and min(a,b) >= 0
        except Exception:
            return await interaction.response.send_message("Формат: `13:9`; одна команда должна иметь 13.", ephemeral=True)
        if not db.finish_match(self.match_id,a,b):
            return await interaction.response.send_message("Матч не найден или уже завершён.", ephemeral=True)
        e=discord.Embed(title=f"🏁 Матч #{self.match_id} завершён",description=f"Итоговый счёт: **{a}:{b}**\nРейтинг игроков обновлён.",color=discord.Color.green())
        await interaction.response.send_message(embed=e)


async def send_profile(interaction):
    p = db.player(interaction.guild_id, interaction.user.id)
    kd = p["kills"] / max(1,p["deaths"])
    e=discord.Embed(title=f"Профиль · {interaction.user.display_name}",color=color())
    e.add_field(name="Игровой ID",value=p["game_id"] or "не указан")
    e.add_field(name="Рейтинг",value=str(p["points"]))
    e.add_field(name="Матчи",value=str(p["games"]))
    e.add_field(name="Победы / поражения",value=f"{p['wins']} / {p['losses']}")
    e.add_field(name="K/D",value=f"{kd:.2f}")
    view=discord.ui.View(timeout=60)
    button=discord.ui.Button(label="Изменить игровой ID",style=discord.ButtonStyle.primary)
    async def cb(i): await i.response.send_modal(GameIdModal())
    button.callback=cb; view.add_item(button)
    await interaction.response.send_message(embed=e,view=view,ephemeral=True)


async def update_queue(channel):
    if not is_lobby(channel) or not league_of(channel): return
    text = discord.utils.get(channel.category.text_channels, name="ranked")
    if not text: return
    key=channel.id
    msg=None
    if key in queue_messages:
        try: msg=await text.fetch_message(queue_messages[key])
        except discord.HTTPException: pass
    if not msg:
        msg=await text.send(embed=queue_embed(channel),view=QueueView())
        queue_messages[key]=msg.id
    else:
        await msg.edit(embed=queue_embed(channel),view=QueueView())
    if len(live_members(channel)) >= 10 and key not in starting:
        starting.add(key)
        try: await start_match(channel,text)
        finally: starting.discard(key)


async def start_match(lobby,text):
    members=live_members(lobby)[:10]
    random.shuffle(members)
    a,b=members[:5],members[5:]
    league=league_of(lobby) or "Default"
    host=random.choice(members)
    map_name=random.choice(MAPS)
    match_id=db.create_match(lobby.guild.id,league,map_name,host.id,[x.id for x in a],[x.id for x in b])
    everyone=lobby.guild.default_role
    def overwrites(team):
        o={everyone:discord.PermissionOverwrite(view_channel=False,connect=False),lobby.guild.me:discord.PermissionOverwrite(view_channel=True,connect=True,move_members=True)}
        for m in team:o[m]=discord.PermissionOverwrite(view_channel=True,connect=True,speak=True)
        return o
    va=await lobby.guild.create_voice_channel(f"🛡 CT · #{match_id}",category=lobby.category,overwrites=overwrites(a),user_limit=5)
    vb=await lobby.guild.create_voice_channel(f"💣 T · #{match_id}",category=lobby.category,overwrites=overwrites(b),user_limit=5)
    for m in a:
        try: await m.move_to(va)
        except discord.HTTPException: pass
    for m in b:
        try: await m.move_to(vb)
        except discord.HTTPException: pass
    e=discord.Embed(title=f"🎮 Матч #{match_id}",description=f"{LEAGUES[league][0]} Лига **{league}**\nКарта: **{map_name}**\nФормат: **до 13 раундов**\nХост: {host.mention}\n\n**Комнаты:** {va.mention} · {vb.mention}\n*Ждём ссылку на лобби от хоста…*",color=color())
    e.add_field(name="🛡 CT",value="\n".join(f"• {m.mention}" for m in a))
    e.add_field(name="💣 T",value="\n".join(f"• {m.mention}" for m in b))
    view=discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Отправить ссылку",emoji="🔗",style=discord.ButtonStyle.success,custom_id=f"match:lobby:{match_id}"))
    view.add_item(discord.ui.Button(label="Отправить результат",emoji="🏁",style=discord.ButtonStyle.primary,custom_id=f"match:result:{match_id}"))
    await text.send(content=" ".join(m.mention for m in members),embed=e,view=view)
    await update_queue(lobby)


@bot.event
async def setup_hook():
    db.init_db()
    bot.add_view(QueueView()); bot.add_view(RoomPanel())
    if GUILD_ID:
        guild=discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
    else:
        await bot.tree.sync()


@bot.event
async def on_ready():
    print(f"{bot.user} ready")
    await bot.change_presence(activity=discord.Game("очереди 5×5"))


@bot.event
async def on_interaction(interaction):
    if interaction.type != discord.InteractionType.component: return
    cid=interaction.data.get("custom_id","")
    if cid.startswith("match:lobby:"):
        await interaction.response.send_modal(LobbyModal(int(cid.rsplit(":",1)[1])))
    elif cid.startswith("match:result:"):
        await interaction.response.send_modal(ResultModal(int(cid.rsplit(":",1)[1])))


@bot.event
async def on_voice_state_update(member,before,after):
    if member.bot: return
    if after.channel and after.channel.name.startswith("➕ Создать комнату"):
        overwrites={member.guild.default_role:discord.PermissionOverwrite(view_channel=True,connect=True),member:discord.PermissionOverwrite(manage_channels=True,move_members=True,mute_members=True,connect=True)}
        ch=await member.guild.create_voice_channel(f"🏠 Комната {member.display_name}",category=after.channel.category,overwrites=overwrites,user_limit=10)
        room_owners[ch.id]=member.id
        await member.move_to(ch)
    for ch in {before.channel,after.channel}:
        if ch and is_lobby(ch): await update_queue(ch)
    if before.channel and before.channel.id in room_owners and not before.channel.members:
        room_owners.pop(before.channel.id,None)
        await before.channel.delete(reason="Приватная комната опустела")
    if before.channel and before.channel.name.startswith(("🛡 CT · #","💣 T · #")) and not before.channel.members:
        await asyncio.sleep(30)
        if before.channel and not before.channel.members:
            try: await before.channel.delete(reason="Комната завершённого матча пуста")
            except discord.NotFound: pass


@bot.tree.command(name="setup",description="Создать структуру лиг и панели")
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction:discord.Interaction):
    await interaction.response.defer(ephemeral=True,thinking=True)
    g=interaction.guild
    for name,(emoji,_) in LEAGUES.items():
        category=discord.utils.get(g.categories,name=f"{emoji} {name.upper()} LEAGUE") or await g.create_category(f"{emoji} {name.upper()} LEAGUE")
        ranked=discord.utils.get(category.text_channels,name="ranked") or await g.create_text_channel("ranked",category=category)
        if not any(is_lobby(x) for x in category.voice_channels):
            lobby=await g.create_voice_channel("Lobby 1",category=category,user_limit=10)
            await ranked.send(embed=queue_embed(lobby),view=QueueView())
    private=discord.utils.get(g.categories,name="🎧 ПРИВАТНЫЕ КАНАЛЫ") or await g.create_category("🎧 ПРИВАТНЫЕ КАНАЛЫ")
    panel=discord.utils.get(private.text_channels,name="настройка") or await g.create_text_channel("настройка",category=private)
    if not discord.utils.get(private.voice_channels,name="➕ Создать комнату"):
        await g.create_voice_channel("➕ Создать комнату",category=private)
    e=discord.Embed(title="🎧 Управление приватной комнатой",description="Зайди в **➕ Создать комнату** — бот создаст твой голосовой канал и перенесёт тебя. Настраивай его кнопками ниже. Комната удалится, когда опустеет.",color=color())
    await panel.send(embed=e,view=RoomPanel())
    await interaction.followup.send("Готово: лиги, очереди и приватные комнаты созданы.",ephemeral=True)


@bot.tree.command(name="profile",description="Показать игровой профиль")
async def profile(interaction:discord.Interaction): await send_profile(interaction)


@bot.tree.command(name="set_game_id",description="Сохранить игровой ID")
async def set_game_id(interaction:discord.Interaction): await interaction.response.send_modal(GameIdModal())


@bot.tree.command(name="result",description="Отправить результат матча")
@app_commands.describe(match_id="Номер матча")
async def result(interaction:discord.Interaction,match_id:int): await interaction.response.send_modal(ResultModal(match_id))


@bot.tree.command(name="top",description="Показать топ-10 игроков")
async def top(interaction:discord.Interaction):
    rows=db.leaders(interaction.guild_id)
    img=Image.new("RGB",(900,120+70*max(1,len(rows))),(10,14,22)); d=ImageDraw.Draw(img)
    try: title=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",34); body=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",24)
    except OSError: title=body=None
    d.text((35,30),"ЛУЧШИЕ ИГРОКИ",fill=(124,58,237),font=title)
    if not rows:d.text((35,105),"Пока нет данных",fill="white",font=body)
    for i,p in enumerate(rows,1):
        member=interaction.guild.get_member(p["user_id"]); name=member.display_name if member else str(p["user_id"])
        y=85+i*65; d.rounded_rectangle((25,y-12,875,y+42),12,fill=(25,31,44)); d.text((45,y),f"{i:>2}. {name[:22]}",fill="white",font=body); d.text((610,y),f"{p['points']} pts   {p['wins']}W",fill=(104,211,145),font=body)
    out=io.BytesIO(); img.save(out,"PNG"); out.seek(0)
    await interaction.response.send_message(file=discord.File(out,"leaderboard.png"))


@setup.error
async def setup_error(interaction,error):
    if isinstance(error,app_commands.MissingPermissions): await interaction.response.send_message("Нужны права администратора.",ephemeral=True)

if __name__ == "__main__":
    if not TOKEN: raise SystemExit("DISCORD_TOKEN не задан. Скопируй .env.example в .env")
    bot.run(TOKEN)
