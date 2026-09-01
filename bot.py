import asyncio
from datetime import timedelta
import io
import json
import os
import random
import re
from collections import defaultdict
from difflib import SequenceMatcher

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

import db
from profile_card import build_profile_card
from leaderboard_card import build_leaderboard
from matches_card import build_matches_card
from screenshot_reader import analyze_screenshot

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0") or 0)
BOT_NAME = os.getenv("BOT_NAME", "Seor FACEIT")
ACCENT = int(os.getenv("ACCENT_COLOR", "7C3AED"), 16)
LOBBY_SIZE = max(1, min(10, int(os.getenv("LOBBY_SIZE", "10"))))
QUALIFICATION_KD = max(0.0, float(os.getenv("QUALIFICATION_KD", "1.00")))
LEAGUES = {
    "Default": ("⚪", 1000),
    "Qualifications": ("🟢", 1150),
    "Division": ("🟣", 1350),
    "Pro": ("🔴", 1600),
}
MAPS = ["Sandstone", "Province", "Rust", "Dune", "Hanami", "Breeze", "Prison"]
MAP_ICONS = {"Sandstone":"🏜️","Province":"🏘️","Rust":"🏭","Dune":"🌵","Hanami":"🌸","Breeze":"🌊","Prison":"⛓️"}
MAP_VETO_TIMEOUT = 15
REGISTERED_ROLE_NAME = "зарегистрирован"
STARTING_ELO = 1000
STAFF_ROLES = {
    "owner": "owner",
    "admin": "admin",
    "curator_qualifications": "qualifications curator",
    "curator_division": "division curator",
    "curator_pro": "PRO League curator",
}
LEAGUE_ROLES = {
    "default": "default League",
    "qualifications": "qualifications League",
    "division": "division League",
    "pro": "pro League",
}
EXTRA_ROLE_SPECS = {
    "developer": ("Developer", 0x9CCBFF, {"administrator": True}),
    "bot_role": ("SEOR CYBER bot", 0x99AAB5, {}),
    "director": ("GENERAL MÁNAGER", 0x111111, {"manage_guild": True, "manage_channels": True, "manage_roles": True}),
    "head_admin": ("head admin", 0x111111, {"manage_guild": True, "manage_channels": True, "manage_roles": True, "moderate_members": True}),
    "ticket_admin": ("Ticket admin", 0xA855F7, {"manage_messages": True, "moderate_members": True}),
    "head_ac": ("head ac", 0x1D4ED8, {"manage_messages": True, "moderate_members": True}),
    "games_admin": ("games admin", 0xEC4899, {"manage_messages": True, "move_members": True}),
    "anticheat": ("anticheat", 0x22C55E, {"manage_messages": True}),
    "moderator": ("moderator", 0xF97316, {"manage_messages": True, "moderate_members": True}),
    "content_creator": ("content creator", 0x14D8CC, {}),
    "streamer": ("streamer", 0xFDE68A, {}),
    "sponsor": ("₽", 0x00FF55, {}),
    "pro_lead": ("head of pro League", 0xC026D3, {"manage_messages": True, "move_members": True}),
    "premium": ("Premium", 0x0EA5E9, {}),
    "warn_pro_1": ("1/3 pro warn", 0xFB7185, {}),
    "warn_pro_2": ("2/3 pro warn", 0xFB7185, {}),
    "warn_pro_3": ("3/3 pro warn", 0xEF4444, {}),
    "warn_div_1": ("1/3 division warn", 0xC084FC, {}),
    "warn_div_2": ("2/3 division warn", 0xC084FC, {}),
    "warn_div_3": ("3/3 division warn", 0xA855F7, {}),
    "dot_role": (".", 0x164E63, {}),
    "test_division": ("test division", 0x7E22CE, {}),
    "warn_qual_1": ("1/3 Qual warn", 0xFEF08A, {}),
    "warn_qual_2": ("2/3 Qual warn", 0xFDE047, {}),
    "warn_qual_3": ("3/3 Qual warn", 0xEAB308, {}),
    "test_qualification": ("test fpl qualifications", 0x00E676, {}),
}
ROLE_PANEL_EXTRAS=("developer","director","head_admin","ticket_admin","head_ac","games_admin","anticheat","moderator","content_creator","streamer","sponsor","pro_lead","premium")

# Разовый перенос ролей со скриншотов старого сервера.
LAUNCH_ROLE_MEMBERS = {
    "league_division": {
        "conexxion0", "betrid", "birox444", "celocesd", "dissww", "gersachw",
        "hoollywood17", "hyko_zxc", "lanny122", "xanax_suicide", "tombaura",
        "r0g0ff", "pomidor0439", "gkv2213", "slizerry", "zilinl756",
        "versus2739", "koyen0692", "ono216", "whitemoon1337", "younai007",
        "wyrthless_1",
    },
    "league_pro": {
        "conexxion0", "birox444", "dissww", "hyko_zxc", "lanny122",
        "poanching", "versus2739", "koyen0692",
    },
    "test_division": {
        "noneattack88", "x1mk0", "apgxht", "vilent.", "trynexz2", "4shorty7",
        "ebanat67.", "koyen0692",
    },
    "curator_division": {
        "versus2739", "koyen0692", "ono216", "whitemoon1337",
    },
    "league_qualifications": {
        "fa1l_hello", "conexxion0", "sblnmazatishki", "summerdayy", "liublumaslo",
        "betrid", "birox444", "celocesd", "w1yterr.", "crouch0", "deruss23",
        "dissww", "dyhace228", "noneattack88", "exty73", "zex06607", "gersachw",
        "x1mk0", "gv3nt", "hoollywood17", "apgxht", "vilent.", "lever.uu",
        "hyko_zxc", "wtfinferno", "itso23_78155", "lanny122", "lepewsan",
        "poanching", "xanax_suicide", "bsbsbdbdbjdjdjo", "trynexz2", "paraannual.",
        "tombaura", "r0g0ff", "4shorty7", "lodzyyoc32", "gkv2213", "oxjii",
        "slizerry", "morti699_87849", "stayits", "headshot0379_73668", "ebanat67.",
        "versus2739", "koyen0692", "ono216", "wendyiosik", "wht2312",
        "whitemoon1337", "why.www", "younai007", "wyrthless_1",
        "pswonderfull_45644",
    },
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


def normalized_role_name(name):
    return re.sub(r"\s+", " ", str(name)).strip().casefold().replace("á","a")


def role_name_matches(actual_name, expected_name):
    return normalized_role_name(actual_name) == normalized_role_name(expected_name)


def find_role(guild, role_name):
    return next((role for role in guild.roles if role_name_matches(role.name,role_name)),None)


def has_role(member, role_name):
    return any(role_name_matches(role.name,role_name) for role in member.roles)


def player_league(points):
    if points >= 1600: return "Pro"
    if points >= 1350: return "Division"
    if points >= 1150: return "Qualifications"
    return "Default"


def qualification_status(player_data):
    league=player_league(player_data["points"])
    kd=player_data["kills"]/max(1,player_data["deaths"])
    exempt=league in {"Pro","Division"}
    return league,kd,exempt or kd >= QUALIFICATION_KD,exempt


def can_manage_staff(member):
    return member.id == member.guild.owner_id or has_role(member, STAFF_ROLES["owner"])


def can_administer(member):
    operational=(STAFF_ROLES["admin"],EXTRA_ROLE_SPECS["director"][0],EXTRA_ROLE_SPECS["head_admin"][0],EXTRA_ROLE_SPECS["games_admin"][0],EXTRA_ROLE_SPECS["moderator"][0])
    return can_manage_staff(member) or any(has_role(member,name) for name in operational)


def is_staff_member(member):
    """Стафф, которому доступны warn и timeout через админ-панель."""
    staff_names = set(STAFF_ROLES.values()) | {
        EXTRA_ROLE_SPECS[key][0] for key in (
            "developer", "director", "head_admin", "ticket_admin", "head_ac",
            "games_admin", "anticheat", "moderator", "pro_lead",
        )
    }
    return member.id == member.guild.owner_id or any(has_role(member, name) for name in staff_names)


def is_developer(member):
    return has_role(member, EXTRA_ROLE_SPECS["developer"][0])


def curator_league(member):
    for league in ("qualifications","division","pro"):
        if has_role(member,STAFF_ROLES[f"curator_{league}"]): return league
    return None


def role_panel_keys():
    """Все роли, которыми можно управлять через панель."""
    return set(STAFF_ROLES) | {f"league_{key}" for key in LEAGUE_ROLES} | set(ROLE_PANEL_EXTRAS)


def allowed_role_keys(member):
    """Роли, которые участник может выдавать и снимать по иерархии SEOR."""
    all_roles = role_panel_keys()

    # Владелец Discord-сервера, Owner, General Manager, Developer и Head Admin.
    full_access_roles = (
        STAFF_ROLES["owner"],
        EXTRA_ROLE_SPECS["director"][0],
        EXTRA_ROLE_SPECS["developer"][0],
        EXTRA_ROLE_SPECS["head_admin"][0],
    )
    if member.id == member.guild.owner_id or any(has_role(member, name) for name in full_access_roles):
        return all_roles

    league_all = {"league_default", "league_qualifications", "league_division", "league_pro"}
    if has_role(member, STAFF_ROLES["admin"]):
        return {"moderator", "anticheat", "games_admin", "ticket_admin"} | league_all
    if has_role(member, EXTRA_ROLE_SPECS["ticket_admin"][0]):
        return {"moderator", "anticheat"} | league_all
    if has_role(member, EXTRA_ROLE_SPECS["games_admin"][0]):
        return {"moderator", "anticheat", "league_qualifications", "league_division"}
    if has_role(member, EXTRA_ROLE_SPECS["head_ac"][0]):
        return {"moderator", "anticheat"} | league_all
    if has_role(member, EXTRA_ROLE_SPECS["pro_lead"][0]):
        return {
            "league_qualifications", "league_division", "league_pro",
            "curator_qualifications", "curator_division", "curator_pro",
        }
    if has_role(member, STAFF_ROLES["curator_pro"]):
        return league_all
    if has_role(member, STAFF_ROLES["curator_division"]):
        return {"league_qualifications", "league_division"}
    if has_role(member, STAFF_ROLES["curator_qualifications"]):
        return {"league_qualifications"}
    return set()


def can_use_role_panel(member):
    return bool(allowed_role_keys(member))


async def command_channel_access(interaction):
    if not interaction.guild:
        return False
    command_channels=[c for c in interaction.guild.text_channels if c.name.endswith("команды")]
    return not command_channels or bool(interaction.channel and interaction.channel.id in {c.id for c in command_channels})


async def result_admin_access(interaction):
    return bool(interaction.guild and can_administer(interaction.user))


async def ensure_staff_roles(guild):
    result={}
    legacy_role_renames={
        "👑 Owner":"owner","🛡️ Admin":"admin","⚪ Curator Default":None,
        "🟢 Curator Prospect":"qualifications curator","🟣 Curator Division":"division curator","🔴 Curator Pro":"PRO League curator",
        "🟢 Prospect":"qualifications League","🟣 Division":"division League","🔴 Pro":"pro League",
        "🧬 SEOR Developer":"Developer","🏛️ Project Director":"GENERAL MÁNAGER","🔰 Lead Administrator":"head admin",
        "🎫 Support Administrator":"Ticket admin","⚔️ Anti-Cheat Lead":"head ac","🎮 Match Administrator":"games admin",
        "🧿 Anti-Cheat":"anticheat","🔨 Moderator":"moderator","🎨 Media Creator":"content creator",
        "📡 Stream Partner":"streamer","💠 SEOR Sponsor":"₽","👑 Pro League Lead":"head of pro League","💎 Premium":"Premium",
        "🔴 Pro Warning I":"1/3 pro warn","🔴 Pro Warning II":"2/3 pro warn","🔴 Pro Warning III":"3/3 pro warn",
        "🟣 Division Warning I":"1/3 division warn","🟣 Division Warning II":"2/3 division warn","🟣 Division Warning III":"3/3 division warn",
        "🟡 Qualification Warning I":"1/3 Qual warn","🟡 Qualification Warning II":"2/3 Qual warn","🟡 Qualification Warning III":"3/3 Qual warn",
        "🧪 Division Trial":"test division","🧪 Qualification Trial":"test fpl qualifications",
    }
    for old_name,new_name in legacy_role_renames.items():
        old_role=discord.utils.get(guild.roles,name=old_name)
        if not old_role: continue
        existing=find_role(guild,new_name) if new_name else None
        try:
            if new_name and not existing: await old_role.edit(name=new_name,reason="SEOR: точные названия ролей")
            else: await old_role.delete(reason="SEOR: удаление старой версии роли")
        except discord.Forbidden: pass
    specs={
        "owner": (discord.Color.gold(), discord.Permissions(administrator=True)),
        "admin": (discord.Color.red(), discord.Permissions(manage_guild=True,manage_channels=True,manage_messages=True,moderate_members=True,move_members=True,mute_members=True)),
        "curator_qualifications": (discord.Color.green(), discord.Permissions(move_members=True,mute_members=True)),
        "curator_division": (discord.Color.purple(), discord.Permissions(move_members=True,mute_members=True)),
        "curator_pro": (discord.Color.magenta(), discord.Permissions(move_members=True,mute_members=True)),
    }
    for key,name in STAFF_ROLES.items():
        role=find_role(guild,name)
        role_color,permissions=specs[key]
        if not role:
            try:
                role=await guild.create_role(name=name,color=role_color,permissions=permissions,hoist=True,reason="SEOR: создание служебной роли")
            except discord.Forbidden:
                role=await guild.create_role(name=name,color=role_color,permissions=discord.Permissions.none(),hoist=True,reason="SEOR: создание роли без глобальных прав")
        else:
            try:
                if key=="curator_qualifications":
                    await role.edit(permissions=permissions,hoist=True,reason="SEOR: синхронизация роли без изменения пользовательского цвета")
                else:
                    await role.edit(color=role_color,permissions=permissions,hoist=True,reason="SEOR: синхронизация служебной роли")
            except discord.Forbidden: pass
        result[key]=role
    league_colors={"default":discord.Color.light_grey(),"qualifications":discord.Color.gold(),"division":discord.Color.purple(),"pro":discord.Color.red()}
    for key,name in LEAGUE_ROLES.items():
        role=find_role(guild,name)
        if not role:
            role=await guild.create_role(name=name,color=league_colors[key],permissions=discord.Permissions.none(),hoist=True,reason="SEOR: роль доступа к лиге")
        result[f"league_{key}"]=role
    for key,(name,color_value,permission_values) in EXTRA_ROLE_SPECS.items():
        role=find_role(guild,name)
        permissions=discord.Permissions(**permission_values)
        if not role:
            try:
                role=await guild.create_role(name=name,color=discord.Color(color_value),permissions=permissions,hoist=True,reason="SEOR: расширенная роль персонала")
            except discord.Forbidden:
                role=await guild.create_role(name=name,color=discord.Color(color_value),permissions=discord.Permissions.none(),hoist=True,reason="SEOR: роль без глобальных прав")
        else:
            try: await role.edit(color=discord.Color(color_value),permissions=permissions,hoist=True,reason="SEOR: синхронизация роли")
            except discord.Forbidden: pass
        result[key]=role
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
    e.set_footer(text="Матч до 13 победных раундов · очередь обно��ляется автоматически")
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


def registration_embed(member=None):
    greeting=f"{member.mention}, добро пожаловать!" if member else "Добро пожаловать в соревновательное сообщество SEOR."
    e=discord.Embed(title="⚡ ДОБРО ПОЖАЛОВАТЬ В SEOR",description=f"{greeting}\n\nДо регистрации тебе доступен только этот раздел. Подтверди игровой профиль — после этого откроются основные каналы сервера.",color=color())
    first_step="Открой канал **📋・регистрация** и выбери нужную кнопку." if member else "Выбери **Регистрация** для нового профиля или **Войти по данным** для восстановления старого."
    e.add_field(name="01  НАЖМИ КНОПКУ",value=first_step,inline=False)
    e.add_field(name="02  УКАЖИ ДАННЫЕ",value="В одной форме укажи игровой ник и числовой Standoff 2 ID.",inline=False)
    e.add_field(name="03  ПОЛУЧИ ДОСТУП",value=f"Бот выдаст роли **{REGISTERED_ROLE_NAME}** и **default League**, установит **{STARTING_ELO} ELO** и откроет сервер.",inline=False)
    e.set_footer(text="SEOR CYBER • competitive platform")
    return e


class GameIdModal(discord.ui.Modal, title="Регистрация SEOR"):
    nickname = discord.ui.TextInput(label="Игров��й ник", placeholder="Например: Versus", min_length=2, max_length=24)
    game_id = discord.ui.TextInput(label="Standoff 2 ID", placeholder="Например: 245507174", max_length=30)
    async def on_submit(self, interaction):
        value=str(self.game_id).strip()
        nickname=str(self.nickname).strip()
        if not value.isdigit() or len(value) < 5:
            return await interaction.response.send_message("Укажи корректный числовой Standoff 2 ID.",ephemeral=True)
        if len(nickname)<2:
            return await interaction.response.send_message("Игровой ник должен содержать минимум 2 символа.",ephemeral=True)
        owner=db.game_id_owner(value)
        if owner and (owner["guild_id"]!=interaction.guild_id or owner["user_id"]!=interaction.user.id):
            return await interaction.response.send_message("❌ Этот Standoff 2 ID уже занят. Если это твой старый профиль, используй кнопку **Войти по данным**.",ephemeral=True)
        db.set_registration(interaction.guild_id,interaction.user.id,nickname,value)
        try: await interaction.user.edit(nick=nickname,reason="SEOR: игровой ник при регистрации")
        except discord.Forbidden: pass
        roles=await ensure_staff_roles(interaction.guild)
        role=find_role(interaction.guild,REGISTERED_ROLE_NAME)
        if not role:
            role=await interaction.guild.create_role(name=REGISTERED_ROLE_NAME,color=discord.Color.green(),permissions=discord.Permissions.none(),hoist=False,reason="SEOR: роль регистрации")
        try:
            await interaction.user.add_roles(role,roles["league_default"],reason="SEOR: регистрация и вход в Default League")
        except discord.Forbidden:
            return await interaction.response.send_message("Профиль сохранён, но роли не выданы. Подними роль бота выше ролей `зарегистрирован` и `default League`.",ephemeral=True)
        db.set_points(interaction.guild_id,interaction.user.id,STARTING_ELO)
        await interaction.response.send_message(f"✅ Регистрация завершена. Ник: **{nickname}** · Game ID: **{value}** · роль **default League** · **{STARTING_ELO} ELO**.",ephemeral=True)


class LoginByDataModal(discord.ui.Modal, title="Вход в SEOR FACEIT"):
    nickname = discord.ui.TextInput(label="Игровой ник", placeholder="Ник из старого профиля", min_length=2, max_length=24)
    game_id = discord.ui.TextInput(label="Standoff 2 ID", placeholder="ID из старого профиля", max_length=30)

    async def on_submit(self, interaction):
        nickname=str(self.nickname).strip()
        game_id=str(self.game_id).strip()
        if not game_id.isdigit() or len(game_id)<5:
            return await interaction.response.send_message("Укажи корректный числовой Standoff 2 ID.",ephemeral=True)
        profile=db.restore_registration(interaction.guild_id,interaction.user.id,nickname,game_id)
        if not profile:
            return await interaction.response.send_message("❌ Профиль с таким ником и Standoff 2 ID не найден. Проверь данные или пройди новую регистрацию.",ephemeral=True)
        try: await interaction.user.edit(nick=profile["nickname"],reason="SEOR: восстановление игрового профиля")
        except discord.Forbidden: pass
        roles=await ensure_staff_roles(interaction.guild)
        role=find_role(interaction.guild,REGISTERED_ROLE_NAME)
        if not role:
            role=await interaction.guild.create_role(name=REGISTERED_ROLE_NAME,color=discord.Color.green(),permissions=discord.Permissions.none(),hoist=False,reason="SEOR: роль регистрации")
        try:
            await interaction.user.add_roles(role,roles["league_default"],reason="SEOR: вход по данным и Default League")
        except discord.Forbidden:
            return await interaction.response.send_message("Профиль восстановлен, но роли не выданы. Подними роль бота выше ролей `зарегистрирован` и `default League`.",ephemeral=True)
        db.set_points(interaction.guild_id,interaction.user.id,STARTING_ELO)
        await interaction.response.send_message(f"✅ Вход выполнен. Профиль **{profile['nickname']}** восстановлен · роль **default League** · **{STARTING_ELO} ELO**.",ephemeral=True)


class RegistrationView(discord.ui.View):
    """Постоянные кнопки; обработка выполняется централизованно в on_interaction."""
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label="Регистрация",emoji="⚡",style=discord.ButtonStyle.success,custom_id="seor:registration:start"))
        self.add_item(discord.ui.Button(label="Войти по данным",emoji="🔑",style=discord.ButtonStyle.primary,custom_id="seor:registration:login"))


def match_ocr_players(guild,match,analysis):
    player_ids=[int(x) for x in (match["team_a"]+","+match["team_b"]).split(",") if x]
    candidates=[]
    for user_id in player_ids:
        member=guild.get_member(user_id)
        player=db.player(guild.id,user_id)
        names=[]
        if member:
            names=[player.get("nickname") or member.display_name,member.display_name,member.name]
        candidates.append({"user_id":user_id,"member":member,"game_id":str(player.get("game_id") or ""),"names":names})
    used=set(); matched=[]
    def clean(value): return re.sub(r"[^a-zа-яё0-9]","",str(value).lower())
    for stat in analysis.get("players",[]):
        selected=None
        game_id=str(stat.get("game_id") or "")
        if game_id:
            selected=next((c for c in candidates if c["game_id"]==game_id and c["user_id"] not in used),None)
        if not selected:
            source=clean(stat.get("name"))
            best_score=0
            for candidate in candidates:
                if candidate["user_id"] in used: continue
                for name in candidate["names"]:
                    target=clean(name)
                    score=SequenceMatcher(None,source,target).ratio() if source and target else 0
                    if source in target or target in source: score=max(score,0.86)
                    if score>best_score: best_score=score; selected=candidate
            if best_score<0.68: selected=None
        item=dict(stat)
        if selected:
            item["user_id"]=selected["user_id"]
            used.add(selected["user_id"])
        matched.append(item)
    analysis["matched_stats"]=matched
    return analysis


def result_review_embed(submission_id,match,analysis,final_score,submitter):
    detected_a=analysis.get("score_a"); detected_b=analysis.get("score_b")
    detected=f"{detected_a}:{detected_b}" if detected_a is not None and detected_b is not None else "не распознан"
    lines_a=[]; lines_b=[]; unmatched=[]
    for item in analysis.get("matched_stats",[])[:10]:
        player=f"<@{item['user_id']}>" if item.get("user_id") else f"`{item.get('name','?')}`"
        game_id=f" · ID `{item['game_id']}`" if item.get("game_id") else ""
        line=f"{player}{game_id}\n`{item.get('kills',0):02}/{item.get('deaths',0):02}/{item.get('assists',0):02}` · MVP **{item.get('mvp',0)}**"
        team=str(item.get("team") or "").upper()
        if not item.get("user_id"):
            unmatched.append(f"⚠️ {item.get('name','?')}")
        (lines_b if team=="B" else lines_a).append(line)
    confidence=analysis.get("confidence",0)*100
    has_error=bool(analysis.get("error"))
    embed_color=discord.Color.red() if has_error else (discord.Color.green() if confidence>=80 else discord.Color.orange())
    e=discord.Embed(
        title=f"Матч #{match['id']} · регистрация №{submission_id}",
        description=f"**Ожидает проверки**  •  отправил {submitter.mention}",
        color=embed_color,
    )
    e.add_field(name="Результат",value=f"Со скриншота: **{detected}**\nК регистрации: **{final_score}**\nИсточник: **автораспознавание**",inline=True)
    e.add_field(name="Матч",value=f"Лига: **{match['league']}**\nКарта: **{analysis.get('map') or match.get('map') or 'не определена'}**\nХост: <@{match['host_id']}>",inline=True)
    e.add_field(name="Распознавание",value=f"Точность: **{confidence:.0f}%**\nМодель: `{analysis.get('model') or 'ручной режим'}`\nИгроков: **{len(analysis.get('matched_stats',[]))}/10**",inline=True)
    e.add_field(name="CT · K / D / A",value="\n".join(lines_a)[:1024] or "Нет распознанных данных",inline=True)
    e.add_field(name="T · K / D / A",value="\n".join(lines_b)[:1024] or "Нет распознанных данных",inline=True)
    notes=[]
    if analysis.get("notes"): notes.append(str(analysis["notes"]))
    if unmatched: notes.append("Не привязаны: "+", ".join(unmatched))
    if has_error:
        raw=str(analysis["error"])
        if "404" in raw or "NOT_FOUND" in raw or "no longer available" in raw:
            raw="Модель Gemini из настроек больше недоступна. Бот попробовал актуальную модель; если ошибка осталась, проверь GEMINI_VISION_MODEL и доступ API."
        notes.append("⚠️ "+raw[:700])
    e.add_field(name="Проверка модератором",value=("\n".join(notes)[:1024] if notes else "Сверь счёт, команды и статистику со скриншотом."),inline=False)
    e.set_footer(text="SEOR FACEIT · принять только после сверки скриншота")
    return e


class ResultSubmitView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Отправить результат", emoji="📌", style=discord.ButtonStyle.success, custom_id="result:submit")
    async def submit(self, interaction, button):
        await interaction.response.send_modal(ResultSubmitModal())


class ResultSubmitModal(discord.ui.Modal, title="Отправка результата"):
    def __init__(self):
        super().__init__()
        self.match_id_input=discord.ui.TextInput(placeholder="Например: 700",required=True,min_length=1,max_length=10)
        self.screenshot_upload=discord.ui.FileUpload(required=True,min_values=1,max_values=1,custom_id="result_screenshot")
        self.add_item(discord.ui.Label(
            text="Номер матча",
            description="Укажи только номер без символа #",
            component=self.match_id_input,
        ))
        self.add_item(discord.ui.Label(
            text="Скриншот итоговой таблицы",
            description="Полный скрин с итоговым счётом и статистикой игроков",
            component=self.screenshot_upload,
        ))

    async def on_submit(self,interaction):
        try:
            match_id=int(self.match_id_input.value.strip())
            if match_id<=0: raise ValueError
        except ValueError:
            return await interaction.response.send_message("Укажи корректный номер матча.",ephemeral=True)
        if not self.screenshot_upload.values:
            return await interaction.response.send_message("Прикрепи скриншот матча.",ephemeral=True)
        await interaction.response.defer(ephemeral=True,thinking=True)
        await process_result_submission(interaction,match_id,self.screenshot_upload.values[0])


async def process_result_submission(interaction,match_id,attachment):
    match=db.match(match_id)
    if not match:
        return await interaction.followup.send("Матч с таким номером не найден.",ephemeral=True)
    players={int(x) for x in (match["team_a"]+","+match["team_b"]).split(",") if x}
    if interaction.user.id not in players and not interaction.user.guild_permissions.manage_guild:
        return await interaction.followup.send("Ты не являешься участником этого матча.",ephemeral=True)
    content_type=(attachment.content_type or "").lower()
    if not content_type.startswith("image/") and not attachment.filename.lower().endswith((".png",".jpg",".jpeg",".webp")):
        return await interaction.followup.send("Прикрепи скриншот в формате PNG, JPG или WEBP.",ephemeral=True)
    review=next((c for c in interaction.guild.text_channels if c.name.endswith("регистрация-игр")),None)
    if not review:
        return await interaction.followup.send("Канал `регистрация-игр` не найден. Администратору нужно повторно выполнить `/setup`.",ephemeral=True)
    try:
        image_bytes=await attachment.read()
        analysis=await analyze_screenshot(image_bytes,content_type or "image/png")
        analysis=match_ocr_players(interaction.guild,match,analysis)
    except Exception as exc:
        analysis={"error":str(exc)[:300],"score_a":None,"score_b":None,"map":None,"confidence":0,"matched_stats":[]}
    detected_a,detected_b=analysis.get("score_a"),analysis.get("score_b")
    detected_valid=isinstance(detected_a,int) and isinstance(detected_b,int) and (detected_a==13 or detected_b==13) and detected_a!=detected_b and min(detected_a,detected_b)>=0 and analysis.get("confidence",0)>=0.55
    if not detected_valid:
        error=""
        if analysis.get("error"):
            raw=str(analysis["error"])
            error=" Модель распознавания недоступна — проверь `GEMINI_VISION_MODEL=gemini-3.6-flash` и `GEMINI_API_KEY`." if ("404" in raw or "NOT_FOUND" in raw) else f" Ошибка AI: `{raw[:180]}`"
        return await interaction.followup.send("❌ Не удалось уверенно прочитать итоговый счёт. Отправь более чёткий полный скриншот таблицы матча."+error,ephemeral=True)
    final_a,final_b=detected_a,detected_b
    analysis["registered_score"]=[final_a,final_b]
    submission_id=db.create_submission(interaction.guild_id,match_id,interaction.user.id,final_a,final_b,attachment.url,json.dumps(analysis,ensure_ascii=False))
    e=result_review_embed(submission_id,match,analysis,f"{final_a}:{final_b}",interaction.user)
    extension="jpg" if "jpeg" in content_type else ("webp" if "webp" in content_type else "png")
    image_name=f"match-{match_id}-result.{extension}"
    e.set_image(url=f"attachment://{image_name}")
    view=discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Принять",emoji="✅",style=discord.ButtonStyle.success,custom_id=f"result:approve:{submission_id}"))
    view.add_item(discord.ui.Button(label="Отклонить",emoji="❌",style=discord.ButtonStyle.danger,custom_id=f"result:reject:{submission_id}"))
    await review.send(embed=e,view=view,file=discord.File(io.BytesIO(image_bytes),filename=image_name))
    await interaction.followup.send(f"✅ Скриншот распознан. Результат №{submission_id} отправлен модераторам.",ephemeral=True)


class GameLookupModal(discord.ui.Modal, title="Поиск профил��"):
    game_id = discord.ui.TextInput(label="Игровой ID", placeholder="Например: 132699411", max_length=30)

    async def on_submit(self, interaction):
        p=db.player_by_game_id(interaction.guild_id,str(self.game_id).strip())
        if not p:
            return await interaction.response.send_message("Игрок с таким ID не найден.",ephemeral=True)
        await interaction.response.defer(ephemeral=True,thinking=True)
        member=interaction.guild.get_member(p["user_id"])
        name=p.get("nickname") or (member.display_name if member else f"Игрок {p['user_id']}")
        recent=[]
        for match in db.recent_matches(interaction.guild_id,50):
            ids=set((match["team_a"]+","+match["team_b"]).split(","))
            if str(p["user_id"]) in ids: recent.append(match)
        avatar_url=str(member.display_avatar.with_size(256).url) if member else ""
        card=await build_profile_card(p,name,avatar_url,recent)
        await interaction.followup.send(file=discord.File(card,"profile.png"),ephemeral=True)


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
    "account":("⚙️","Акка��нт","Игровой ID и данные регистрации."),
    "roles":("���️","Роли","Создание и выдача служебных ролей проекта."),
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
        await i.response.send_message("Используй `/top` и выбери лигу: Default, Qualifications, Division или Pro.",ephemeral=True)

    async def place(self,i):
        rows=db.leaders(i.guild_id,1000); pos=next((n for n,p in enumerate(rows,1) if p["user_id"]==i.user.id),None); p=db.player(i.guild_id,i.user.id)
        await i.response.send_message(f"📍 Твоё место: **#{pos or '—'}**, рейтинг: **{p['points']} ELO**.",ephemeral=True)

    async def norms(self,i):
        await i.response.send_message(f"📗 Квалификация: **K/D {QUALIFICATION_KD:.2f}**. Игроки лиг **Division** и **Pro** освобождены от норматива.\n\nЛиги по ELO: Default 1000 · Qualifications 1150 · Division 1350 · Pro 1600.",ephemeral=True)

    async def matches(self,i): await send_recent_matches(i)

    async def party_create(self,i): await i.response.send_message("Используй `/party create` и выбери лигу: Default, Qualifications, Pro или PC.",ephemeral=True)
    async def party_show(self,i):
        party=db.party_for_user(i.guild_id,i.user.id)
        if not party: return await i.response.send_message("👥 Ты не состоишь в активном пати.",ephemeral=True)
        await i.response.send_message(embed=party_embed(party),ephemeral=True)
    async def party_leave(self,i):
        result=db.leave_party(i.guild_id,i.user.id)
        await i.response.send_message("🚪 Ты покинул пати." if result!="not_in_party" else "Ты не состоишь в пати.",ephemeral=True)
    async def account(self,i):
        p=db.player(i.guild_id,i.user.id)
        await i.response.send_message(f"⚙️ Discord: {i.user.mention}\nИгровой ID: `{p['game_id'] or 'не указан'}`\nELO: **{p['points']}**\nМатчей: **{p['games']}**",ephemeral=True)

    async def back(self,i):
        await i.response.edit_message(embed=dashboard_home_embed(),view=DashboardView())

    async def role_panel(self,i):
        if not can_use_role_panel(i.user):
            return await i.response.send_message("У тебя нет доступа к управлению ролями.",ephemeral=True)
        await i.response.send_message(embed=discord.Embed(title="🛡️ Управление ролями",description="Выбери участника и роль, затем нажми **Выдать** или **Снять**. Доступные действия ограничены иерархией персонала.",color=color()),view=RolePanelView(i.user),ephemeral=True)

    async def create_roles(self,i):
        if not can_manage_staff(i.user):
            return await i.response.send_message("Создавать роли может только владелец сервера или Owner.",ephemeral=True)
        await ensure_staff_roles(i.guild)
        await i.response.send_message("Служебные роли созданы и синхронизированы.",ephemeral=True)


class StaffMemberSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="Выбери участника",min_values=1,max_values=1,row=0)
    async def callback(self,interaction):
        member=self.values[0]
        self.view.target_id=member.id
        self.placeholder=f"Участник: {member.display_name}"[:150]
        embed=discord.Embed(title="🛡️ Управление ролями",description=f"Участник выбран: {member.mention}\nТеперь выбери доступную роль.",color=color())
        await interaction.response.edit_message(embed=embed,view=self.view)


class StaffRoleSelect(discord.ui.Select):
    def __init__(self, allowed_keys):
        options=[discord.SelectOption(label=name,value=key,description="Служебная роль") for key,name in STAFF_ROLES.items() if key in allowed_keys]
        options += [discord.SelectOption(label=name,value=f"league_{key}",description="Доступ игрока к лиге") for key,name in LEAGUE_ROLES.items() if f"league_{key}" in allowed_keys]
        options += [discord.SelectOption(label=EXTRA_ROLE_SPECS[key][0],value=key,description="Расширенная роль SEOR") for key in ROLE_PANEL_EXTRAS if key in allowed_keys]
        super().__init__(placeholder="Выбери доступную роль",options=options,min_values=1,max_values=1,row=1)
    async def callback(self,interaction):
        self.view.role_key=self.values[0]
        selected=next((option.label for option in self.options if option.value==self.values[0]),self.values[0])
        self.placeholder=f"Роль: {selected}"[:150]
        member=interaction.guild.get_member(self.view.target_id) if self.view.target_id else None
        who=member.mention if member else "сначала выбери участника"
        embed=discord.Embed(title="🛡️ Управление ролями",description=f"Участник: {who}\nРоль: **{selected}**\nНажми **Выдать** или **Снять**.",color=color())
        await interaction.response.edit_message(embed=embed,view=self.view)


class RolePanelView(discord.ui.View):
    def __init__(self, manager):
        super().__init__(timeout=300)
        self.target_id=None; self.role_key=None
        self.add_item(StaffMemberSelect()); self.add_item(StaffRoleSelect(allowed_role_keys(manager)))

    async def on_error(self,interaction,error,item):
        print(f"Role panel error: {error!r}",flush=True)
        message="Ошибка панели ролей. Попробуй заново или используй `/league_role`."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message,ephemeral=True)
            else:
                await interaction.response.send_message(message,ephemeral=True)
        except discord.HTTPException:
            pass

    async def reply(self,interaction,message):
        if interaction.response.is_done():
            await interaction.followup.send(message,ephemeral=True)
        else:
            await interaction.response.send_message(message,ephemeral=True)

    async def selected(self,interaction):
        if not can_use_role_panel(interaction.user):
            await self.reply(interaction,"Недостаточно прав."); return None,None
        if not self.target_id or not self.role_key:
            await self.reply(interaction,"Сначала выбери участника и роль."); return None,None
        if self.role_key not in allowed_role_keys(interaction.user):
            await self.reply(interaction,"По иерархии персонала ты не можешь выдавать или снимать эту роль."); return None,None
        member=interaction.guild.get_member(self.target_id)
        roles=await ensure_staff_roles(interaction.guild)
        role=roles.get(self.role_key)
        if role and role >= interaction.guild.me.top_role:
            await self.reply(interaction,"Бот не может управлять этой ролью: владелец сервера должен поднять роль бота выше ролей лиг в списке ролей Discord.")
            return None,None
        return member,role

    @discord.ui.button(label="Выдать",emoji="✅",style=discord.ButtonStyle.success,row=2)
    async def give(self,interaction,button):
        await interaction.response.defer(ephemeral=True,thinking=True)
        member,role=await self.selected(interaction)
        if not member or not role: return
        try:
            await member.add_roles(role,reason=f"SEOR dashboard: {interaction.user}")
        except discord.Forbidden:
            return await interaction.followup.send("Не удалось выдать роль: подними роль бота выше выдаваемой роли и включи ему право `Управлять ролями`.",ephemeral=True)
        await interaction.followup.send(f"{role.mention} выдана участнику {member.mention}.",ephemeral=True)

    @discord.ui.button(label="Снять",emoji="➖",style=discord.ButtonStyle.danger,row=2)
    async def remove(self,interaction,button):
        await interaction.response.defer(ephemeral=True,thinking=True)
        member,role=await self.selected(interaction)
        if not member or not role: return
        if member.id==interaction.guild.owner_id and self.role_key=="owner":
            return await interaction.followup.send("Нельзя снять Owner с владельца сервера.",ephemeral=True)
        try:
            await member.remove_roles(role,reason=f"SEOR dashboard: {interaction.user}")
        except discord.Forbidden:
            return await interaction.followup.send("Роль бота должна находиться выше снимаемой роли.",ephemeral=True)
        await interaction.followup.send(f"{role.mention} снята с участника {member.mention}.",ephemeral=True)


class DashboardQuickView(discord.ui.View):
    def __init__(self): super().__init__(timeout=300)
    @discord.ui.button(label="Профиль",emoji="👤",style=discord.ButtonStyle.primary,row=0)
    async def profile(self,i,b): await send_profile(i)
    @discord.ui.button(label="Последние матчи",emoji="🎮",style=discord.ButtonStyle.primary,row=0)
    async def matches(self,i,b): await send_recent_matches(i)
    @discord.ui.button(label="Отправить результат",emoji="📤",style=discord.ButtonStyle.success,row=0)
    async def result(self,i,b): await i.response.send_modal(ResultSubmitModal())
    @discord.ui.button(label="Топ лиги",emoji="🏆",style=discord.ButtonStyle.secondary,row=1)
    async def top(self,i,b): await i.response.send_message(embed=league_top_embed(),view=LeagueTopView(),ephemeral=True)
    @discord.ui.button(label="Моё пати",emoji="👥",style=discord.ButtonStyle.secondary,row=1)
    async def party(self,i,b):
        party=db.party_for_user(i.guild_id,i.user.id)
        if not party: return await i.response.send_message("Ты не состоишь в пати. Создай его через `/party create`.",ephemeral=True)
        await i.response.send_message(embed=party_embed(party),ephemeral=True)
    @discord.ui.button(label="Игровой ID",emoji="🪪",style=discord.ButtonStyle.secondary,row=1)
    async def game_id(self,i,b): await i.response.send_modal(GameIdModal())
    @discord.ui.button(label="Управление ролями",emoji="🛡️",style=discord.ButtonStyle.danger,row=2)
    async def roles(self,i,b):
        if not can_use_role_panel(i.user): return await i.response.send_message("У тебя нет доступа к управлению ролями.",ephemeral=True)
        await i.response.send_message(embed=discord.Embed(title="🛡️ Управление ролями",description="Выбери участника и роль.",color=discord.Color.red()),view=RolePanelView(i.user),ephemeral=True)


class DashboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Открыть панель",emoji="🎛️",style=discord.ButtonStyle.success,custom_id="dashboard:open")
    async def open_panel(self,interaction,button):
        try:
            await interaction.response.send_message(embed=dashboard_home_embed(),view=DashboardQuickView(),ephemeral=True)
        except Exception as exc:
            print(f"Dashboard open error: {exc!r}",flush=True)
            if not interaction.response.is_done():
                await interaction.response.send_message("Не удалось открыть панель. Ошибка записана в Railway Logs.",ephemeral=True)

    @discord.ui.button(label="Управление ролями",emoji="🛡️",style=discord.ButtonStyle.danger,custom_id="dashboard:roles")
    async def open_roles(self,interaction,button):
        if not can_use_role_panel(interaction.user):
            return await interaction.response.send_message("Этот раздел доступен owner и кураторам лиг.",ephemeral=True)
        await interaction.response.send_message(embed=discord.Embed(title="🛡️ Роли и доступ к лигам",description="Выбери участника и роль. В списке показываются только роли, доступные тебе по иерархии.",color=discord.Color.red()),view=RolePanelView(interaction.user),ephemeral=True)


async def send_staff_log(guild,channel_suffix,title,description,log_color=None):
    channel=next((c for c in guild.text_channels if c.name.endswith(channel_suffix)),None)
    if channel:
        try: await channel.send(embed=discord.Embed(title=title,description=description,color=log_color or color()))
        except discord.HTTPException: pass


class SanctionModal(discord.ui.Modal,title="Выдать санкцию"):
    user_id=discord.ui.TextInput(label="Discord ID участника",placeholder="123456789012345678",max_length=20)
    action=discord.ui.TextInput(label="Действие",placeholder="warn / timeout / kick / ban",max_length=10)
    duration=discord.ui.TextInput(label="Минуты для timeout",placeholder="Например: 60",required=False,max_length=6)
    reason=discord.ui.TextInput(label="Причина",style=discord.TextStyle.paragraph,max_length=500)
    async def on_submit(self,interaction):
        if not is_staff_member(interaction.user): return await interaction.response.send_message("Нет доступа.",ephemeral=True)
        try: member=interaction.guild.get_member(int(str(self.user_id).strip()))
        except ValueError: member=None
        if not member: return await interaction.response.send_message("Участник не найден.",ephemeral=True)
        action=str(self.action).strip().lower(); reason=str(self.reason).strip()
        if action not in {"warn", "предупреждение", "timeout"} and not can_administer(interaction.user):
            return await interaction.response.send_message("Все стафф-роли могут выдавать только `warn` и `timeout`. Kick и ban доступны старшей администрации.",ephemeral=True)
        try:
            if action in {"warn","предупреждение"}:
                try: await member.send(f"⚠️ Предупреждение на **{interaction.guild.name}**: {reason}")
                except discord.HTTPException: pass
            elif action=="timeout":
                minutes=max(1,min(40320,int(str(self.duration) or "60")))
                await member.timeout(timedelta(minutes=minutes),reason=reason)
            elif action=="kick": await member.kick(reason=reason)
            elif action=="ban": await member.ban(reason=reason,delete_message_seconds=0)
            else: return await interaction.response.send_message("Действие: `warn`, `timeout`, `kick` или `ban`.",ephemeral=True)
        except (discord.Forbidden,discord.HTTPException,ValueError):
            return await interaction.response.send_message("Не удалось применить санкцию. Проверь права и длительность.",ephemeral=True)
        await send_staff_log(interaction.guild,"общий-журнал","⚖️ Санкция применена",f"Участник: {member.mention}\nДействие: **{action}**\nПричина: {reason}\nАдминистратор: {interaction.user.mention}",discord.Color.orange())
        await interaction.response.send_message(f"✅ Санкция **{action}** применена к {member.mention}.",ephemeral=True)


class MatchAdminModal(discord.ui.Modal,title="Управление матчем"):
    match_id=discord.ui.TextInput(label="Номер матча",max_length=10)
    action=discord.ui.TextInput(label="Действие",placeholder="info или finish",max_length=10)
    score=discord.ui.TextInput(label="Счёт для finish",placeholder="13:9",required=False,max_length=7)
    async def on_submit(self,interaction):
        try: match_id=int(str(self.match_id)); match=db.match(match_id)
        except ValueError: match=None
        if not match: return await interaction.response.send_message("Матч не найден.",ephemeral=True)
        action=str(self.action).strip().lower()
        if action=="info":
            return await interaction.response.send_message(embed=discord.Embed(title=f"🎮 Матч #{match_id}",description=f"Лига: **{match['league']}**\nКарта: **{match['map']}**\nСтатус: **{match['status']}**\nСчёт: **{match['score_a']}:{match['score_b']}**",color=color()),ephemeral=True)
        if action!="finish": return await interaction.response.send_message("Действие: `info` или `finish`.",ephemeral=True)
        try:
            a,b=[int(x) for x in str(self.score).replace("-",":").split(":",1)]
            assert (a==13 or b==13) and a!=b
        except Exception: return await interaction.response.send_message("Укажи корректный счёт, например `13:9`.",ephemeral=True)
        if not db.finish_match(match_id,a,b): return await interaction.response.send_message("Матч уже завершён.",ephemeral=True)
        await send_staff_log(interaction.guild,"журнал-матчей","🎮 Матч завершён",f"Матч **#{match_id}** · счёт **{a}:{b}** · администратор {interaction.user.mention}",discord.Color.green())
        await interaction.response.send_message(f"✅ Матч #{match_id} завершён: **{a}:{b}**.",ephemeral=True)


class CloseTicketModal(discord.ui.Modal,title="Закрыть тикет"):
    channel_id=discord.ui.TextInput(label="ID канала тикета",max_length=20)
    reason=discord.ui.TextInput(label="Причина закрытия",required=False,max_length=200)
    async def on_submit(self,interaction):
        try: channel=interaction.guild.get_channel(int(str(self.channel_id)))
        except ValueError: channel=None
        if not channel or not (channel.topic or "").startswith("ticket-owner:"):
            return await interaction.response.send_message("Канал тикета не найден.",ephemeral=True)
        name=channel.name
        await send_staff_log(interaction.guild,"журнал-тикетов","🔒 Тикет закрыт",f"Канал: **{name}**\nПричина: {str(self.reason) or 'не указана'}\nЗакрыл: {interaction.user.mention}")
        await interaction.response.send_message(f"Тикет **{name}** закрыт.",ephemeral=True)
        await channel.delete(reason=f"SEOR ticket closed by {interaction.user}")


class StaffControlView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    async def allowed(self,i):
        if can_administer(i.user) or can_use_role_panel(i.user): return True
        await i.response.send_message("Нет доступа к панели штаба.",ephemeral=True); return False
    @discord.ui.button(label="Санкции",emoji="⚖️",style=discord.ButtonStyle.danger,custom_id="staff:sanction",row=0)
    async def sanctions(self,i,b):
        if not is_staff_member(i.user):
            return await i.response.send_message("Нет доступа к санкциям.",ephemeral=True)
        await i.response.send_modal(SanctionModal())
    @discord.ui.button(label="Роли",emoji="🛡️",style=discord.ButtonStyle.primary,custom_id="staff:roles",row=0)
    async def roles(self,i,b):
        if await self.allowed(i): await i.response.send_message(embed=discord.Embed(title="🛡️ Управление ролями",description="Выбери участника и доступную роль.",color=color()),view=RolePanelView(i.user),ephemeral=True)
    @discord.ui.button(label="Матчи",emoji="🎮",style=discord.ButtonStyle.primary,custom_id="staff:matches",row=0)
    async def matches(self,i,b):
        if await self.allowed(i): await i.response.send_modal(MatchAdminModal())
    @discord.ui.button(label="Результаты",emoji="✅",style=discord.ButtonStyle.success,custom_id="staff:results",row=0)
    async def results(self,i,b):
        if not await self.allowed(i): return
        channels=[c.mention for c in i.guild.text_channels if c.name.endswith(("проверка-результатов","регистрация-игр"))]
        await i.response.send_message("Проверка результатов: "+(" · ".join(channels) or "каналы не найдены"),ephemeral=True)
    @discord.ui.button(label="Тикеты",emoji="🎫",style=discord.ButtonStyle.secondary,custom_id="staff:tickets",row=1)
    async def tickets(self,i,b):
        if not await self.allowed(i): return
        tickets=[c.mention for c in i.guild.text_channels if (c.topic or "").startswith("ticket-owner:")]
        await i.response.send_message("Открытые тикеты:\n"+("\n".join(tickets) or "Нет открытых тикетов."),ephemeral=True)
    @discord.ui.button(label="Закрыть тикет",emoji="🔒",style=discord.ButtonStyle.danger,custom_id="staff:close_ticket",row=1)
    async def close_ticket(self,i,b):
        if await self.allowed(i): await i.response.send_modal(CloseTicketModal())
    @discord.ui.button(label="Аудит",emoji="📡",style=discord.ButtonStyle.secondary,custom_id="staff:audit",row=1)
    async def audit(self,i,b):
        if not await self.allowed(i): return
        channels=[c.mention for c in i.guild.text_channels if "журнал" in c.name or c.name.endswith("логи-бота")]
        await i.response.send_message("Журналы аудита:\n"+(" · ".join(channels) or "Каналы не найдены."),ephemeral=True)


class TicketTypeSelect(discord.ui.Select):
    TICKET_TYPES = {
        "cheats": ("🛡️", "Подозрение на нечестную игру", "Сообщение о возможных читах", ("owner","director","head_admin","head_ac","anticheat")),
        "player": ("🚫", "Жалоба на игрока", "Нарушения, оскорбления или срыв матча", ("owner","director","head_admin","admin","ticket_admin","moderator")),
        "match": ("🎯", "Спор по матчу", "Результат матча или техническая проблема", ("owner","director","head_admin","admin","games_admin","curator_qualifications","curator_division","curator_pro")),
        "staff": ("⚖️", "Обращение по персоналу", "Рассматривает только старшее руководство", ("owner","director","head_admin")),
        "appeal": ("📄", "Обжалование наказания", "Пересмотр выданного варна или санкции", ("owner","director","head_admin","admin","ticket_admin")),
        "other": ("❓", "Другой вопрос", "Общая помощь по остальным вопросам", ("owner","director","head_admin","admin","ticket_admin")),
    }

    def __init__(self):
        options=[discord.SelectOption(label=title,value=key,emoji=emoji,description=description) for key,(emoji,title,description,_) in self.TICKET_TYPES.items()]
        super().__init__(placeholder="Выбери раздел обращения",options=options,custom_id="ticket:type",min_values=1,max_values=1)

    async def callback(self, interaction):
        key=self.values[0]
        emoji,title,description,staff_keys=self.TICKET_TYPES[key]
        guild=interaction.guild
        staff_roles=await ensure_staff_roles(guild)
        existing=next((c for c in guild.text_channels if (c.topic or "").startswith(f"ticket-owner:{interaction.user.id}")),None)
        if existing:
            return await interaction.response.send_message(f"У тебя уже есть открытый тикет: {existing.mention}",ephemeral=True)
        category=discord.utils.get(guild.categories,name="🎫 TICKETS") or await guild.create_category("🎫 TICKETS")
        overwrites={
            guild.default_role:discord.PermissionOverwrite(view_channel=False),
            interaction.user:discord.PermissionOverwrite(view_channel=True,send_messages=True,attach_files=True,read_message_history=True),
            guild.me:discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_channels=True,manage_messages=True),
        }
        for staff_key in staff_keys:
            role=staff_roles.get(staff_key)
            if role:
                overwrites[role]=discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_messages=True,read_message_history=True)
        safe_name=re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ_-]+","-",interaction.user.name).strip("-") or str(interaction.user.id)
        channel=await guild.create_text_channel(f"{key}-{safe_name}"[:90],category=category,topic=f"ticket-owner:{interaction.user.id}:{key}",overwrites=overwrites)
        # Старшее руководство получает доступ к тикету, но не упоминается.
        silent_staff={"owner","developer","director","admin","head_admin"}
        staff_mentions=" ".join(staff_roles[k].mention for k in staff_keys if k not in silent_staff and staff_roles.get(k))
        content=" ".join(part for part in (interaction.user.mention,staff_mentions) if part)
        embed=discord.Embed(title=f"{emoji} {title}",description=f"{description}. Опиши ситуацию и приложи доказательства.",color=color())
        await channel.send(content=content,embed=embed)
        control=discord.Embed(title="🔒 Управление тикетом",description="Автор обращения или сотрудник администрации может закрыть тикет кнопкой ниже.",color=discord.Color.red())
        await channel.send(embed=control,view=TicketChannelView())
        await send_staff_log(guild,"журнал-тикетов","🎫 Создан новый тикет",f"Раздел: **{title}**\nАвтор: {interaction.user.mention}\nКанал: {channel.mention}",discord.Color.purple())
        await interaction.response.send_message(f"Тикет создан: {channel.mention}",ephemeral=True)


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketTypeSelect())


def ticket_owner_id(channel):
    topic=channel.topic or ""
    if not topic.startswith("ticket-owner:"):
        return None
    try:
        return int(topic.split(":",2)[1])
    except (ValueError,IndexError):
        return None


def can_close_ticket(member,channel):
    owner_id=ticket_owner_id(channel)
    return owner_id==member.id or is_staff_member(member)


class CloseCurrentTicketModal(discord.ui.Modal,title="Закрытие тикета"):
    reason=discord.ui.TextInput(label="Причина",placeholder="Причина закрытия",required=False,max_length=300)

    async def on_submit(self,interaction):
        channel=interaction.channel
        if not isinstance(channel,discord.TextChannel) or ticket_owner_id(channel) is None:
            return await interaction.response.send_message("Эта кнопка работает только внутри тикета.",ephemeral=True)
        if not can_close_ticket(interaction.user,channel):
            return await interaction.response.send_message("Закрыть тикет может его автор или сотрудник администрации.",ephemeral=True)
        reason=str(self.reason).strip() or "не указана"
        await send_staff_log(interaction.guild,"журнал-тикетов","🔒 Тикет закрыт",f"Канал: **{channel.name}**\nПричина: {reason}\nЗакрыл: {interaction.user.mention}")
        await interaction.response.send_message("Тикет закрывается…",ephemeral=True)
        await asyncio.sleep(1)
        try:
            await channel.delete(reason=f"SEOR FACEIT ticket closed by {interaction.user}: {reason}")
        except discord.Forbidden:
            pass


class TicketChannelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Закрыть тикет",emoji="🔒",style=discord.ButtonStyle.danger,custom_id="ticket:close:button")
    async def close_ticket(self,interaction,button):
        if not isinstance(interaction.channel,discord.TextChannel) or ticket_owner_id(interaction.channel) is None:
            return await interaction.response.send_message("Эта кнопка работает только внутри тикета.",ephemeral=True)
        if not can_close_ticket(interaction.user,interaction.channel):
            return await interaction.response.send_message("Закрыть тикет может его автор или сотрудник администрации.",ephemeral=True)
        await interaction.response.send_modal(CloseCurrentTicketModal())


async def ensure_ticket_close_buttons(guild):
    """Добавить кнопку только в старые тикеты, где панели закрытия ещё нет."""
    changed=0
    for channel in guild.text_channels:
        if ticket_owner_id(channel) is None:
            continue
        found=False
        try:
            async for message in channel.history(limit=30):
                if message.author==guild.me and any(embed.title=="🔒 Управление тикетом" for embed in message.embeds):
                    found=True
                    break
        except discord.HTTPException:
            continue
        if found:
            continue
        control=discord.Embed(title="🔒 Управление тикетом",description="Автор обращения или сотрудник администрации может закрыть тикет кнопкой ниже.",color=discord.Color.red())
        try:
            await channel.send(embed=control,view=TicketChannelView())
            changed+=1
        except discord.HTTPException:
            pass
    return changed


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


async def send_recent_matches(interaction,limit:int=10):
    await interaction.response.defer(ephemeral=True,thinking=True)
    rows=db.recent_matches(interaction.guild_id,limit)
    card=await asyncio.to_thread(build_matches_card,rows)
    await interaction.followup.send(file=discord.File(card,"recent-matches.png"),ephemeral=True)


async def send_league_top(interaction,league_name:str,ephemeral:bool=True):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=ephemeral,thinking=True)
    league_roles=set(LEAGUE_ROLES.values())
    selected=[]
    for player_data in db.leaders(interaction.guild_id,1000):
        member=interaction.guild.get_member(player_data["user_id"])
        if not member: continue
        member_roles={role.name for role in member.roles}
        allowed=LEAGUE_ROLES[league_name.lower()] in member_roles
        if not allowed: continue
        item=dict(player_data)
        item["name"]=item.get("nickname") or member.display_name
        item["avatar_url"]=str(member.display_avatar.with_size(128).url)
        selected.append(item)
        if len(selected)>=10: break
    out=await asyncio.to_thread(build_leaderboard,selected,league_name)
    await interaction.followup.send(file=discord.File(out,f"top-{league_name.lower()}.png"),ephemeral=ephemeral)


class LeagueTopView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Default",emoji="⚪",style=discord.ButtonStyle.secondary,custom_id="top:default",row=0)
    async def default_top(self,i,b): await send_league_top(i,"Default")

    @discord.ui.button(label="Qualifications",emoji="🟡",style=discord.ButtonStyle.secondary,custom_id="top:qualifications",row=0)
    async def qualifications_top(self,i,b): await send_league_top(i,"Qualifications")

    @discord.ui.button(label="Division",emoji="🟣",style=discord.ButtonStyle.secondary,custom_id="top:division",row=0)
    async def division_top(self,i,b): await send_league_top(i,"Division")

    @discord.ui.button(label="Pro",emoji="🔴",style=discord.ButtonStyle.secondary,custom_id="top:pro",row=0)
    async def pro_top(self,i,b): await send_league_top(i,"Pro")


def league_top_embed():
    e=discord.Embed(title="🏆 ТОП СЕРВЕРА",description="Выбери лигу — бот пришлёт красочную карточку топ-10 игроков этой лиги.",color=color())
    e.add_field(name="⚪ Default",value="Участники Default League",inline=True)
    e.add_field(name="🟡 Qualifications",value="Участники квалификации",inline=True)
    e.add_field(name="🟣 Division",value="Участники Division",inline=True)
    e.add_field(name="🔴 Pro",value="Участники Pro",inline=True)
    e.set_footer(text="Топ строится по ELO и учитывает только игроков с ролью лиги")
    return e


async def send_profile(interaction,member=None):
    await interaction.response.defer(ephemeral=True, thinking=True)
    member=member or interaction.user
    p = db.player(interaction.guild_id, member.id)
    recent=[]
    for m in db.recent_matches(interaction.guild_id,50):
        ids=set((m["team_a"]+","+m["team_b"]).split(","))
        if str(member.id) in ids: recent.append(m)
    avatar_url=member.display_avatar.with_size(256).url
    card=await build_profile_card(p,p.get("nickname") or member.display_name,str(avatar_url),recent)
    view=None
    if member.id==interaction.user.id:
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
            e=discord.Embed(title="🗺️ РАСПИК КАРТ",description=f"Капитаны по очереди исключают карты. На ход даётся **{MAP_VETO_TIMEOUT} секунд**. Если капитан не отвечает, бот автоматически банит случайную карту.\n\n**Сейчас ходит:** {self.captain.mention}\n**Дос��упные карты:**\n{available}",color=discord.Color.from_rgb(124,58,237))
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
    e=discord.Embed(title=f"🎮 Матч #{match_id}",description=f"{LEAGUES[league][0]} Лига **{league}**\nКарта: **{map_name}**\nФормат: **до 13 раундов**\nХост: {host.mention}\n\n**Комнаты:** {va.mention} · {vb.mention}\nНажми **Получить ID** — бот автоматически покажет Standoff 2 ID хоста, указанный при регистрации.",color=color())
    e.add_field(name="🛡 CT",value="\n".join(f"• {m.mention}" for m in a))
    e.add_field(name="💣 T",value="\n".join(f"• {m.mention}" for m in b))
    view=discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Получить ID",emoji="🆔",style=discord.ButtonStyle.success,custom_id=f"match:getid:{match_id}"))
    await text.send(content=" ".join(m.mention for m in members),embed=e,view=view)
    await update_queue(lobby)


@bot.event
async def setup_hook():
    db.init_db()
    bot.add_view(QueueView()); bot.add_view(RoomPanel()); bot.add_view(ResultSubmitView()); bot.add_view(DashboardView()); bot.add_view(TicketView()); bot.add_view(TicketChannelView()); bot.add_view(RegistrationView()); bot.add_view(StaffControlView()); bot.add_view(LeagueTopView())
    if GUILD_ID:
        guild=discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
    else:
        await bot.tree.sync()


async def give_default_league_to_registered(guild):
    """Выдать Default League всем зарегистрированным, у кого ещё нет роли лиги."""
    registered=find_role(guild,REGISTERED_ROLE_NAME)
    default_league=find_role(guild,LEAGUE_ROLES["default"])
    if not registered or not default_league:
        return 0
    league_names=set(LEAGUE_ROLES.values())
    changed=0
    for member in guild.members:
        if member.bot or registered not in member.roles:
            continue
        if any(role.name in league_names for role in member.roles):
            continue
        try:
            await member.add_roles(default_league,reason="SEOR: Default League для зарегистрированного игрока")
            changed+=1
        except discord.Forbidden:
            pass
    return changed


@bot.event
async def on_ready():
    print(f"{bot.user} ready")
    await bot.change_presence(activity=discord.Game(f"очередь: {LOBBY_SIZE} игроков"))
    for guild in bot.guilds:
        changed=await give_default_league_to_registered(guild)
        if changed:
            print(f"{guild.name}: Default League выдана {changed} зарегистрированным",flush=True)
        ticket_updates=await ensure_ticket_close_buttons(guild)
        if ticket_updates:
            print(f"{guild.name}: кнопка закрытия добавлена в {ticket_updates} тикетов",flush=True)


@bot.event
async def on_member_join(member):
    if member.bot: return
    try: await member.send(embed=registration_embed(member))
    except discord.HTTPException: pass


@bot.event
async def on_interaction(interaction):
    if interaction.type != discord.InteractionType.component: return
    cid=interaction.data.get("custom_id","")
    if cid in {"seor:registration:start","seor:registration:login"}:
        try:
            if has_role(interaction.user,REGISTERED_ROLE_NAME):
                message="Ты уже зарегистрирован. Для смены ID используй `/set_game_id` в канале команд." if cid.endswith(":start") else "Ты уже вошёл в профиль SEOR."
                return await interaction.response.send_message(message,ephemeral=True)
            modal=GameIdModal() if cid.endswith(":start") else LoginByDataModal()
            return await interaction.response.send_modal(modal)
        except Exception as exc:
            print(f"Registration button error: {exc!r}",flush=True)
            if not interaction.response.is_done():
                return await interaction.response.send_message("Не удалось открыть форму регистрации. Ошибка записана в Railway Logs.",ephemeral=True)
            return
    if cid.startswith("party:accept:") or cid.startswith("party:decline:"):
        _,action,party_id,target_id=cid.split(":")
        if interaction.user.id!=int(target_id):
            return await interaction.response.send_message("Это приглашение предназначено другому участнику.",ephemeral=True)
        if action=="decline":
            return await interaction.response.edit_message(content="❌ Приглашение отклонено.",embed=None,view=None)
        result=db.add_party_member(interaction.guild_id,int(party_id),interaction.user.id)
        messages={"full":"Пати уже заполнено.","already_in_party":"Ты уже состоишь в другом пати.","not_found":"Пати больше не существует."}
        if result!="ok": return await interaction.response.send_message(messages.get(result,"Не удалось вступить в пати."),ephemeral=True)
        party=db.party_for_user(interaction.guild_id,interaction.user.id)
        return await interaction.response.edit_message(content=f"✅ {interaction.user.mention} вступил в пати!",embed=party_embed(party),view=None)
    if cid.startswith("match:getid:"):
        match_id=int(cid.rsplit(":",1)[1]); match_data=db.match(match_id)
        if not match_data:
            return await interaction.response.send_message("Матч не найден.",ephemeral=True)
        player_ids={int(x) for x in (match_data["team_a"]+","+match_data["team_b"]).split(",") if x}
        if interaction.user.id not in player_ids and not can_administer(interaction.user):
            return await interaction.response.send_message("ID доступен только участникам матча.",ephemeral=True)
        host_profile=db.player(interaction.guild_id,match_data["host_id"])
        host_game_id=str(host_profile.get("game_id") or "").strip()
        if not host_game_id:
            return await interaction.response.send_message("У хоста не указан Standoff 2 ID. Хосту нужно добавить его через регистрацию или `/set_game_id`.",ephemeral=True)
        host_member=interaction.guild.get_member(match_data["host_id"])
        host_name=host_member.mention if host_member else (host_profile.get("nickname") or f"игрок {match_data['host_id']}")
        return await interaction.response.send_message(f"🆔 Standoff 2 ID хоста {host_name}: **{host_game_id}**",ephemeral=True)
    elif cid.startswith("result:approve:") or cid.startswith("result:reject:"):
        submission_id = int(cid.rsplit(":", 1)[1])
        sub = db.submission(submission_id)
        if not sub or sub["status"] != "pending":
            return await interaction.response.send_message("Заявка уже обработана или не найдена.", ephemeral=True)
        match_data=db.match(sub["match_id"])
        allowed=can_administer(interaction.user) or (match_data and curator_league(interaction.user)==str(match_data["league"]).lower())
        if not allowed:
            return await interaction.response.send_message("Подтверждать игру может Admin, Owner или куратор этой лиги.", ephemeral=True)
        approved = cid.startswith("result:approve:")
        if approved:
            if not db.finish_match(sub["match_id"], sub["score_a"], sub["score_b"]):
                return await interaction.response.send_message("Матч уже завершён или не найден.", ephemeral=True)
            db.review_submission(submission_id, "approved", interaction.user.id)
            try:
                analysis=json.loads(sub.get("analysis_json") or "{}")
                matched=[item for item in analysis.get("matched_stats",[]) if item.get("user_id")]
                db.apply_player_stats(sub["guild_id"],matched)
            except Exception as exc:
                print(f"Apply screenshot stats error: {exc}",flush=True)
            status, clr = "✅ принят", discord.Color.green()
            history = next((c for c in interaction.guild.text_channels if c.name.endswith("история-игр")), None)
            if history:
                e = discord.Embed(title=f"🎮 Матч #{sub['match_id']}", description=f"Итоговый ��чёт: **{sub['score_a']}:{sub['score_b']}**\nРезультат проверил: {interaction.user.mention}", color=clr)
                e.set_image(url=sub["screenshot_url"])
                await history.send(embed=e)
        else:
            db.review_submission(submission_id, "rejected", interaction.user.id)
            status, clr = "❌ отклонён", discord.Color.red()
        await send_staff_log(interaction.guild,"журнал-матчей",f"🎮 Проверка м��тча #{sub['match_id']}",f"Решение: **{status}**\nМодератор: {interaction.user.mention}\nЗаявка: **#{submission_id}**",clr)
        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        embed.color = clr
        embed.description = (embed.description or "") + f"\n\nСтатус: **{status}**\nПроверил: {interaction.user.mention}"
        await interaction.response.edit_message(embed=embed, view=None)


async def delete_empty_match_room(channel):
    task=asyncio.current_task()
    try:
        await asyncio.sleep(60)
        if not channel.members:
            await channel.delete(reason="Комната матча пуста 1 минуту")
    except (asyncio.CancelledError,discord.HTTPException):
        pass
    finally:
        if match_room_cleanup.get(channel.id) is task:
            match_room_cleanup.pop(channel.id,None)


@bot.event
async def on_voice_state_update(member,before,after):
    if member.bot: return
    if after.channel and after.channel.name.startswith("➕ Создать комнату"):
        registered=discord.utils.get(member.guild.roles,name=REGISTERED_ROLE_NAME)
        overwrites={member.guild.default_role:discord.PermissionOverwrite(view_channel=False,connect=False),member:discord.PermissionOverwrite(view_channel=True,manage_channels=True,move_members=True,mute_members=True,connect=True)}
        if registered: overwrites[registered]=discord.PermissionOverwrite(view_channel=True,connect=True,speak=True)
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


def party_embed(party):
    members="\n".join(f"• <@{uid}>"+(" 👑" if uid==party["leader_id"] else "") for uid in party["members"])
    return discord.Embed(title=f"👥 Пати #{party['id']}",description=f"Лига: **{party['league']}**\nУчастники: **{len(party['members'])}/3**\n\n{members}",color=color())


party_group=app_commands.Group(name="party",description="Управление пати")

@party_group.command(name="create",description="Создать пати в выбранной лиге")
@app_commands.check(command_channel_access)
@app_commands.choices(league=[
    app_commands.Choice(name="Default",value="Default"),
    app_commands.Choice(name="Qualifications",value="Qualifications"),
    app_commands.Choice(name="Pro",value="Pro"),
    app_commands.Choice(name="PC",value="PC"),
])
async def party_create_command(interaction:discord.Interaction,league:app_commands.Choice[str]):
    party_id=db.create_party(interaction.guild_id,interaction.user.id,league.value)
    if not party_id:
        return await interaction.response.send_message("Ты уже состоишь в пати. Сначала используй `/party leave`.",ephemeral=True)
    await interaction.response.send_message(embed=party_embed(db.party_for_user(interaction.guild_id,interaction.user.id)),ephemeral=True)

@party_group.command(name="invite",description="Пригласить участника в своё пати")
@app_commands.check(command_channel_access)
async def party_invite_command(interaction:discord.Interaction,member:discord.Member):
    party=db.party_for_user(interaction.guild_id,interaction.user.id)
    if not party or party["leader_id"]!=interaction.user.id:
        return await interaction.response.send_message("Приглашать может только лидер пати.",ephemeral=True)
    if member.bot or member.id in party["members"]:
        return await interaction.response.send_message("Этого участника нельзя пригласить.",ephemeral=True)
    if len(party["members"])>=3:
        return await interaction.response.send_message("Пати уже заполнено: 3/3.",ephemeral=True)
    view=discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Вступить",emoji="✅",style=discord.ButtonStyle.success,custom_id=f"party:accept:{party['id']}:{member.id}"))
    view.add_item(discord.ui.Button(label="Отклонить",emoji="❌",style=discord.ButtonStyle.secondary,custom_id=f"party:decline:{party['id']}:{member.id}"))
    await interaction.response.send_message(content=f"{member.mention}, тебя приглашают в пати **{party['league']}**.",embed=party_embed(party),view=view)

@party_group.command(name="info",description="Показать своё пати")
@app_commands.check(command_channel_access)
async def party_info_command(interaction:discord.Interaction):
    party=db.party_for_user(interaction.guild_id,interaction.user.id)
    if not party: return await interaction.response.send_message("Ты не состоишь в пати.",ephemeral=True)
    await interaction.response.send_message(embed=party_embed(party),ephemeral=True)

@party_group.command(name="leave",description="Покинуть пати")
@app_commands.check(command_channel_access)
async def party_leave_command(interaction:discord.Interaction):
    result=db.leave_party(interaction.guild_id,interaction.user.id)
    await interaction.response.send_message("🚪 Ты покин��л пати." if result!="not_in_party" else "Ты не состоишь в пати.",ephemeral=True)

bot.tree.add_command(party_group)


@bot.tree.command(name="setup",description="Создать структуру лиг и панели")
@app_commands.default_permissions(administrator=True)
@app_commands.check(command_channel_access)
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction:discord.Interaction):
    await interaction.response.defer(ephemeral=True,thinking=True)
    g=interaction.guild
    try:
        await g.edit(default_notifications=discord.NotificationLevel.only_mentions,reason="SEOR FACEIT: уведомления сервера только по упоминаниям")
    except discord.Forbidden:
        await interaction.followup.send("Не удалось включить режим уведомлений «Только упоминания»: боту нужно право `Управлять сервером`.",ephemeral=True)
    staff_roles=await ensure_staff_roles(g)
    registered_role=find_role(g,REGISTERED_ROLE_NAME)
    if not registered_role:
        registered_role=await g.create_role(name=REGISTERED_ROLE_NAME,color=discord.Color.green(),permissions=discord.Permissions.none(),hoist=False,reason="SEOR: роль регистрации")
    league_roles=[staff_roles[f"league_{key}"] for key in LEAGUE_ROLES]
    for member in g.members:
        if member.bot: continue
        has_saved_profile=bool(db.player(g.id,member.id).get("game_id"))
        is_registered=registered_role in member.roles or has_saved_profile
        if not is_registered: continue
        missing=[]
        if registered_role not in member.roles: missing.append(registered_role)
        if not any(role in member.roles for role in league_roles): missing.append(staff_roles["league_default"])
        if missing:
            try: await member.add_roles(*missing,reason="SEOR: регистрация и Default League")
            except discord.Forbidden: pass

    # /setup синхронизирует только структуру, которой управляет бот.
    # Посторонние пользовательские категории и каналы не затрагиваются.
    # Инкрементальный setup: существующие категории и каналы не удаляются.
    # Создаются только отсутствующие элементы, а права обновляются на нужных элементах.

    async def category(name):
        return discord.utils.get(g.categories, name=name) or await g.create_category(name)
    async def text(cat, name, **kwargs):
        return discord.utils.get(cat.text_channels, name=name) or await g.create_text_channel(name, category=cat, **kwargs)
    async def sync_channels(cat, text_names=(), voice_names=(), preserve_voice_prefixes=()):
        """Не удаляет существующие каналы; создание нужных выполняют следующие вызовы text/voice."""
        return

    async def set_permissions_if_changed(target,role,**values):
        desired=discord.PermissionOverwrite(**values)
        if target.overwrites_for(role).pair()!=desired.pair():
            await target.set_permissions(role,overwrite=desired)

    async def gate_registered(cat,touch_existing_channels=True):
        await set_permissions_if_changed(cat,g.default_role,view_channel=False,connect=False,send_messages=False,use_application_commands=False)
        await set_permissions_if_changed(cat,registered_role,view_channel=True,connect=True,speak=True,send_messages=True,read_message_history=True,use_application_commands=True)
        if not touch_existing_channels:
            return
        for channel in cat.channels:
            if isinstance(channel,discord.TextChannel):
                await set_permissions_if_changed(channel,g.default_role,view_channel=False,send_messages=False,use_application_commands=False)
                await set_permissions_if_changed(channel,registered_role,view_channel=True,send_messages=True,read_message_history=True,use_application_commands=True)
            elif isinstance(channel,discord.VoiceChannel):
                await set_permissions_if_changed(channel,g.default_role,view_channel=False,connect=False)
                await set_permissions_if_changed(channel,registered_role,view_channel=True,connect=True,speak=True)

    onboarding=await category("▶️ SEOR START")
    await onboarding.set_permissions(g.default_role,view_channel=True,send_messages=False,read_message_history=True,use_application_commands=False)
    await onboarding.set_permissions(registered_role,view_channel=False)
    await sync_channels(onboarding,text_names=("📋・регистрация",))
    registration_channel=await text(onboarding,"📋・регистрация")
    await registration_channel.set_permissions(g.default_role,view_channel=True,send_messages=False,read_message_history=True,use_application_commands=False)
    await registration_channel.set_permissions(registered_role,view_channel=False)
    await registration_channel.set_permissions(g.me,view_channel=True,send_messages=True,manage_messages=True)
    async for old_message in registration_channel.history(limit=20):
        if old_message.author==g.me:
            try: await old_message.delete()
            except discord.HTTPException: pass
    await registration_channel.send(embed=registration_embed(),view=RegistrationView())

    info = await category("📡 SEOR INFO")
    info_names=("📣・объявления", "📜・регламент", "🛍️・магазин", "📨・новости-лиги", "🧩・настройка-лобби", "📺・трансляции")
    await sync_channels(info, text_names=info_names)
    for channel_name in info_names:
        await text(info, channel_name)

    start = await category("⌨️ SEOR COMMANDS")
    await start.set_permissions(g.default_role,view_channel=True,send_messages=True,read_message_history=True,use_application_commands=True)
    await sync_channels(start, text_names=("🤖・команды", "📊・дашборд", "🏆・топ-сервера"))
    commands_channel=await text(start, "🤖・команды")
    await commands_channel.set_permissions(g.default_role,view_channel=True,send_messages=True,read_message_history=True,use_application_commands=True)
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
    commands_embed.add_field(name="🎮 Матчи",value="Кнопка **Отправить результат** — форма с номером матча и скриншотом\n`/match_info` — информация о матче",inline=False)
    commands_embed.add_field(name="🛡️ Администрация",value="`/set_nickname` — изменить ник участника на сервере",inline=False)
    commands_embed.set_footer(text="Стандарт квалификации: K/D 1.00 • Division и Pro освобождены")
    await commands_channel.send(embed=commands_embed)
    dashboard = await text(start, "📊・дашборд")
    top_channel = await text(start, "🏆・топ-сервера")
    await top_channel.set_permissions(g.default_role,view_channel=True,send_messages=False,read_message_history=True,use_application_commands=True)
    async for old_message in top_channel.history(limit=20):
        if old_message.author == g.me:
            try: await old_message.delete()
            except discord.HTTPException: pass
    await top_channel.send(embed=league_top_embed(),view=LeagueTopView())
    async for old_message in dashboard.history(limit=20):
        if old_message.author == g.me:
            try: await old_message.delete()
            except discord.HTTPException: pass
    e = dashboard_home_embed()
    await dashboard.send(embed=e, view=DashboardView())

    community = await category("💬 SEOR COMMUNITY")
    community_names=("💭・общий-чат", "🛡️・поиск-клана", "🎯・поиск-игроков", "🔴・чат-pro", "🟣・чат-division", "🟡・чат-qualifications", "🛠️・чат-кураторов")
    await sync_channels(community, text_names=community_names, voice_names=("🌐 Общий голос",))
    community_channels={channel_name:await text(community,channel_name) for channel_name in community_names}
    protected_chats={
        "🔴・чат-pro":("league_pro","curator_pro"),
        "🟣・чат-division":("league_division","curator_division"),
        "🟡・чат-qualifications":("league_qualifications","curator_qualifications"),
    }
    for channel_name,(league_key,curator_key) in protected_chats.items():
        channel=community_channels[channel_name]
        await channel.set_permissions(g.default_role,view_channel=False,send_messages=False,read_message_history=False)
        await channel.set_permissions(staff_roles[league_key],view_channel=True,send_messages=True,read_message_history=True)
        await channel.set_permissions(staff_roles[curator_key],view_channel=True,send_messages=True,manage_messages=True,read_message_history=True)
        await channel.set_permissions(staff_roles["owner"],view_channel=True,send_messages=True,manage_messages=True)
        await channel.set_permissions(staff_roles["admin"],view_channel=True,send_messages=True,manage_messages=True)
    curator_chat=community_channels["🛠️��чат-кураторов"]
    await curator_chat.set_permissions(g.default_role,view_channel=False,send_messages=False,read_message_history=False)
    for curator_key in ("curator_qualifications","curator_division","curator_pro"):
        await curator_chat.set_permissions(staff_roles[curator_key],view_channel=True,send_messages=True,read_message_history=True)
    await curator_chat.set_permissions(staff_roles["owner"],view_channel=True,send_messages=True,manage_messages=True)
    await curator_chat.set_permissions(staff_roles["admin"],view_channel=True,send_messages=True,manage_messages=True)
    if not discord.utils.get(community.voice_channels, name="🌐 Общий голос"):
        await g.create_voice_channel("🌐 Общий голос", category=community, user_limit=99)

    support = await category("🆘 SEOR SUPPORT")
    await sync_channels(support, text_names=("🎫・создать-тикет", "⚠️・наказания"))
    tickets = await text(support, "🎫・создать-тикет")
    await text(support, "⚠️・наказания")
    async for old_message in tickets.history(limit=20):
        if old_message.author==g.me:
            try: await old_message.delete()
            except discord.HTTPException: pass
    e = discord.Embed(title="🎫 ЦЕНТР ОБРАЩЕНИЙ", description="Выбери раздел: нечестная игра, жал��ба на игрока, спор по матчу, обращение по персоналу, обжалование наказания или другой вопрос. Бот создаст приватный канал только для нужной группы персонала.", color=color())
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
            league_role=staff_roles[f"league_{name.lower()}"]
            await cat.set_permissions(g.default_role,view_channel=False,connect=False,send_messages=False,use_application_commands=False)
            await cat.set_permissions(registered_role,view_channel=False,connect=False,send_messages=False,use_application_commands=False)
            await cat.set_permissions(league_role,view_channel=True,connect=True,speak=True,send_messages=True,read_message_history=True,use_application_commands=True)
            await cat.set_permissions(staff_roles["owner"],view_channel=True,connect=True,send_messages=True,move_members=True)
            await cat.set_permissions(staff_roles["admin"],view_channel=True,connect=True,send_messages=True,move_members=True)
            await sync_channels(cat, text_names=("🎮・ranked",), voice_names=(f"🔊 Lobby {i}",), preserve_voice_prefixes=("🛡 CT · #", "💣 T · #"))
            ranked=discord.utils.get(cat.text_channels,name="🎮・ranked") or await g.create_text_channel("🎮・ranked",category=cat)
            lobby=discord.utils.get(cat.voice_channels,name=f"🔊 Lobby {i}")
            if not lobby:
                lobby=next((v for v in cat.voice_channels if is_lobby(v)),None) or await g.create_voice_channel(f"🔊 Lobby {i}",category=cat,user_limit=LOBBY_SIZE)
            if lobby.user_limit != LOBBY_SIZE:
                await lobby.edit(user_limit=LOBBY_SIZE,reason="SEOR: синхронизация LOBBY_SIZE")
            league_role=staff_roles[f"league_{name.lower()}"]
            for managed_channel in (ranked,lobby):
                await managed_channel.set_permissions(g.default_role,view_channel=False,connect=False,send_messages=False,use_application_commands=False)
                await managed_channel.set_permissions(registered_role,view_channel=False,connect=False,send_messages=False,use_application_commands=False)
                await managed_channel.set_permissions(league_role,view_channel=True,connect=True,speak=True,send_messages=True,read_message_history=True,use_application_commands=True)
            for stale_room in [v for v in cat.voice_channels if v.name.startswith(("🛡 CT · #","💣 T · #")) and not v.members]:
                try: await stale_room.delete(reason="SEOR /setup: удаление пустой комнаты матча")
                except discord.HTTPException: pass
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

    await gate_registered(info,touch_existing_channels=False)
    for public_category in (start,community,support,private,results):
        await gate_registered(public_category)
    for protected_name in tuple(protected_chats)+("🛠️・чат-кураторов",):
        await community_channels[protected_name].set_permissions(registered_role,view_channel=False,send_messages=False,read_message_history=False)
    for league_name,(league_emoji,_) in LEAGUES.items():
        for league_category in [c for c in g.categories if c.name==f"{league_emoji} SEOR {league_name.upper()}"]:
            await league_category.set_permissions(registered_role,view_channel=False,connect=False,send_messages=False,use_application_commands=False)
            for league_channel in league_category.channels:
                await league_channel.set_permissions(registered_role,view_channel=False,connect=False,send_messages=False,use_application_commands=False)

    admin_overwrites={g.default_role:discord.PermissionOverwrite(view_channel=False),g.me:discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_channels=True),staff_roles["owner"]:discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_messages=True),staff_roles["admin"]:discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_messages=True)}
    for staff_key in (
        "developer", "director", "head_admin", "ticket_admin", "head_ac",
        "games_admin", "anticheat", "moderator", "pro_lead",
        "curator_qualifications", "curator_division", "curator_pro",
    ):
        admin_overwrites[staff_roles[staff_key]]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True)
    admin = discord.utils.get(g.categories,name="🛡️ SEOR STAFF") or await g.create_category("🛡️ SEOR STAFF",overwrites=admin_overwrites)
    for target,overwrite in admin_overwrites.items(): await admin.set_permissions(target,overwrite=overwrite)
    staff_text_names=("💬・штаб-команды","⌨️・команды-штаба","⚠️・центр-санкций","🧾・архив-доказательств","✅・проверка-результатов", "📝・регистрация-игр", "🎛️・управление-матчами", "📋・логи-бота")
    await sync_channels(admin,text_names=staff_text_names,voice_names=("🔊 Штабной голос",))
    staff_channels={name:await text(admin,name,overwrites=admin_overwrites) for name in staff_text_names}
    if not discord.utils.get(admin.voice_channels,name="🔊 Штабной голос"):
        await g.create_voice_channel("🔊 Штабной голос",category=admin,overwrites=admin_overwrites,user_limit=20)
    review = await text(admin,"✅・проверка-результатов",overwrites=admin_overwrites)
    registration = await text(admin,"📝・регистрация-игр",overwrites=admin_overwrites)
    await registration.set_permissions(g.default_role,view_channel=False,send_messages=False)
    await registration.set_permissions(g.me,view_channel=True,send_messages=True,manage_messages=True)
    await registration.set_permissions(staff_roles["owner"],view_channel=True,send_messages=True,manage_messages=True)
    await registration.set_permissions(staff_roles["admin"],view_channel=True,send_messages=True,manage_messages=True)
    for curator_key in ("curator_qualifications","curator_division","curator_pro"):
        await registration.set_permissions(staff_roles[curator_key],view_channel=True,send_messages=True,read_message_history=True)
    staff_commands=staff_channels["⌨️・команды-штаба"]
    async for old_message in staff_commands.history(limit=20):
        if old_message.author==g.me:
            try: await old_message.delete()
            except discord.HTTPException: pass
    panel=discord.Embed(title="🛡️ SEOR CONTROL DESK",description="Рабочая панель администрации. Все действия выполняются кнопками ниже и записываются в журналы.",color=color())
    panel.add_field(name="⚖️ Модерация",value="`Санкции` — warn, timeout, kick, ban\n`Роли` — выдача и снятие ролей",inline=True)
    panel.add_field(name="🎮 Матчи",value="`Матчи` — информация и завершение\n`Результаты` — каналы проверки",inline=True)
    panel.add_field(name="📡 Аудит и поддержка",value="`Тикеты` — список открытых\n`Закрыть тикет` • `Аудит`",inline=True)
    panel.set_footer(text="SEOR CYBER • каждое действие проверяет права")
    await staff_commands.send(embed=panel,view=StaffControlView())
    if not review.last_message_id:
        await review.send(embed=discord.Embed(title="🧾 Проверка результатов",description="Сюда поступают скриншоты игроков. Администратор проверяет данные и нажимает **Принять** или **Отклонить**.",color=color()))
    if not registration.last_message_id:
        await registration.send(embed=discord.Embed(title="🤖 АВТО-РЕГИСТРАЦИЯ ИГР",description="Бот автоматически считывает со скриншота счёт, карту и K/D/A/MVP. Модератор сверяет распознанные данные с изображением и нажимает **Принять** или **Отклонить**. Куратор может подтверждать только матчи своей лиги.",color=discord.Color.orange()))

    audit=await category("📡 SEOR AUDIT")
    for target,overwrite in admin_overwrites.items(): await audit.set_permissions(target,overwrite=overwrite)
    audit_names=("🎫・журнал-тикетов","🆘・журнал-поддержки","🎮・журнал-матчей","📡・общий-журнал")
    await sync_channels(audit,text_names=audit_names)
    audit_channels={name:await text(audit,name,overwrites=admin_overwrites) for name in audit_names}
    if not audit_channels["📡・общий-журнал"].last_message_id:
        await audit_channels["📡・общий-журнал"].send(embed=discord.Embed(title="📡 SEOR AUDIT STREAM",description="Системные события, действия бота и служебные записи проекта.",color=discord.Color.dark_purple()))

    await send_staff_log(g,"общий-журнал","✅ Структура SEOR синхронизирована",f"Запустил: {interaction.user.mention}\nРоли и закрытые разделы обновлены.",discord.Color.green())
    await interaction.followup.send("Готово: обновлены только нужные элементы структуры. Существующие категории и каналы не удалялись и не пересоздавались.",ephemeral=True)


@bot.tree.command(name="league_role",description="Выдать или снять роль лиги по иерархии SEOR")
@app_commands.check(command_channel_access)
@app_commands.describe(member="Участник",league="Роль лиги",action="Выдать или снять")
@app_commands.choices(
    league=[
        app_commands.Choice(name="Default",value="default"),
        app_commands.Choice(name="Qualifications",value="qualifications"),
        app_commands.Choice(name="Division",value="division"),
        app_commands.Choice(name="Pro",value="pro"),
    ],
    action=[
        app_commands.Choice(name="Выдать",value="give"),
        app_commands.Choice(name="Снять",value="remove"),
    ],
)
async def league_role_command(interaction:discord.Interaction,member:discord.Member,league:app_commands.Choice[str],action:app_commands.Choice[str]):
    role_key=f"league_{league.value}"
    if role_key not in allowed_role_keys(interaction.user):
        return await interaction.response.send_message("По иерархии персонала ты не можешь управлять этой ролью лиги.",ephemeral=True)
    roles=await ensure_staff_roles(interaction.guild)
    role=roles.get(role_key)
    if not role:
        return await interaction.response.send_message("Роль лиги не найдена. Владелец должен один раз выполнить `/setup`.",ephemeral=True)
    if role >= interaction.guild.me.top_role:
        return await interaction.response.send_message("Discord блокирует выдачу: владелец сервера должен поднять роль бота выше ролей лиг в настройках ролей.",ephemeral=True)
    try:
        if action.value=="give":
            await member.add_roles(role,reason=f"SEOR FACEIT /league_role by {interaction.user}")
            text=f"{role.mention} выдана участнику {member.mention}."
        else:
            await member.remove_roles(role,reason=f"SEOR FACEIT /league_role by {interaction.user}")
            text=f"{role.mention} снята с участника {member.mention}."
    except discord.Forbidden:
        return await interaction.response.send_message("Discord не разрешил изменить роль. Проверь право бота `Управлять ролями` и поставь роль бота выше ролей лиг.",ephemeral=True)
    await interaction.response.send_message(text,ephemeral=True)


@bot.tree.command(name="roles_setup",description="Создать или восстановить служебные роли")
@app_commands.default_permissions(administrator=True)
@app_commands.check(command_channel_access)
async def roles_setup(interaction:discord.Interaction):
    if not can_manage_staff(interaction.user):
        return await interaction.response.send_message("Команда доступна только владельцу сервера или Owner.",ephemeral=True)
    await interaction.response.defer(ephemeral=True,thinking=True)
    roles=await ensure_staff_roles(interaction.guild)
    await interaction.followup.send("Роли готовы: "+", ".join(role.mention for role in roles.values()),ephemeral=True)


@bot.tree.command(name="strip_all_roles",description="Снять роли со всех участников, кроме Owner и Developer")
@app_commands.default_permissions(administrator=True)
@app_commands.check(command_channel_access)
@app_commands.describe(confirm="Для подтверждения введи CONFIRM")
async def strip_all_roles(interaction:discord.Interaction,confirm:str):
    if not is_developer(interaction.user):
        return await interaction.response.send_message("Команда доступна только участникам с ролью Developer.",ephemeral=True)
    if confirm.strip().upper() != "CONFIRM":
        return await interaction.response.send_message("Операция отменена. Для запуска команды введи `CONFIRM`.",ephemeral=True)

    await interaction.response.defer(ephemeral=True,thinking=True)
    owner_role_name=STAFF_ROLES["owner"]
    developer_role_name=EXTRA_ROLE_SPECS["developer"][0]
    changed=0; skipped=0; failed=0; removed_count=0

    for member in interaction.guild.members:
        if member.bot or member.id == interaction.guild.owner_id or has_role(member,owner_role_name) or has_role(member,developer_role_name):
            skipped += 1
            continue
        removable=[role for role in member.roles if not role.is_default() and not role.managed and role < interaction.guild.me.top_role]
        if not removable:
            continue
        try:
            await member.remove_roles(*removable,reason=f"SEOR mass role reset by {interaction.user}")
            changed += 1; removed_count += len(removable)
        except (discord.Forbidden,discord.HTTPException):
            failed += 1

    await send_staff_log(
        interaction.guild,"общий-журнал","🧹 Массовое снятие ролей",
        f"Запустил: {interaction.user.mention}\nОбработано участников: **{changed}**\nСнято ролей: **{removed_count}**\nПропущено защищённых/ботов: **{skipped}**\nОшибок: **{failed}**",
        discord.Color.red(),
    )
    await interaction.followup.send(
        f"Готово. Роли сняты у **{changed}** участников (всего ролей: **{removed_count}**). "
        f"Owner, Developer, владелец сервера и боты пропущены. Ошибок: **{failed}**.",ephemeral=True,
    )


@bot.tree.command(name="restore_launch_roles",description="Разово восстановить роли участников со скриншотов")
@app_commands.default_permissions(administrator=True)
@app_commands.check(command_channel_access)
@app_commands.describe(confirm="Для подтверждения введи CONFIRM")
async def restore_launch_roles(interaction:discord.Interaction,confirm:str):
    if not is_developer(interaction.user):
        return await interaction.response.send_message("Команда доступна только участникам с ролью Developer.",ephemeral=True)
    if confirm.strip().upper() != "CONFIRM":
        return await interaction.response.send_message("Операция отменена. Для запуска команды введи `CONFIRM`.",ephemeral=True)

    await interaction.response.defer(ephemeral=True,thinking=True)
    try:
        await interaction.guild.chunk(cache=True)
    except discord.HTTPException:
        pass

    roles=await ensure_staff_roles(interaction.guild)
    members_by_name={member.name.casefold():member for member in interaction.guild.members if not member.bot}
    expected=set().union(*LAUNCH_ROLE_MEMBERS.values())
    found=set(); changed_members=0; added_roles=0; failed=[]

    for username in sorted(expected):
        member=members_by_name.get(username.casefold())
        if not member:
            continue
        found.add(username)
        desired=[]
        for role_key,usernames in LAUNCH_ROLE_MEMBERS.items():
            if username in usernames:
                role=roles.get(role_key)
                if role and role not in member.roles:
                    desired.append(role)
        if not desired:
            continue
        try:
            await member.add_roles(*desired,reason=f"SEOR launch role restore by {interaction.user}")
            changed_members += 1; added_roles += len(desired)
        except (discord.Forbidden,discord.HTTPException):
            failed.append(username)

    missing=sorted(expected-found)
    details=""
    if missing:
        details="\n\nНе найдены на сервере:\n`"+"`, `".join(missing)+"`"
    if failed:
        details+="\n\nНе удалось выдать роли:\n`"+"`, `".join(failed)+"`"
    if len(details)>1300:
        details=details[:1300]+"…"

    await send_staff_log(
        interaction.guild,"общий-журнал","📥 Восстановлены стартовые роли",
        f"Запустил: {interaction.user.mention}\nНайдено участников: **{len(found)}/{len(expected)}**\nИзменено участников: **{changed_members}**\nВыдано ролей: **{added_roles}**\nОшибок: **{len(failed)}**",
        discord.Color.green(),
    )
    await interaction.followup.send(
        f"Готово. Найдено **{len(found)}/{len(expected)}** участников, изменено **{changed_members}**, выдано ролей **{added_roles}**.{details}",
        ephemeral=True,
    )


@bot.tree.command(name="profile",description="Показать игровой профиль")
@app_commands.check(command_channel_access)
@app_commands.describe(member="Игрок, профиль которого нужно открыть")
async def profile(interaction:discord.Interaction,member:discord.Member=None): await send_profile(interaction,member)


@bot.tree.command(name="set_game_id",description="Сохранить игровой ID")
@app_commands.check(command_channel_access)
async def set_game_id(interaction:discord.Interaction): await interaction.response.send_modal(GameIdModal())


@bot.tree.command(name="set_nickname",description="Изменить ник участника на сервере")
@app_commands.default_permissions(manage_nicknames=True)
@app_commands.check(command_channel_access)
@app_commands.describe(member="Участник",nickname="Новый ник на сервере")
async def set_nickname(interaction:discord.Interaction,member:discord.Member,nickname:str):
    if not can_administer(interaction.user):
        return await interaction.response.send_message("Команда доступна только владельцу и администрации SEOR.",ephemeral=True)
    nickname=nickname.strip()
    if not 2 <= len(nickname) <= 32:
        return await interaction.response.send_message("Ник должен содержать от 2 до 32 символов.",ephemeral=True)
    if member.id==interaction.guild.owner_id:
        return await interaction.response.send_message("Discord не разрешает боту менять ник владельца сервера.",ephemeral=True)
    try:
        await member.edit(nick=nickname,reason=f"SEOR /set_nickname by {interaction.user}")
    except discord.Forbidden:
        return await interaction.response.send_message("Не удалось изменить ник. Подними роль бота выше роли этого участника и выдай право **Manage Nicknames**.",ephemeral=True)
    except discord.HTTPException:
        return await interaction.response.send_message("Discord не принял новый ник. Проверь символы и попробуй ещё раз.",ephemeral=True)
    db.set_nickname(interaction.guild_id,member.id,nickname)
    await send_staff_log(interaction.guild,"общий-журнал","✏️ Изменён ник участника",f"Участник: {member.mention}\nНовый ник: **{nickname}**\nИзменил: {interaction.user.mention}",discord.Color.blue())
    await interaction.response.send_message(f"✅ Ник участника {member.mention} изменён на **{nickname}**.",ephemeral=True)


@bot.tree.command(name="admin_result",description="Вручную зарегистрировать результат")
@app_commands.default_permissions(manage_messages=True)
@app_commands.check(command_channel_access)
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


@bot.tree.command(name="matches",description="Показать последние матчи карточкой")
@app_commands.check(command_channel_access)
async def matches_command(interaction:discord.Interaction): await send_recent_matches(interaction)


@bot.tree.command(name="match_info",description="Показать информацию о матче")
@app_commands.check(command_channel_access)
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
@app_commands.check(command_channel_access)
async def standard(interaction:discord.Interaction):
    await interaction.response.send_message(embed=standard_embed(interaction.guild_id,interaction.user),ephemeral=True)


@bot.tree.command(name="qualification",description="Проверить норматив K/D")
@app_commands.check(command_channel_access)
async def qualification(interaction:discord.Interaction):
    await interaction.response.send_message(embed=standard_embed(interaction.guild_id,interaction.user),ephemeral=True)


@bot.tree.command(name="top",description="Показать топ игроков выбранной лиги")
@app_commands.check(command_channel_access)
@app_commands.choices(league=[
    app_commands.Choice(name="Default",value="Default"),
    app_commands.Choice(name="Qualifications",value="Qualifications"),
    app_commands.Choice(name="Division",value="Division"),
    app_commands.Choice(name="Pro",value="Pro"),
])
async def top(interaction:discord.Interaction,league:app_commands.Choice[str]):
    await send_league_top(interaction,league.value,ephemeral=False)


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
