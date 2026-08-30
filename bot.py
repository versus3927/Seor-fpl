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
from profile_card import build_profile_card

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0") or 0)
BOT_NAME = os.getenv("BOT_NAME", "Arena Queue")
ACCENT = int(os.getenv("ACCENT_COLOR", "7C3AED"), 16)
STAFF_ONLY_COMMANDS = os.getenv("STAFF_ONLY_COMMANDS", "true").lower() in {"1", "true", "yes", "on"}
LOBBY_SIZE = max(1, min(10, int(os.getenv("LOBBY_SIZE", "10"))))
QUALIFICATION_KD = max(0.0, float(os.getenv("QUALIFICATION_KD", "1.00")))
LEAGUES = {
    "Default": ("⚪", 1000),
    "Prospect": ("🟢", 1150),
    "Division": ("🟣", 1350),
    "Pro": ("🔴", 1600),
}
MAPS = ["Sandstone", "Province", "Rust", "Dune", "Hanami", "Breeze", "Prison"]
MAP_ICONS = {"Sandstone":"🏜️","Province":"🏘️","Rust":"🏭","Dune":"🌵","Hanami":"🌸","Breeze":"🌊","Prison":"⛓️"}
MAP_VETO_TIMEOUT = 15
STAFF_ROLES = {
    "owner": "👑 Owner",
    "admin": "🛡️ Admin",
    "curator_default": "⚪ Curator Default",
    "curator_prospect": "🟢 Curator Prospect",
    "curator_division": "🟣 Curator Division",
    "curator_pro": "🔴 Curator Pro",
}
LEAGUE_ROLES = {
    "prospect": "🟢 Prospect",
    "division": "🟣 Division",
    "pro": "🔴 Pro",
}

intents = discord.Intents.default()
intents.members = True
intents.voice_states = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
queue_messages = {}
starting = set()
active_veto = set()
room_owners = {}
match_room_cleanup = {}


def color():
    return discord.Color(ACCENT)


def has_role(member, role_name):
    return any(role.name == role_name for role in member.roles)


def player_league(points):
    if points >= 1600: return "Pro"
    if points >= 1350: return "Division"
    if points >= 1150: return "Prospect"
    return "Default"


def qualification_status(player_data):
    league=player_league(player_data["points"])
    kd=player_data["kills"]/max(1,player_data["deaths"])
    exempt=league in {"Pro","Division"}
    return league,kd,exempt or kd >= QUALIFICATION_KD,exempt


def can_manage_staff(member):
    return member.id == member.guild.owner_id or has_role(member, STAFF_ROLES["owner"])


def can_administer(member):
    return can_manage_staff(member) or has_role(member, STAFF_ROLES["admin"])


def curator_league(member):
    for league in ("prospect","division","pro"):
        if has_role(member,STAFF_ROLES[f"curator_{league}"]): return league
    return None


def can_use_role_panel(member):
    return can_manage_staff(member) or curator_league(member) is not None


async def staff_command_access(interaction):
    if not await command_channel_access(interaction):
        return False
    if not STAFF_ONLY_COMMANDS:
        return True
    if not interaction.guild:
        return False
    allowed_roles=tuple(STAFF_ROLES.values())+tuple(LEAGUE_ROLES.values())
    return interaction.user.id == interaction.guild.owner_id or any(has_role(interaction.user,name) for name in allowed_roles)


async def command_channel_access(interaction):
    if not interaction.guild:
        return False
    command_channels=[c for c in interaction.guild.text_channels if c.name.endswith("команды")]
    return not command_channels or bool(interaction.channel and interaction.channel.id in {c.id for c in command_channels})


async def result_admin_access(interaction):
    return bool(interaction.guild and can_administer(interaction.user))


async def ensure_staff_roles(guild):
    result={}
    specs={
        "owner": (discord.Color.gold(), discord.Permissions(administrator=True)),
        "admin": (discord.Color.red(), discord.Permissions(manage_guild=True,manage_channels=True,manage_messages=True,moderate_members=True,move_members=True,mute_members=True)),
        "curator_default": (discord.Color.light_grey(), discord.Permissions(move_members=True,mute_members=True)),
        "curator_prospect": (discord.Color.green(), discord.Permissions(move_members=True,mute_members=True)),
        "curator_division": (discord.Color.purple(), discord.Permissions(move_members=True,mute_members=True)),
        "curator_pro": (discord.Color.magenta(), discord.Permissions(move_members=True,mute_members=True)),
    }
    for key,name in STAFF_ROLES.items():
        role=discord.utils.get(guild.roles,name=name)
        role_color,permissions=specs[key]
        if not role:
            try:
                role=await guild.create_role(name=name,color=role_color,permissions=permissions,hoist=True,reason="SEOR: создание служебной роли")
            except discord.Forbidden:
                role=await guild.create_role(name=name,color=role_color,permissions=discord.Permissions.none(),hoist=True,reason="SEOR: создание роли без глобальных прав")
        else:
            try: await role.edit(color=role_color,permissions=permissions,hoist=True,reason="SEOR: синхронизация служебной роли")
            except discord.Forbidden: pass
        result[key]=role
    league_colors={"prospect":discord.Color.green(),"division":discord.Color.purple(),"pro":discord.Color.red()}
    for key,name in LEAGUE_ROLES.items():
        role=discord.utils.get(guild.roles,name=name)
        if not role:
            role=await guild.create_role(name=name,color=league_colors[key],permissions=discord.Permissions.none(),hoist=True,reason="SEOR: роль доступа к лиге")
        result[f"league_{key}"]=role
    owner=guild.get_member(guild.owner_id)
    if owner and result["owner"] not in owner.roles:
        try: await owner.add_roles(result["owner"],reason="SEOR: роль владельца сервера")
        except discord.Forbidden: pass
    return result


def league_of(channel: discord.abc.GuildChannel):
    if not channel.category:
        return None
    for name in LEAGUES:
        if name.lower() in channel.category.name.lower():
            return name
    return None


def is_lobby(channel):
    return isinstance(channel, discord.VoiceChannel) and "lobby" in channel.name.lower()


def live_members(channel):
    return [m for m in channel.members if not m.bot]


def queue_embed(channel):
    league = league_of(channel) or "Default"
    emoji, _ = LEAGUES[league]
    members = live_members(channel)
    lines = "\n".join(f"`{i:02}` {m.mention}" for i, m in enumerate(members, 1)) or "Пока никого. Зайди в голосовой канал — бот добавит автоматически."
    e = discord.Embed(
        title=f"⚔️ {league.upper()} · {channel.name}",
        description=f"{emoji} **Очередь открыта.** Зайдите в голосовой канал, чтобы участвовать.\n\n**Подтверждённые игроки:** `{len(members)}/{LOBBY_SIZE}`\n**Голосовой канал:** {channel.mention}\n\n**В очереди**\n{lines}\n\n**До старта:** `{max(0, LOBBY_SIZE-len(members))}`",
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


class ResultSubmitView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Отправить результат", emoji="📌", style=discord.ButtonStyle.success, custom_id="result:submit")
    async def submit(self, interaction, button):
        await interaction.response.send_modal(ResultSubmitModal())


class ResultSubmitModal(discord.ui.Modal, title="Отправка результата"):
    match_id = discord.ui.TextInput(label="ID матча", placeholder="Например: 700", max_length=10)
    score = discord.ui.TextInput(label="Счёт", placeholder="13:9", max_length=7)

    def __init__(self, match_id=None):
        super().__init__()
        if match_id is not None:
            self.match_id.default = str(match_id)

    async def on_submit(self, interaction):
        try:
            match_id = int(str(self.match_id))
            a, b = [int(x.strip()) for x in str(self.score).replace("-", ":").split(":", 1)]
            assert (a == 13 or b == 13) and a != b and min(a, b) >= 0
        except Exception:
            return await interaction.response.send_message("Проверь ID и счёт. Пример счёта: `13:9`.", ephemeral=True)
        match = db.match(match_id)
        if not match:
            return await interaction.response.send_message("Матч с таким ID не найден.", ephemeral=True)
        players = {int(x) for x in (match["team_a"] + "," + match["team_b"]).split(",")}
        if interaction.user.id not in players and not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Ты не являешься участником этого матча.", ephemeral=True)
        await interaction.response.send_message(
            f"Теперь отправь **одним следующим сообщением** скриншот итогового счёта матча `#{match_id}`. У тебя 3 минуты.",
            ephemeral=True,
        )
        def check(message):
            return message.author.id == interaction.user.id and message.channel.id == interaction.channel_id and bool(message.attachments)
        try:
            message = await bot.wait_for("message", timeout=180, check=check)
        except asyncio.TimeoutError:
            return await interaction.followup.send("Время ожидания скриншота истекло. Нажми кнопку ещё раз.", ephemeral=True)
        attachment = message.attachments[0]
        if not (attachment.content_type or "").startswith("image/"):
            return await interaction.followup.send("Нужно отправить изображение, а не другой файл.", ephemeral=True)
        submission_id = db.create_submission(interaction.guild_id, match_id, interaction.user.id, a, b, attachment.url)
        review = next((c for c in interaction.guild.text_channels if c.name.endswith("проверка-результатов")), None)
        if not review:
            return await interaction.followup.send("Админ-канал не найден. Администратору нужно повторно выполнить `/setup`.", ephemeral=True)
        e = discord.Embed(
            title=f"🧾 Проверка результата №{submission_id}",
            description=f"Матч: **#{match_id}**\nСчёт: **{a}:{b}**\nОтправил: {interaction.user.mention}\nСтатус: **ожидает проверки**",
            color=discord.Color.orange(),
        )
        e.set_image(url=attachment.url)
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label="Принять", emoji="✅", style=discord.ButtonStyle.success, custom_id=f"result:approve:{submission_id}"))
        view.add_item(discord.ui.Button(label="Отклонить", emoji="❌", style=discord.ButtonStyle.danger, custom_id=f"result:reject:{submission_id}"))
        await review.send(embed=e, view=view)
        try: await message.delete()
        except discord.HTTPException: pass
        await interaction.followup.send(f"Результат №{submission_id} отправлен администрации.", ephemeral=True)


class GameLookupModal(discord.ui.Modal, title="Поиск профил��"):
    game_id = discord.ui.TextInput(label="Игровой ID", placeholder="Например: 132699411", max_length=30)

    async def on_submit(self, interaction):
        p=db.player_by_game_id(interaction.guild_id,str(self.game_id).strip())
        if not p:
            return await interaction.response.send_message("Игрок с таким ID не найден.",ephemeral=True)
        member=interaction.guild.get_member(p["user_id"])
        name=member.display_name if member else f"Игрок {p['user_id']}"
        kd=p["kills"]/max(1,p["deaths"])
        e=discord.Embed(title=f"🔎 {name}",description=f"ID: `{p['game_id']}`\nELO: **{p['points']}**\nМатчи: **{p['games']}**\nПобеды: **{p['wins']}**\nK/D: **{kd:.2f}**",color=color())
        await interaction.response.send_message(embed=e,ephemeral=True)


class MatchLookupDashboardModal(discord.ui.Modal, title="Поиск матча"):
    match_id = discord.ui.TextInput(label="ID матча", placeholder="Например: 700", max_length=10)

    async def on_submit(self, interaction):
        try: m=db.match(int(str(self.match_id)))
        except ValueError: m=None
        if not m:
            return await interaction.response.send_message("Матч не найден.",ephemeral=True)
        a=" ".join(f"<@{x}>" for x in m["team_a"].split(",") if x)
        b=" ".join(f"<@{x}>" for x in m["team_b"].split(",") if x)
        score=f"{m['score_a'] if m['score_a'] is not None else '?'}:{m['score_b'] if m['score_b'] is not None else '?'}"
        e=discord.Embed(title=f"🎮 Матч #{m['id']}",description=f"Лига: **{m['league']}**\nКарта: **{m['map']}**\nСтатус: **{m['status']}**\nСчёт: **{score}**\n\n🛡 CT: {a}\n💣 T: {b}",color=color())
        await interaction.response.send_message(embed=e,ephemeral=True)


DASHBOARD_SECTIONS={
    "stats":("📊","Статистика","Профиль, K/D, игровая форма и поиск игрока."),
    "rating":("🏆","Рейтинг","Таблица лидеров, твой ELO и место на сервере."),
    "matches":("🎮","Матчи","Последние игры, текущий статус и поиск по ID."),
    "party":("👥","Пати","Группа до трёх игроков для совместного подбора."),
    "account":("⚙️","Аккаунт","Игровой ID и данные регистрации."),
    "roles":("🛡️","Роли","Создание и выдача служебных ролей проекта."),
}


def dashboard_panel_embed(section):
    emoji,title,description=DASHBOARD_SECTIONS[section]
    section_colors={
        "stats":discord.Color.from_rgb(124,58,237),
        "rating":discord.Color.gold(),
        "matches":discord.Color.from_rgb(37,99,235),
        "party":discord.Color.from_rgb(16,185,129),
        "account":discord.Color.from_rgb(100,116,139),
        "roles":discord.Color.from_rgb(239,68,68),
    }
    e=discord.Embed(title=f"{emoji} {title}",description=description,color=section_colors[section])
    e.add_field(name="Навигация",value="Выбери раздел в меню ниже.",inline=True)
    e.add_field(name="Доступ",value="Панель видна только тебе.",inline=True)
    e.set_footer(text="SEOR CYBER • игровая панель")
    return e


def dashboard_home_embed():
    e=discord.Embed(title="🎛️ ПАНЕЛЬ УПРАВЛЕНИЯ",description="Твой центр управления матчами и профилем. Нажми кнопку ниже — панель откроется лично для тебя.",color=discord.Color.from_rgb(124,58,237))
    e.add_field(name="👤 Игрок",value="Профиль • статистика • рейтинг",inline=True)
    e.add_field(name="🎮 Матчи",value="История • поиск • результаты",inline=True)
    e.add_field(name="👥 Команда",value="Пати • совместный подбор",inline=True)
    e.add_field(name="🛡️ Персонал",value="Создание и выдача служебных ролей",inline=False)
    e.set_footer(text="SEOR CYBER · FACEIT STANDOFF 2")
    return e


class DashboardSectionSelect(discord.ui.Select):
    def __init__(self,section):
        options=[discord.SelectOption(label=title,value=value,emoji=emoji,description=desc[:95],default=value==section) for value,(emoji,title,desc) in DASHBOARD_SECTIONS.items()]
        super().__init__(placeholder="Выбери раздел панели",options=options,row=0)

    async def callback(self,interaction):
        section=self.values[0]
        await interaction.response.edit_message(embed=dashboard_panel_embed(section),view=DashboardPanelView(section))


class DashboardPanelView(discord.ui.View):
    def __init__(self,section="stats"):
        super().__init__(timeout=300)
        self.add_item(DashboardSectionSelect(section))
        if section=="stats":
            self._button("Мой профиль","👤",discord.ButtonStyle.primary,self.profile)
            self._button("Найти по ID","🔎",discord.ButtonStyle.secondary,self.lookup_player)
            self._button("Моя форма","📈",discord.ButtonStyle.secondary,self.form)
        elif section=="rating":
            self._button("Топ сервера","🏆",discord.ButtonStyle.primary,self.top)
            self._button("Моё место","📍",discord.ButtonStyle.secondary,self.place)
            self._button("Норматив лиги","📗",discord.ButtonStyle.secondary,self.norms)
        elif section=="matches":
            self._button("Последние матчи","🕹️",discord.ButtonStyle.primary,self.matches)
            self._button("Найти матч","🔎",discord.ButtonStyle.secondary,self.lookup_match)
            self._button("Отправить результат","📤",discord.ButtonStyle.success,self.result)
        elif section=="party":
            self._button("Создать пати","➕",discord.ButtonStyle.success,self.party_create)
            self._button("Моё пати","👥",discord.ButtonStyle.primary,self.party_show)
            self._button("Покинуть","🚪",discord.ButtonStyle.danger,self.party_leave)
        elif section=="account":
            self._button("Изменить игровой ID","🪪",discord.ButtonStyle.primary,self.change_id)
            self._button("Данные аккаунта","📋",discord.ButtonStyle.secondary,self.account)
        else:
            self._button("Управление ролями","🛡️",discord.ButtonStyle.primary,self.role_panel)
            self._button("Создать роли","➕",discord.ButtonStyle.success,self.create_roles)
        back=discord.ui.Button(label="Назад",emoji="↩️",style=discord.ButtonStyle.secondary,row=4)
        back.callback=self.back
        self.add_item(back)

    def _button(self,label,emoji,style,callback):
        b=discord.ui.Button(label=label,emoji=emoji,style=style,row=1); b.callback=callback; self.add_item(b)

    async def profile(self,i): await send_profile(i)
    async def lookup_player(self,i): await i.response.send_modal(GameLookupModal())
    async def lookup_match(self,i): await i.response.send_modal(MatchLookupDashboardModal())
    async def change_id(self,i): await i.response.send_modal(GameIdModal())
    async def result(self,i): await i.response.send_modal(ResultSubmitModal())

    async def form(self,i):
        p=db.player(i.guild_id,i.user.id); wr=100*p["wins"]/max(1,p["games"]); kd=p["kills"]/max(1,p["deaths"])
        await i.response.send_message(f"📈 Текущая форма: **{p['wins']}W / {p['losses']}L**, WR **{wr:.0f}%**, K/D **{kd:.2f}**.",ephemeral=True)

    async def top(self,i):
        rows=db.leaders(i.guild_id,10); text="\n".join(f"**#{n}** <@{p['user_id']}> — `{p['points']} ELO`" for n,p in enumerate(rows,1)) or "Рейтинг пока пуст."
        await i.response.send_message(embed=discord.Embed(title="🏆 Топ SEOR",description=text,color=color()),ephemeral=True)

    async def place(self,i):
        rows=db.leaders(i.guild_id,1000); pos=next((n for n,p in enumerate(rows,1) if p["user_id"]==i.user.id),None); p=db.player(i.guild_id,i.user.id)
        await i.response.send_message(f"📍 Твоё место: **#{pos or '—'}**, рейтинг: **{p['points']} ELO**.",ephemeral=True)

    async def norms(self,i):
        await i.response.send_message(f"📗 Квалификация: **K/D {QUALIFICATION_KD:.2f}**. Игроки лиг **Division** и **Pro** освобождены от норматива.\n\nЛиги по ELO: Default 1000 · Prospect 1150 · Division 1350 · Pro 1600.",ephemeral=True)

    async def matches(self,i):
        rows=db.recent_matches(i.guild_id,10); text="\n".join(f"`#{m['id']}` · {m['league']} · {m['map']} · {m['score_a'] if m['score_a'] is not None else '?'}:{m['score_b'] if m['score_b'] is not None else '?'}" for m in rows) or "Матчей пока нет."
        await i.response.send_message(embed=discord.Embed(title="🕹️ Последние матчи",description=text,color=color()),ephemeral=True)

    async def party_create(self,i): await i.response.send_message("👥 Тестовое пати создано. Приглашение игроков будет добавлено в следующем модуле.",ephemeral=True)
    async def party_show(self,i): await i.response.send_message("👥 Сейчас ты не состоишь в активном пати.",ephemeral=True)
    async def party_leave(self,i): await i.response.send_message("🚪 Ты покинул активное пати.",ephemeral=True)
    async def account(self,i):
        p=db.player(i.guild_id,i.user.id)
        await i.response.send_message(f"⚙️ Discord: {i.user.mention}\nИгровой ID: `{p['game_id'] or 'не указан'}`\nELO: **{p['points']}**\nМатчей: **{p['games']}**",ephemeral=True)

    async def back(self,i):
        await i.response.edit_message(embed=dashboard_home_embed(),view=DashboardView())

    async def role_panel(self,i):
        if not can_use_role_panel(i.user):
            return await i.response.send_message("Управлять ролями могут Owner и кураторы лиг.",ephemeral=True)
        await i.response.send_message(embed=discord.Embed(title="🛡️ Управление ролями",description="Выбери участника и роль, затем нажми **Выдать** или **Снять**. Куратор может управлять только ролью своей лиги.",color=color()),view=RolePanelView(),ephemeral=True)

    async def create_roles(self,i):
        if not can_manage_staff(i.user):
            return await i.response.send_message("Создавать роли может только владелец сервера или Owner.",ephemeral=True)
        await ensure_staff_roles(i.guild)
        await i.response.send_message("Служебные роли созданы и синхронизированы.",ephemeral=True)


class StaffMemberSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="Выбери участника",min_values=1,max_values=1,row=0)
    async def callback(self,interaction):
        self.view.target_id=self.values[0].id
        await interaction.response.defer()


class StaffRoleSelect(discord.ui.Select):
    def __init__(self):
        options=[discord.SelectOption(label=name,value=key,description="Служебная роль") for key,name in STAFF_ROLES.items()]
        options += [discord.SelectOption(label=name,value=f"league_{key}",description="Доступ игрока к лиге") for key,name in LEAGUE_ROLES.items()]
        super().__init__(placeholder="Выбери роль",options=options,min_values=1,max_values=1,row=1)
    async def callback(self,interaction):
        self.view.role_key=self.values[0]
        await interaction.response.defer()


class RolePanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.target_id=None; self.role_key=None
        self.add_item(StaffMemberSelect()); self.add_item(StaffRoleSelect())

    async def selected(self,interaction):
        if not can_use_role_panel(interaction.user):
            await interaction.response.send_message("Недостаточно прав.",ephemeral=True); return None,None
        if not self.target_id or not self.role_key:
            await interaction.response.send_message("Сначала выбери участника и роль.",ephemeral=True); return None,None
        if self.role_key in STAFF_ROLES and not can_manage_staff(interaction.user):
            await interaction.response.send_message("Служебные роли Owner/Admin/Curator может выдавать только владелец или Owner.",ephemeral=True); return None,None
        if self.role_key.startswith("league_"):
            target_league=self.role_key.removeprefix("league_")
            if not can_manage_staff(interaction.user) and curator_league(interaction.user)!=target_league:
                await interaction.response.send_message("Куратор может выдавать и снимать только роль своей лиги.",ephemeral=True); return None,None
        member=interaction.guild.get_member(self.target_id)
        roles=await ensure_staff_roles(interaction.guild)
        return member,roles.get(self.role_key)

    @discord.ui.button(label="Выдать",emoji="✅",style=discord.ButtonStyle.success,row=2)
    async def give(self,interaction,button):
        member,role=await self.selected(interaction)
        if not member or not role: return
        try: await member.add_roles(role,reason=f"SEOR dashboard: {interaction.user}")
        except discord.Forbidden: return await interaction.response.send_message("Роль бота должна находиться выше выдаваемой роли.",ephemeral=True)
        await interaction.response.send_message(f"{role.mention} выдана участнику {member.mention}.",ephemeral=True)

    @discord.ui.button(label="Снять",emoji="➖",style=discord.ButtonStyle.danger,row=2)
    async def remove(self,interaction,button):
        member,role=await self.selected(interaction)
        if not member or not role: return
        if member.id==interaction.guild.owner_id and self.role_key=="owner":
            return await interaction.response.send_message("Нельзя снять Owner с владельца сервера.",ephemeral=True)
        try: await member.remove_roles(role,reason=f"SEOR dashboard: {interaction.user}")
        except discord.Forbidden: return await interaction.response.send_message("Роль бота должна находиться выше снимаемой роли.",ephemeral=True)
        await interaction.response.send_message(f"{role.mention} снята с участника {member.mention}.",ephemeral=True)


class DashboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Открыть панель",emoji="🎛️",style=discord.ButtonStyle.success,custom_id="dashboard:open")
    async def open_panel(self,interaction,button):
        await interaction.response.send_message(embed=dashboard_panel_embed("stats"),view=DashboardPanelView("stats"),ephemeral=True)

    @discord.ui.button(label="Управление ролями",emoji="🛡️",style=discord.ButtonStyle.danger,custom_id="dashboard:roles")
    async def open_roles(self,interaction,button):
        if not can_use_role_panel(interaction.user):
            return await interaction.response.send_message("Этот раздел доступен Owner и кураторам лиг.",ephemeral=True)
        await interaction.response.send_message(embed=discord.Embed(title="🛡️ Роли и доступ к лигам",description="Выбери участника и роль. Затем нажми **Выдать** или **Снять**.\n\n🟢 Prospect · 🟣 Division · 🔴 Pro — роли доступа игроков\n👑 Owner · 🛡️ Admin · Curator — служебные роли\n\nКуратор может выдавать только доступ к своей лиге.",color=discord.Color.red()),view=RolePanelView(),ephemeral=True)


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Создать тикет", emoji="🎫", style=discord.ButtonStyle.success, custom_id="ticket:create")
    async def create_ticket(self, interaction, button):
        guild = interaction.guild
        staff_roles = await ensure_staff_roles(guild)
        existing = discord.utils.get(guild.text_channels, topic=f"ticket-owner:{interaction.user.id}")
        if existing:
            return await interaction.response.send_message(f"У тебя уже есть тикет: {existing.mention}", ephemeral=True)
        category = discord.utils.get(guild.categories, name="🎫 TICKETS") or await guild.create_category("🎫 TICKETS")
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
            staff_roles["owner"]: discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_messages=True),
            staff_roles["admin"]: discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_messages=True),
        }
        channel = await guild.create_text_channel(f"ticket-{interaction.user.name}"[:90], category=category, topic=f"ticket-owner:{interaction.user.id}", overwrites=overwrites)
        await channel.send(f"{interaction.user.mention}, опиши проблему и приложи доказательства. Администраторы с правом Administrator видят этот канал.")
        await interaction.response.send_message(f"Тикет создан: {channel.mention}", ephemeral=True)


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
            return await interaction.response.send_message("Матч не най��ен или уже завершён.", ephemeral=True)
        e=discord.Embed(title=f"🏁 Матч #{self.match_id} завершён",description=f"Итоговый счёт: **{a}:{b}**\nРейтинг игроков обновлён.",color=discord.Color.green())
        await interaction.response.send_message(embed=e)


async def send_profile(interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    p = db.player(interaction.guild_id, interaction.user.id)
    recent=[]
    for m in db.recent_matches(interaction.guild_id,50):
        ids=set((m["team_a"]+","+m["team_b"]).split(","))
        if str(interaction.user.id) in ids: recent.append(m)
    avatar_url=interaction.user.display_avatar.with_size(256).url
    card=await build_profile_card(p,interaction.user.display_name,str(avatar_url),recent)
    view=discord.ui.View(timeout=60)
    button=discord.ui.Button(label="Изменить игровой ID",style=discord.ButtonStyle.primary)
    async def cb(i): await i.response.send_modal(GameIdModal())
    button.callback=cb; view.add_item(button)
    await interaction.followup.send(file=discord.File(card,"profile.png"),view=view,ephemeral=True)


async def update_queue(channel):
    if not is_lobby(channel) or not league_of(channel): return
    text = next((c for c in channel.category.text_channels if c.name.endswith("ranked")), None)
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
    if len(live_members(channel)) >= LOBBY_SIZE and key not in starting and key not in active_veto:
        starting.add(key)
        try: await start_match(channel,text)
        finally: starting.discard(key)


class MapVetoView(discord.ui.View):
    def __init__(self,lobby,text,members,team_a,team_b,league,host):
        super().__init__(timeout=None)
        self.lobby=lobby; self.text=text; self.members=members
        self.team_a=team_a; self.team_b=team_b; self.league=league; self.host=host
        captain_a=next((m for m in team_a if not m.bot),host)
        captain_b=next((m for m in team_b if not m.bot),captain_a)
        self.captains=[captain_a,captain_b]
        self.remaining=list(MAPS); self.banned=[]; self.history=[]; self.turn=0
        self.message=None; self.timer_task=None; self.finished=False
        self.lock=asyncio.Lock()
        self.rebuild()

    @property
    def captain(self): return self.captains[self.turn % 2]

    def embed(self,selected=None):
        if selected:
            e=discord.Embed(title=f"✅ Карта выбрана: {MAP_ICONS[selected]} {selected}",description="Распик завершён. Бот создаёт комнаты команд.",color=discord.Color.green())
        else:
            available="  ".join(f"{MAP_ICONS[m]} **{m}**" for m in self.remaining)
            log="\n".join(self.history[-6:]) or "Банов пока нет."
            e=discord.Embed(title="🗺️ РАСПИК КАРТ",description=f"Капитаны по очереди исключают карты. На ход даётся **{MAP_VETO_TIMEOUT} секунд**. Если капитан не отвечает, бот автоматически банит случайную карту.\n\n**Сейчас ходит:** {self.captain.mention}\n**Доступные карты:**\n{available}",color=discord.Color.from_rgb(124,58,237))
            e.add_field(name="🛡 Капитан CT",value=self.captains[0].mention,inline=True)
            e.add_field(name="💣 Капитан T",value=self.captains[1].mention,inline=True)
            e.add_field(name="⏱️ Таймер",value=f"{MAP_VETO_TIMEOUT} сек.",inline=True)
            e.add_field(name="История банов",value=log,inline=False)
        e.set_footer(text=f"SEOR MAP VETO • {self.league} • осталось карт: {len(self.remaining)}")
        return e

    def rebuild(self):
        self.clear_items()
        for index,map_name in enumerate(MAPS):
            banned=map_name not in self.remaining
            button=discord.ui.Button(label=map_name,emoji=MAP_ICONS[map_name],style=discord.ButtonStyle.secondary if banned else discord.ButtonStyle.primary,disabled=banned,row=index//5)
            async def callback(interaction,map_choice=map_name):
                await self.manual_ban(interaction,map_choice)
            button.callback=callback
            self.add_item(button)

    async def start(self):
        mentions=" ".join(m.mention for m in self.members)
        self.message=await self.text.send(content=mentions,embed=self.embed(),view=self)
        self.schedule_timer()

    def schedule_timer(self):
        current=asyncio.current_task()
        if self.timer_task and not self.timer_task.done() and self.timer_task is not current:
            self.timer_task.cancel()
        self.timer_task=asyncio.create_task(self.auto_ban())

    async def manual_ban(self,interaction,map_name):
        if interaction.user.id != self.captain.id and not can_administer(interaction.user):
            return await interaction.response.send_message(f"Сейчас ход капитана {self.captain.mention}.",ephemeral=True)
        await interaction.response.defer()
        async with self.lock:
            if self.finished or map_name not in self.remaining: return
            self.remaining.remove(map_name)
            self.banned.append(map_name)
            self.history.append(f"🚫 {interaction.user.mention} забанил {MAP_ICONS[map_name]} **{map_name}**")
            await self.advance()

    async def auto_ban(self):
        try: await asyncio.sleep(MAP_VETO_TIMEOUT)
        except asyncio.CancelledError: return
        async with self.lock:
            if self.finished or len(self.remaining)<=1: return
            map_name=random.choice(self.remaining)
            captain=self.captain
            self.remaining.remove(map_name)
            self.banned.append(map_name)
            self.history.append(f"⏱️ AUTO-BAN: {captain.mention} не ответил — исключена {MAP_ICONS[map_name]} **{map_name}**")
            await self.advance()

    async def advance(self):
        if len(self.remaining)==1:
            self.finished=True
            selected=self.remaining[0]
            if self.timer_task and not self.timer_task.done() and self.timer_task is not asyncio.current_task():
                self.timer_task.cancel()
            self.clear_items()
            await self.message.edit(embed=self.embed(selected),view=self)
            active_veto.discard(self.lobby.id)
            await finalize_match(self.lobby,self.text,self.members,self.team_a,self.team_b,self.league,self.host,selected)
            return
        self.turn+=1
        self.rebuild()
        await self.message.edit(embed=self.embed(),view=self)
        self.schedule_timer()


async def start_match(lobby,text):
    members=live_members(lobby)[:LOBBY_SIZE]
    if not members: return
    random.shuffle(members)
    if len(members)==1:
        a,b=members,[lobby.guild.me]
    else:
        split=len(members)//2
        a,b=members[:split],members[split:]
    league=league_of(lobby) or "Default"
    host=random.choice(members)
    active_veto.add(lobby.id)
    veto=MapVetoView(lobby,text,members,a,b,league,host)
    try: await veto.start()
    except Exception:
        active_veto.discard(lobby.id)
        raise


async def finalize_match(lobby,text,members,a,b,league,host,map_name):
    match_id=db.create_match(lobby.guild.id,league,map_name,host.id,[x.id for x in a],[x.id for x in b])
    everyone=lobby.guild.default_role
    def overwrites(team):
        o={everyone:discord.PermissionOverwrite(view_channel=False,connect=False),lobby.guild.me:discord.PermissionOverwrite(view_channel=True,connect=True,move_members=True)}
        staff_names=(STAFF_ROLES["owner"],STAFF_ROLES["admin"],STAFF_ROLES.get(f"curator_{league.lower()}"))
        for role_name in staff_names:
            role=discord.utils.get(lobby.guild.roles,name=role_name) if role_name else None
            if role: o[role]=discord.PermissionOverwrite(view_channel=True,connect=True,speak=True,move_members=True,mute_members=True)
        for m in team:o[m]=discord.PermissionOverwrite(view_channel=True,connect=True,speak=True)
        return o
    va=await lobby.guild.create_voice_channel(f"🛡 CT · #{match_id}",category=lobby.category,overwrites=overwrites(a),user_limit=5)
    vb=await lobby.guild.create_voice_channel(f"💣 T · #{match_id}",category=lobby.category,overwrites=overwrites(b),user_limit=5)
    for m in a:
        if m.bot: continue
        try: await m.move_to(va)
        except discord.HTTPException: pass
    for m in b:
        if m.bot: continue
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
    bot.add_view(QueueView()); bot.add_view(RoomPanel()); bot.add_view(ResultSubmitView()); bot.add_view(DashboardView()); bot.add_view(TicketView())
    if GUILD_ID:
        guild=discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
    else:
        await bot.tree.sync()


@bot.event
async def on_ready():
    print(f"{bot.user} ready")
    await bot.change_presence(activity=discord.Game(f"очередь: {LOBBY_SIZE} игроков"))


@bot.event
async def on_interaction(interaction):
    if interaction.type != discord.InteractionType.component: return
    cid=interaction.data.get("custom_id","")
    if cid.startswith("match:lobby:"):
        await interaction.response.send_modal(LobbyModal(int(cid.rsplit(":",1)[1])))
    elif cid.startswith("match:result:"):
        await interaction.response.send_modal(ResultSubmitModal(int(cid.rsplit(":",1)[1])))
    elif cid.startswith("result:approve:") or cid.startswith("result:reject:"):
        if not can_administer(interaction.user):
            return await interaction.response.send_message("Нужны права управления сервером.", ephemeral=True)
        submission_id = int(cid.rsplit(":", 1)[1])
        sub = db.submission(submission_id)
        if not sub or sub["status"] != "pending":
            return await interaction.response.send_message("Заявка уже обработана или не найдена.", ephemeral=True)
        approved = cid.startswith("result:approve:")
        if approved:
            if not db.finish_match(sub["match_id"], sub["score_a"], sub["score_b"]):
                return await interaction.response.send_message("Матч уже завершён или не найден.", ephemeral=True)
            db.review_submission(submission_id, "approved", interaction.user.id)
            status, clr = "✅ принят", discord.Color.green()
            history = next((c for c in interaction.guild.text_channels if c.name.endswith("история-игр")), None)
            if history:
                e = discord.Embed(title=f"🎮 Матч #{sub['match_id']}", description=f"Итоговый счёт: **{sub['score_a']}:{sub['score_b']}**\nРезультат проверил: {interaction.user.mention}", color=clr)
                e.set_image(url=sub["screenshot_url"])
                await history.send(embed=e)
        else:
            db.review_submission(submission_id, "rejected", interaction.user.id)
            status, clr = "❌ отклонён", discord.Color.red()
        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        embed.color = clr
        embed.description = (embed.description or "") + f"\n\nСтатус: **{status}**\nПроверил: {interaction.user.mention}"
        await interaction.response.edit_message(embed=embed, view=None)


async def delete_empty_match_room(channel):
    task=asyncio.current_task()
    try:
        await asyncio.sleep(180)
        if not channel.members:
            await channel.delete(reason="Комната матча пуста 3 минуты")
    except (asyncio.CancelledError,discord.HTTPException):
        pass
    finally:
        if match_room_cleanup.get(channel.id) is task:
            match_room_cleanup.pop(channel.id,None)


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
    if after.channel and after.channel.name.startswith(("🛡 CT · #","💣 T · #")):
        old_task=match_room_cleanup.pop(after.channel.id,None)
        if old_task: old_task.cancel()
    if before.channel and before.channel.name.startswith(("🛡 CT · #","💣 T · #")) and not before.channel.members:
        old_task=match_room_cleanup.pop(before.channel.id,None)
        if old_task: old_task.cancel()
        match_room_cleanup[before.channel.id]=asyncio.create_task(delete_empty_match_room(before.channel))


@bot.tree.command(name="setup",description="Создать структуру лиг и панели")
@app_commands.check(command_channel_access)
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction:discord.Interaction):
    await interaction.response.defer(ephemeral=True,thinking=True)
    g=interaction.guild
    staff_roles=await ensure_staff_roles(g)

    # /setup синхронизирует только структуру, которой управляет бот.
    # Посторонние пользовательские категории и каналы не затрагиваются.
    unique_managed = {
        "📡 SEOR INFO": 1,
        "⌨️ SEOR COMMANDS": 1,
        "💬 SEOR COMMUNITY": 1,
        "🆘 SEOR SUPPORT": 1,
        "🎧 SEOR PRIVATE": 1,
        "📮 SEOR RESULTS": 1,
        "🛡️ SEOR STAFF": 1,
    }
    league_managed = {f"{emoji} SEOR {name.upper()}": 3 for name, (emoji, _) in LEAGUES.items()}
    for cat_name, keep_count in {**unique_managed, **league_managed}.items():
        same = [c for c in g.categories if c.name == cat_name]
        for extra in same[keep_count:]:
            for channel in list(extra.channels):
                await channel.delete(reason="SEOR /setup: удаление лишнего канала")
            await extra.delete(reason="SEOR /setup: удаление лишней категории")

    # Категории ранних тестовых версий, которые больше не входят в схему.
    legacy_names = {
        "Prospect 🟢", "Prospect matches", "PROSPECT MATCHES",
        "INFORMATION", "comand", "COMMAND", "COMMUNITY",
        "📌 INFO", "▶️ START", "👥 COMMUNITY", "🎫 SUPPORT'S",
        "🎧 ПРИВАТНЫЕ КАНАЛЫ", "📮 SEND RESULT'S", "🛡️ ADMINISTRATION",
        "⚪ DEFAULT LEAGUE", "🟢 PROSPECT LEAGUE", "🟣 DIVISION LEAGUE", "🔴 PRO LEAGUE",
    }
    for old_cat in [c for c in g.categories if c.name in legacy_names]:
        for channel in list(old_cat.channels):
            await channel.delete(reason="SEOR /setup: очистка старой структуры")
        await old_cat.delete(reason="SEOR /setup: очистка старой структуры")

    async def category(name):
        return discord.utils.get(g.categories, name=name) or await g.create_category(name)
    async def text(cat, name, **kwargs):
        return discord.utils.get(cat.text_channels, name=name) or await g.create_text_channel(name, category=cat, **kwargs)
    async def sync_channels(cat, text_names=(), voice_names=(), preserve_voice_prefixes=()):
        allowed_text=set(text_names); allowed_voice=set(voice_names)
        for channel in list(cat.channels):
            if isinstance(channel, discord.TextChannel) and channel.name not in allowed_text:
                await channel.delete(reason="SEOR /setup: канал отсутствует в актуальной схеме")
            elif isinstance(channel, discord.VoiceChannel):
                preserved=any(channel.name.startswith(prefix) for prefix in preserve_voice_prefixes)
                if channel.name not in allowed_voice and not preserved:
                    await channel.delete(reason="SEOR /setup: голосовой канал отсутствует в актуальной схеме")

    info = await category("📡 SEOR INFO")
    info_names=("📣・объявления", "📜・регламент", "🛍️・магазин", "📨・новости-лиги", "🧩・настройка-лобби", "📺・трансляции")
    await sync_channels(info, text_names=info_names)
    for channel_name in info_names:
        await text(info, channel_name)

    start = await category("⌨️ SEOR COMMANDS")
    await sync_channels(start, text_names=("🤖・команды", "📊・дашборд", "🏆・топ-сервера"))
    commands_channel=await text(start, "🤖・команды")
    await commands_channel.set_permissions(g.default_role,view_channel=False,send_messages=False)
    await commands_channel.set_permissions(g.me,view_channel=True,send_messages=True,manage_messages=True)
    owner_member=g.get_member(g.owner_id)
    if owner_member:
        await commands_channel.set_permissions(owner_member,view_channel=True,send_messages=True)
    for role in staff_roles.values():
        await commands_channel.set_permissions(role,view_channel=True,send_messages=True,read_message_history=True)
    async for old_message in commands_channel.history(limit=20):
        if old_message.author == g.me:
            try: await old_message.delete()
            except discord.HTTPException: pass
    commands_embed=discord.Embed(title="⌨️ КОМАНДЫ SEOR",description="Используй slash-команды только в этом канале.",color=color())
    commands_embed.add_field(name="👤 Игрок",value="`/profile` — профиль\n`/set_game_id` — игровой ID\n`/standard` — норматив K/D\n`/qualification` — личная проверка норматива\n`/top` — топ игроков",inline=False)
    commands_embed.add_field(name="🎮 Матчи",value="`/result` — отправить результат\n`/match_info` — информация о матче",inline=False)
    commands_embed.add_field(name="🛡️ Управление",value="`/setup` — обновить структуру\n`/roles_setup` — восстановить роли\n`/admin_result` — принять результат вручную\n`/delete` — удалить структуру",inline=False)
    commands_embed.set_footer(text="Стандарт квалификации: K/D 1.00 • Division и Pro освобождены")
    await commands_channel.send(embed=commands_embed)
    dashboard = await text(start, "📊・дашборд")
    await text(start, "🏆・топ-сервера")
    async for old_message in dashboard.history(limit=20):
        if old_message.author == g.me:
            try: await old_message.delete()
            except discord.HTTPException: pass
    e = dashboard_home_embed()
    await dashboard.send(embed=e, view=DashboardView())

    community = await category("💬 SEOR COMMUNITY")
    community_names=("💭・общий-чат", "🛡️・поиск-клана", "🎯・поиск-игроков", "🔴・чат-pro", "🟣・чат-division", "🟡・чат-qualifications", "🛠️・чат-кураторов")
    await sync_channels(community, text_names=community_names, voice_names=("🌐 Общий голос",))
    for channel_name in community_names:
        await text(community, channel_name)
    if not discord.utils.get(community.voice_channels, name="🌐 Общий голос"):
        await g.create_voice_channel("🌐 Общий голос", category=community, user_limit=99)

    support = await category("🆘 SEOR SUPPORT")
    await sync_channels(support, text_names=("🎫・создать-тикет", "⚠️・наказания"))
    tickets = await text(support, "🎫・создать-тикет")
    await text(support, "⚠️・наказания")
    if not tickets.last_message_id:
        e = discord.Embed(title="🎧 ТЕХНИЧЕСКАЯ ПОДДЕРЖКА", description="Спорные результаты, регистрация, баги, жалобы и обжалования. Нажми кнопку — бот создаст приватный канал.", color=color())
        await tickets.send(embed=e, view=TicketView())

    for name,(emoji,_) in LEAGUES.items():
        cat_name=f"{emoji} SEOR {name.upper()}"
        cats=[c for c in g.categories if c.name == cat_name]
        while len(cats) < 3:
            cats.append(await g.create_category(cat_name))
        for i,cat in enumerate(cats[:3],1):
            curator=staff_roles.get(f"curator_{name.lower()}")
            if curator:
                await cat.set_permissions(curator,view_channel=True,send_messages=True,manage_messages=True,manage_channels=True,connect=True,move_members=True,mute_members=True)
            if name != "Default":
                league_role=staff_roles[f"league_{name.lower()}"]
                await cat.set_permissions(g.default_role,view_channel=False,connect=False,send_messages=False)
                await cat.set_permissions(league_role,view_channel=True,connect=True,speak=True,send_messages=True,read_message_history=True)
                await cat.set_permissions(staff_roles["owner"],view_channel=True,connect=True,send_messages=True,move_members=True)
                await cat.set_permissions(staff_roles["admin"],view_channel=True,connect=True,send_messages=True,move_members=True)
            else:
                await cat.set_permissions(g.default_role,view_channel=True,connect=True,send_messages=True,read_message_history=True)
            await sync_channels(cat, text_names=("🎮・ranked",), voice_names=(f"🔊 Lobby {i}",), preserve_voice_prefixes=("🛡 CT · #", "💣 T · #"))
            ranked=discord.utils.get(cat.text_channels,name="🎮・ranked") or await g.create_text_channel("🎮・ranked",category=cat)
            lobby=discord.utils.get(cat.voice_channels,name=f"🔊 Lobby {i}")
            if not lobby:
                lobby=next((v for v in cat.voice_channels if is_lobby(v)),None) or await g.create_voice_channel(f"🔊 Lobby {i}",category=cat,user_limit=LOBBY_SIZE)
            if lobby.user_limit != LOBBY_SIZE:
                await lobby.edit(user_limit=LOBBY_SIZE,reason="SEOR: синхронизация LOBBY_SIZE")
            for managed_channel in (ranked,lobby):
                if managed_channel and not managed_channel.permissions_synced:
                    await managed_channel.edit(sync_permissions=True,reason="SEOR: синхронизация доступа к лиге")
            if not ranked.last_message_id:
                msg=await ranked.send(embed=queue_embed(lobby),view=QueueView()); queue_messages[lobby.id]=msg.id
    private=discord.utils.get(g.categories,name="🎧 SEOR PRIVATE") or await g.create_category("🎧 SEOR PRIVATE")
    await sync_channels(private, text_names=("⚙️・управление-комнатой",), voice_names=("➕ Создать комнату SEOR",), preserve_voice_prefixes=("🏠 Комната ",))
    panel=discord.utils.get(private.text_channels,name="⚙️・управление-комнатой") or await g.create_text_channel("⚙️・управление-комнатой",category=private)
    if not discord.utils.get(private.voice_channels,name="➕ Создать комнату SEOR"):
        await g.create_voice_channel("➕ Создать комнату SEOR",category=private)
    if not panel.last_message_id:
        e=discord.Embed(title="🎧 Управление приватной комнатой",description="Зайди в **➕ Создать комнату** — бот создаст твой голосовой канал и перенесёт тебя. Настраивай его кнопками ниже. Комната удалится, когда опустеет.",color=color())
        await panel.send(embed=e,view=RoomPanel())

    results = await category("📮 SEOR RESULTS")
    await sync_channels(results, text_names=("📤・отправить-результаты", "📚・история-игр"))
    send_results = await text(results, "📤・отправить-результаты")
    await text(results, "📚・история-игр")
    if not send_results.last_message_id:
        e=discord.Embed(title="📌 ОТПРАВКА РЕЗУЛЬТАТА МАТЧА",description="Нажми кнопку, введи ID матча и счёт, затем отправь скриншот итогового экрана игры. Результат попадёт на ручную проверку администрации.",color=color())
        await send_results.send(embed=e,view=ResultSubmitView())

    admin_overwrites={g.default_role:discord.PermissionOverwrite(view_channel=False),g.me:discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_channels=True),staff_roles["owner"]:discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_messages=True),staff_roles["admin"]:discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_messages=True)}
    admin = discord.utils.get(g.categories,name="🛡️ SEOR STAFF") or await g.create_category("🛡️ SEOR STAFF",overwrites=admin_overwrites)
    await sync_channels(admin, text_names=("✅・проверка-результатов", "📝・регистрация-игр", "🎛️・управление-матчами", "📋・логи-бота"))
    review = await text(admin,"✅・проверка-результатов",overwrites=admin_overwrites)
    await text(admin,"📝・регистрация-игр",overwrites=admin_overwrites)
    await text(admin,"🎛️・управление-матчами",overwrites=admin_overwrites)
    await text(admin,"📋・логи-бота",overwrites=admin_overwrites)
    if not review.last_message_id:
        await review.send(embed=discord.Embed(title="🧾 Проверка результатов",description="Сюда поступают скриншоты игроков. Администратор проверяет данные и нажимает **Принять** или **Отклонить**.",color=color()))
    await interaction.followup.send("Готово: структура синхронизирована — лишние управляемые каналы удалены, нужные добавлены. Посторонние кате��ории не затронуты.",ephemeral=True)


@bot.tree.command(name="delete",description="Удалить созданную ботом структуру")
@app_commands.check(command_channel_access)
@app_commands.describe(confirm="Для подтверждения напиши УДАЛИТЬ")
async def delete_setup(interaction:discord.Interaction,confirm:str):
    if not can_manage_staff(interaction.user):
        return await interaction.response.send_message("Удалять структуру может только владелец сервера или Owner.",ephemeral=True)
    if confirm.strip().upper() != "УДАЛИТЬ":
        return await interaction.response.send_message("Отменено. Для подтверждения нужно написать `УДАЛИТЬ`.",ephemeral=True)
    await interaction.response.send_message("Удаление структуры SEOR запущено.",ephemeral=True)
    managed={"📡 SEOR INFO","⌨️ SEOR COMMANDS","💬 SEOR COMMUNITY","🆘 SEOR SUPPORT","🎧 SEOR PRIVATE","📮 SEOR RESULTS","🛡️ SEOR STAFF","🎫 TICKETS"}
    managed.update(f"{emoji} SEOR {name.upper()}" for name,(emoji,_) in LEAGUES.items())
    for cat in [c for c in interaction.guild.categories if c.name in managed]:
        for channel in list(cat.channels):
            try: await channel.delete(reason=f"SEOR /delete by {interaction.user}")
            except discord.HTTPException: pass
        try: await cat.delete(reason=f"SEOR /delete by {interaction.user}")
        except discord.HTTPException: pass
    for role_name in tuple(STAFF_ROLES.values())+tuple(LEAGUE_ROLES.values()):
        role=discord.utils.get(interaction.guild.roles,name=role_name)
        if role:
            try: await role.delete(reason=f"SEOR /delete by {interaction.user}")
            except discord.HTTPException: pass


@bot.tree.command(name="roles_setup",description="Создать или восстановить служебные роли")
@app_commands.check(command_channel_access)
async def roles_setup(interaction:discord.Interaction):
    if not can_manage_staff(interaction.user):
        return await interaction.response.send_message("Команда доступна только владельцу сервера или Owner.",ephemeral=True)
    await interaction.response.defer(ephemeral=True,thinking=True)
    roles=await ensure_staff_roles(interaction.guild)
    await interaction.followup.send("Роли готовы: "+", ".join(role.mention for role in roles.values()),ephemeral=True)


@bot.tree.command(name="profile",description="Показать игровой профиль")
@app_commands.check(staff_command_access)
async def profile(interaction:discord.Interaction): await send_profile(interaction)


@bot.tree.command(name="set_game_id",description="Сохранить игровой ID")
@app_commands.check(staff_command_access)
async def set_game_id(interaction:discord.Interaction): await interaction.response.send_modal(GameIdModal())


@bot.tree.command(name="result",description="Отправить результат матча")
@app_commands.check(staff_command_access)
async def result(interaction:discord.Interaction): await interaction.response.send_modal(ResultSubmitModal())


@bot.tree.command(name="admin_result",description="Вручную зарегистрировать результат")
@app_commands.check(staff_command_access)
@app_commands.check(result_admin_access)
async def admin_result(interaction:discord.Interaction,match_id:int,score_a:int,score_b:int):
    if not ((score_a == 13 or score_b == 13) and score_a != score_b and min(score_a,score_b) >= 0):
        return await interaction.response.send_message("Некорректный счёт: одна команда должна иметь 13.",ephemeral=True)
    if not db.finish_match(match_id,score_a,score_b):
        return await interaction.response.send_message("Матч уже завершён или не найден.",ephemeral=True)
    history=next((c for c in interaction.guild.text_channels if c.name.endswith("история-игр")),None)
    if history:
        await history.send(embed=discord.Embed(title=f"🎮 Матч #{match_id}",description=f"Результат вручную зарегистрирован администрацией: **{score_a}:{score_b}**",color=discord.Color.green()))
    await interaction.response.send_message(f"Матч #{match_id} зарегистрирован: {score_a}:{score_b}.",ephemeral=True)


@bot.tree.command(name="match_info",description="Показать информацию о матче")
@app_commands.check(staff_command_access)
async def match_info(interaction:discord.Interaction,match_id:int):
    m=db.match(match_id)
    if not m: return await interaction.response.send_message("Матч не найден.",ephemeral=True)
    a=" ".join(f"<@{x}>" for x in m["team_a"].split(",")); b=" ".join(f"<@{x}>" for x in m["team_b"].split(","))
    e=discord.Embed(title=f"🎮 Матч #{match_id}",description=f"Лига: **{m['league']}**\nКарта: **{m['map']}**\nСтатус: **{m['status']}**\nСчёт: **{m['score_a'] if m['score_a'] is not None else '?'}:{m['score_b'] if m['score_b'] is not None else '?'}**\n\n🛡 CT: {a}\n💣 T: {b}",color=color())
    await interaction.response.send_message(embed=e,ephemeral=True)


def standard_embed(guild_id,user):
    p=db.player(guild_id,user.id)
    league,kd,passed,exempt=qualification_status(p)
    if exempt:
        result="✅ Норматив выполнять не нужно: действует освобождение для Division/Pro."
    elif passed:
        result=f"✅ Норматив выполнен: K/D {kd:.2f} ≥ {QUALIFICATION_KD:.2f}."
    else:
        result=f"❌ Норматив не выполнен: K/D {kd:.2f} < {QUALIFICATION_KD:.2f}."
    return discord.Embed(title="📗 Стандарт квалификации",description=f"Лига: **{league}**\nТекущий K/D: **{kd:.2f}**\nСтандарт: **{QUALIFICATION_KD:.2f} K/D**\nОсвобождение: **Division и Pro**\n\n{result}",color=discord.Color.green() if passed else discord.Color.red())


@bot.tree.command(name="standard",description="Показать стандарт квалификации K/D")
@app_commands.check(staff_command_access)
async def standard(interaction:discord.Interaction):
    await interaction.response.send_message(embed=standard_embed(interaction.guild_id,interaction.user),ephemeral=True)


@bot.tree.command(name="qualification",description="Проверить норматив K/D")
@app_commands.check(staff_command_access)
async def qualification(interaction:discord.Interaction):
    await interaction.response.send_message(embed=standard_embed(interaction.guild_id,interaction.user),ephemeral=True)


@bot.tree.command(name="top",description="Показать топ-10 игроков")
@app_commands.check(staff_command_access)
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
    if isinstance(error,app_commands.MissingPermissions):
        await interaction.response.send_message("Нужны права администратора.",ephemeral=True)
    elif isinstance(error,app_commands.CheckFailure):
        await interaction.response.send_message("Используй /setup только в канале #команды. Если канал ещё не создан, команда разрешена в любом канале.",ephemeral=True)


@bot.tree.error
async def command_error(interaction,error):
    if isinstance(error,app_commands.CheckFailure):
        if not interaction.channel or not interaction.channel.name.endswith("команды"):
            message="Эту команду можно использовать только в канале #команды."
        else:
            message="Команды временно доступны только владельцу и участникам со служебными ролями SEOR."
    else:
        print(f"Application command error: {error!r}",flush=True)
        message="При выполнении команды произошла ошибка. Проверь логи Railway."
    if interaction.response.is_done():
        await interaction.followup.send(message,ephemeral=True)
    else:
        await interaction.response.send_message(message,ephemeral=True)

if __name__ == "__main__":
    if not TOKEN: raise SystemExit("DISCORD_TOKEN не задан. Скопируй .env.example в .env")
    bot.run(TOKEN)
