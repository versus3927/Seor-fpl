import asyncio
from datetime import datetime, timedelta, timezone
import io
import json
import os
import random
import re
from pathlib import Path
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
from match_card import build_match_card
from screenshot_reader import analyze_screenshot
from elo_levels import elo_level, elo_table_text
from ticket_transcript import build_ticket_transcript

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent
TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0") or 0)
BOT_NAME = os.getenv("BOT_NAME", "Dominion FACEIT")
ACCENT = int(os.getenv("ACCENT_COLOR", "7C3AED"), 16)
LOBBY_SIZE = max(1, min(10, int(os.getenv("LOBBY_SIZE", "10"))))
QUALIFICATION_KD = max(0.0, float(os.getenv("QUALIFICATION_KD", "1.00")))
LEAGUES = {
    "Default": ("⚪", 1000),
    "Qualifications": ("🟢", 1150),
    "Division": ("🟣", 1350),
    "Pro": ("🔴", 1600),
}
LEAGUE_CATEGORY_NAMES={
    "Default":"⚪・DEFAULT LEAGUE",
    "Qualifications":"🟢・DOMINION RISE",
    "Division":"🟣・DOMINION ASCEND",
    "Pro":"🔴・PRO LEAGUE",
}
LEAGUE_LOBBY_COUNTS={"Default":3,"Qualifications":3,"Division":3,"Pro":3}
LEAGUE_DISPLAY_NAMES={
    "Default":"Default League",
    "Qualifications":"Dominion Rise",
    "Division":"Dominion Ascend",
    "Pro":"Pro League",
}


def league_display_name(league):
    return LEAGUE_DISPLAY_NAMES.get(str(league),str(league))


def league_category_name(league_name):
    return LEAGUE_CATEGORY_NAMES[league_name]
def lobby_number(channel_or_name):
    name=channel_or_name.name if hasattr(channel_or_name,"name") else str(channel_or_name)
    try: return int(name.rsplit(" ",1)[1])
    except (ValueError,IndexError): return None


def ranked_channel_name(lobby_or_number):
    number=lobby_or_number if isinstance(lobby_or_number,int) else lobby_number(lobby_or_number)
    return f"ranked-{number}" if number else "ranked"


def ranked_channel_for_lobby(lobby):
    target=ranked_channel_name(lobby)
    return (discord.utils.get(lobby.category.text_channels,name=target)
            or discord.utils.get(lobby.category.text_channels,name="ranked"))


MAPS = ["Sandstone", "Province", "Rust", "Dune", "Hanami", "Breeze", "Prison"]
MAP_ICONS = {"Sandstone":"🏜️","Province":"🏘️","Rust":"🏭","Dune":"🌵","Hanami":"🌸","Breeze":"🌊","Prison":"⛓️"}
MAP_VETO_TIMEOUT = 15
REGISTERED_ROLE_NAME = "зарегистрирован"
STARTING_ELO = 1000
STAFF_ROLES = {
    "owner": "Owner",
    "admin": "admin",
    "curator_qualifications": "Dm Rise curator",
    "curator_division": "Dm Ascend curator",
    "curator_pro": "Pro curator",
}
LEAGUE_ROLES = {
    "default": "Default League",
    "qualifications": "Dominion Rise",
    "division": "Dominion Ascend",
    "pro": "Pro league",
}
DEFAULT_LEAGUE_ALIASES=("default League","Default League","default league","Default","деф лига","дефолт лига")
EXTRA_ROLE_SPECS = {
    "developer": ("Developer", 0x9CCBFF, {"administrator": True}),
    "bot_role": ("Dominion Faceit", 0x99AAB5, {}),
    "director": ("general manager", 0x111111, {"manage_guild": True, "manage_channels": True, "manage_roles": True}),
    "head_admin": ("Owner", 0x111111, {"manage_guild": True, "manage_channels": True, "manage_roles": True, "moderate_members": True}),
    "ticket_admin": ("games Support", 0xA855F7, {"manage_messages": True, "moderate_members": True}),
    "ticket_support": ("games Support", 0x8B5CF6, {"manage_messages": True}),
    "head_ac": ("head ac", 0x1D4ED8, {"manage_messages": True, "moderate_members": True}),
    "games_admin": ("games admin", 0xEC4899, {"manage_messages": True, "move_members": True}),
    "anticheat": ("anticheat", 0x22C55E, {"manage_messages": True}),
    "moderator": ("moderator", 0xF97316, {"manage_messages": True, "moderate_members": True}),
    "content_creator": ("Partner DPL", 0x14D8CC, {}),
    "streamer": ("Partner DPL", 0xFDE68A, {}),
    "sponsor": ("Server Booster", 0x00FF55, {}),
    "pro_lead": ("Pro curator", 0xC026D3, {"manage_messages": True, "move_members": True}),
    "premium": ("Premium", 0x0EA5E9, {}),
    "all_warn_1": ("ALL warn 1/3", 0xF87171, {}),
    "all_warn_2": ("ALL warn 2/3", 0xEF4444, {}),
    "all_warn_3": ("ALL warn 3/3", 0xB91C1C, {}),
    "anticheat_warn_1": ("anticheat warn 1/3", 0x60A5FA, {}),
    "anticheat_warn_2": ("anticheat warn 2/3", 0x2563EB, {}),
    "anticheat_warn_3": ("anticheat warn 3/3", 0x1D4ED8, {}),
    "admin_warn_1": ("admin warn 1/3", 0xFDBA74, {}),
    "admin_warn_2": ("admin warn 2/3", 0xF97316, {}),
    "admin_warn_3": ("admin warn 3/3", 0xC2410C, {}),
    "warn_pro_1": ("1/3 pro warn", 0xFB7185, {}),
    "warn_pro_2": ("2/3 pro warn", 0xFB7185, {}),
    "warn_pro_3": ("3/3 pro warn", 0xEF4444, {}),
}
LEGACY_UNUSED_ROLE_NAMES=(
    "1/3 division warn","2/3 division warn","3/3 division warn","test division",
    "1/3 Qual warn","2/3 Qual warn","3/3 Qual warn","test fpl qualifications",".",
)
ROLE_PANEL_EXTRAS=("developer","director","head_admin","ticket_admin","head_ac","games_admin","anticheat","moderator","content_creator","streamer","sponsor","pro_lead","premium")

# Перенос ролей со старого сервера отключён: этот сервер использует только свою структуру.
LAUNCH_ROLE_MEMBERS = {}


intents = discord.Intents.default()
intents.members = True
intents.voice_states = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
queue_messages = {}
starting = set()
active_veto = set()
active_veto_players = {}
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


def can_use_sanctions(member):
    """Санкции доступны только администрации и профильным ролям поддержки."""
    sanction_roles=(
        STAFF_ROLES["owner"],STAFF_ROLES["admin"],
        EXTRA_ROLE_SPECS["developer"][0],EXTRA_ROLE_SPECS["director"][0],
        EXTRA_ROLE_SPECS["head_admin"][0],EXTRA_ROLE_SPECS["ticket_admin"][0],
        EXTRA_ROLE_SPECS["head_ac"][0],EXTRA_ROLE_SPECS["games_admin"][0],
        EXTRA_ROLE_SPECS["anticheat"][0],EXTRA_ROLE_SPECS["moderator"][0],
    )
    return member.id==member.guild.owner_id or any(has_role(member,name) for name in sanction_roles)




def curator_league(member):
    for league in ("qualifications","division","pro"):
        if has_role(member,STAFF_ROLES[f"curator_{league}"]): return league
    return None


def role_panel_keys():
    """Все роли, которыми можно управлять через панель."""
    return set(STAFF_ROLES) | {f"league_{key}" for key in LEAGUE_ROLES} | set(ROLE_PANEL_EXTRAS)


def allowed_role_keys(member):
    """Роли, которые участник может выдавать и снимать по иерархии DOMINION."""
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


async def ensure_staff_roles(guild,create_missing=False):
    """Use existing configured roles and create only missing ones when /setup requests it."""
    result={}

    staff_create_specs={
        "owner":(0xED4245,{"administrator":True}),
        "admin":(0xE74C3C,{"manage_guild":True,"manage_channels":True,"manage_roles":True,"manage_messages":True,"kick_members":True,"ban_members":True,"moderate_members":True,"move_members":True}),
        "curator_qualifications":(0x22C55E,{"manage_messages":True,"move_members":True,"mute_members":True}),
        "curator_division":(0xA855F7,{"manage_messages":True,"move_members":True,"mute_members":True}),
        "curator_pro":(0xEF4444,{"manage_messages":True,"move_members":True,"mute_members":True}),
    }
    league_colors={"default":0xB8C0CC,"qualifications":0x22C55E,"division":0xA855F7,"pro":0xEF4444}

    async def resolve(name,color_value=0x99AAB5,permission_values=None,allow_create=True):
        role=find_role(guild,name)
        if role or not create_missing or not allow_create:
            return role
        permissions=discord.Permissions.none()
        for permission,value in (permission_values or {}).items():
            setattr(permissions,permission,bool(value))
        return await guild.create_role(
            name=name,
            colour=discord.Colour(color_value),
            permissions=permissions,
            hoist=False,
            mentionable=False,
            reason="DOMINION /setup: отсутствующая роль",
        )

    for key,name in STAFF_ROLES.items():
        color_value,permission_values=staff_create_specs[key]
        result[key]=await resolve(name,color_value,permission_values)

    for key,name in LEAGUE_ROLES.items():
        if key=="default":
            role=next((role for role in guild.roles if any(role_name_matches(role.name,alias) for alias in DEFAULT_LEAGUE_ALIASES)),None)
            if not role:
                role=await resolve(name,league_colors[key],{})
        else:
            role=await resolve(name,league_colors[key],{})
        result[f"league_{key}"]=role

    for key,(name,color_value,permission_values) in EXTRA_ROLE_SPECS.items():
        # The Discord-managed bot role already exists after inviting the bot.
        if key=="bot_role":
            role=find_role(guild,name) or (guild.me.top_role if guild.me else None)
        else:
            role=await resolve(name,color_value,permission_values)
        result[key]=role
    return result


def league_of(channel: discord.abc.GuildChannel):
    if not channel.category:
        return None
    for name in LEAGUES:
        if channel.category.name==league_category_name(name):
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
        title=f"⚔️ {league_display_name(league).upper()} · {channel.name}",
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
            await interaction.response.defer(ephemeral=True,thinking=True)
            await interaction.user.move_to(None)
            await interaction.followup.send("Ты вышел из очереди.", ephemeral=True)
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
        await interaction.response.defer(ephemeral=True,thinking=True)
        await ch.set_permissions(interaction.guild.default_role, overwrite=current)
        await interaction.followup.send("Доступ комнаты переключён.", ephemeral=True)

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
        await interaction.response.defer(ephemeral=True,thinking=True)
        await ch.set_permissions(interaction.guild.default_role, overwrite=ow)
        await interaction.followup.send("Видимость комнаты переключена.", ephemeral=True)


class RenameRoom(discord.ui.Modal, title="Название комнаты"):
    name = discord.ui.TextInput(label="Новое название", max_length=80)
    def __init__(self, channel):
        super().__init__(); self.channel = channel
    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True,thinking=True)
        await self.channel.edit(name=str(self.name))
        await interaction.followup.send("Название изменено.", ephemeral=True)


class RoomLimit(discord.ui.Modal, title="Лимит комнаты"):
    limit = discord.ui.TextInput(label="Число участников (0–99)", max_length=2)
    def __init__(self, channel):
        super().__init__(); self.channel = channel
    async def on_submit(self, interaction):
        try: value = max(0, min(99, int(str(self.limit))))
        except ValueError:
            return await interaction.response.send_message("Нужно указать число.", ephemeral=True)
        await interaction.response.defer(ephemeral=True,thinking=True)
        await self.channel.edit(user_limit=value)
        await interaction.followup.send(f"Лимит: {value or 'без ограничений'}.", ephemeral=True)


def registration_embed(member=None):
    greeting=f"{member.mention}, добро пожаловать!" if member else "Добро пожаловать в соревновательное сообщество DOMINION."
    e=discord.Embed(title="⚡ ДОБРО ПОЖАЛОВАТЬ В DOMINION",description=f"{greeting}\n\nДо регистрации тебе доступен только этот раздел. Подтверди игровой профиль — после этого откроются основные каналы сервера.",color=color())
    first_step="Открой канал **📋・регистрация** и выбери нужную кнопку." if member else "Выбери **Регистрация** для нового профиля или **Войти по данным** для восстановления старого."
    e.add_field(name="01  НАЖМИ КНОПКУ",value=first_step,inline=False)
    e.add_field(name="02  УКАЖИ ДАННЫЕ",value="В одной форме укажи игровой ник и числовой Standoff 2 ID.",inline=False)
    e.add_field(name="03  ПОЛУЧИ ДОСТУП",value=f"Бот выдаст роли **зарегистрирован** и **Default League**, установит **{STARTING_ELO} ELO** и откроет сервер.",inline=False)
    e.set_footer(text="DOMINION CYBER • competitive platform")
    return e


class GameIdModal(discord.ui.Modal, title="Регистрация DOMINION"):
    nickname = discord.ui.TextInput(label="Игровой ник", placeholder="Например: Versus", min_length=2, max_length=24)
    game_id = discord.ui.TextInput(label="Standoff 2 ID", placeholder="Например: 245507174", max_length=30)
    async def on_submit(self, interaction):
        value=str(self.game_id).strip()
        nickname=str(self.nickname).strip()
        if not value.isdigit() or len(value) < 5:
            return await interaction.response.send_message("Укажи корректный числовой Standoff 2 ID.",ephemeral=True)
        if len(nickname)<2:
            return await interaction.response.send_message("Игровой ник должен содержать минимум 2 символа.",ephemeral=True)
        owner=db.game_id_owner(interaction.guild_id,value)
        if owner and owner["user_id"]!=interaction.user.id:
            return await interaction.response.send_message("❌ Этот Standoff 2 ID уже занят участником этого сервера.",ephemeral=True)
        await interaction.response.defer(ephemeral=True,thinking=True)
        db.set_registration(interaction.guild_id,interaction.user.id,nickname,value)
        try: await interaction.user.edit(nick=nickname,reason="DOMINION: игровой ник при регистрации")
        except discord.Forbidden: pass
        roles=await ensure_staff_roles(interaction.guild)
        registered_role=find_role(interaction.guild,REGISTERED_ROLE_NAME)
        default_role=roles.get("league_default")
        if not registered_role:
            return await interaction.followup.send("Профиль сохранён, но роль `зарегистрирован` не найдена. Администратору нужно выполнить `/setup`.",ephemeral=True)
        if not default_role:
            return await interaction.followup.send("Профиль сохранён, но существующая роль `Default League` не найдена на сервере.",ephemeral=True)
        try:
            await interaction.user.add_roles(registered_role,reason="DOMINION: регистрация игрового профиля")
        except discord.Forbidden:
            return await interaction.followup.send("Регистрация сохранена, но Discord не дал выдать роль `зарегистрирован`. Подними роль бота выше неё.",ephemeral=True)
        try:
            await interaction.user.add_roles(default_role,reason="DOMINION: автоматическая Default League после регистрации")
        except discord.Forbidden:
            return await interaction.followup.send("Регистрация завершена, но Discord не дал выдать Default League. Подними роль бота выше роли Default League.",ephemeral=True)
        db.set_points(interaction.guild_id,interaction.user.id,STARTING_ELO)
        await interaction.followup.send(f"✅ Регистрация завершена. Ник: **{nickname}** · Game ID: **{value}** · роль **default League** · **{STARTING_ELO} ELO**.",ephemeral=True)


class LoginByDataModal(discord.ui.Modal, title="Вход в DOMINION FACEIT"):
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
        await interaction.response.defer(ephemeral=True,thinking=True)
        try: await interaction.user.edit(nick=profile["nickname"],reason="DOMINION: восстановление игрового профиля")
        except discord.Forbidden: pass
        roles=await ensure_staff_roles(interaction.guild)
        registered_role=find_role(interaction.guild,REGISTERED_ROLE_NAME)
        default_role=roles.get("league_default")
        if not registered_role:
            return await interaction.followup.send("Профиль восстановлен, но роль `зарегистрирован` не найдена. Администратору нужно выполнить `/setup`.",ephemeral=True)
        if not default_role:
            return await interaction.followup.send("Профиль восстановлен, но существующая роль `Default League` не найдена на сервере.",ephemeral=True)
        try:
            await interaction.user.add_roles(registered_role,reason="DOMINION: восстановление регистрации")
        except discord.Forbidden:
            return await interaction.followup.send("Профиль восстановлен, но Discord не дал выдать роль `зарегистрирован`. Подними роль бота выше неё.",ephemeral=True)
        try:
            await interaction.user.add_roles(default_role,reason="DOMINION: автоматическая Default League после входа")
        except discord.Forbidden:
            return await interaction.followup.send("Профиль восстановлен, но Discord не дал выдать Default League. Подними роль бота выше роли Default League.",ephemeral=True)
        db.set_points(interaction.guild_id,interaction.user.id,STARTING_ELO)
        await interaction.followup.send(f"✅ Вход выполнен. Профиль **{profile['nickname']}** восстановлен · роль **default League** · **{STARTING_ELO} ELO**.",ephemeral=True)


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
    recognized_count=len(used)
    team_a_ids={int(x) for x in match["team_a"].split(",") if x}
    team_b_ids={int(x) for x in match["team_b"].split(",") if x}

    # OCR обозначает верхнюю/левую сторону как A, но она не всегда совпадает
    # с командой A, сохранённой в матче. Определяем ориентацию по распознанным игрокам.
    direct_matches=0
    swapped_matches=0
    for item in matched:
        user_id=item.get("user_id")
        screenshot_team=str(item.get("team") or "").upper()
        if not user_id or screenshot_team not in {"A","B"}:
            continue
        if (screenshot_team=="A" and user_id in team_a_ids) or (screenshot_team=="B" and user_id in team_b_ids):
            direct_matches+=1
        if (screenshot_team=="A" and user_id in team_b_ids) or (screenshot_team=="B" and user_id in team_a_ids):
            swapped_matches+=1
    if swapped_matches>direct_matches:
        analysis["score_a"],analysis["score_b"]=analysis.get("score_b"),analysis.get("score_a")
        for item in matched:
            screenshot_team=str(item.get("team") or "").upper()
            if screenshot_team=="A": item["team"]="B"
            elif screenshot_team=="B": item["team"]="A"
        orientation_note="Стороны скриншота автоматически сопоставлены с командами матча."
        analysis["notes"]=(str(analysis.get("notes") or "")+" "+orientation_note).strip()

    absent=[]
    for candidate in candidates:
        if candidate["user_id"] in used:
            continue
        fallback={
            "user_id":candidate["user_id"],
            "name":candidate["names"][0] if candidate["names"] else f"Player {candidate['user_id']}",
            "game_id":candidate["game_id"],
            "team":"A" if candidate["user_id"] in team_a_ids else "B",
            "kills":0,
            "assists":0,
            "deaths":13,
            "mvp":0,
            "absent_from_screenshot":True,
        }
        matched.append(fallback)
        absent.append(candidate["user_id"])
    analysis["recognized_players"]=recognized_count
    analysis["absent_players"]=absent
    analysis["matched_stats"]=matched
    return analysis


def result_review_embed(submission_id,match,analysis,final_score,submitter):
    detected_a=analysis.get("score_a"); detected_b=analysis.get("score_b")
    detected=f"{detected_a}:{detected_b}" if detected_a is not None and detected_b is not None else "н�������� распознан"
    lines_a=[]; lines_b=[]; unmatched=[]
    for item in analysis.get("matched_stats",[])[:10]:
        player=f"<@{item['user_id']}>" if item.get("user_id") else f"`{item.get('name','?')}`"
        game_id=f" · ID `{item['game_id']}`" if item.get("game_id") else ""
        line=f"{player}{game_id}\n`{item.get('kills',0):02}/{item.get('assists',0):02}/{item.get('deaths',0):02}` · MVP **{item.get('mvp',0)}**"
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
    e.add_field(name="Матч",value=f"Лига: **{league_display_name(match['league'])}**\nКарта: **{analysis.get('map') or match.get('map') or 'не определена'}**\nХост: <@{match['host_id']}>",inline=True)
    e.add_field(name="Распознавание",value=f"Точность: **{confidence:.0f}%**\nМодель: `{analysis.get('model') or 'ручной режим'}`\nРаспознано: **{analysis.get('recognized_players',len(analysis.get('matched_stats',[])))}/10**",inline=True)
    e.add_field(name="CT · K / A / D",value="\n".join(lines_a)[:1024] or "Нет распознанных данных",inline=True)
    e.add_field(name="T · K / A / D",value="\n".join(lines_b)[:1024] or "Нет распознанных данных",inline=True)
    notes=[]
    if analysis.get("notes"): notes.append(str(analysis["notes"]))
    absent_ids=analysis.get("absent_players",[])
    if absent_ids: notes.append("Нет на финальном скрине — записано K/A/D 0/0/13: "+", ".join(f"<@{uid}>" for uid in absent_ids))
    if unmatched: notes.append("Не привязаны: "+", ".join(unmatched))
    if has_error:
        raw=str(analysis["error"])
        if "404" in raw or "NOT_FOUND" in raw or "no longer available" in raw:
            raw="Модель Gemini из настроек больше недоступна. Бот попробовал актуальную модель; если ошибка осталась, проверь GEMINI_VISION_MODEL и доступ API."
        notes.append("⚠️ "+raw[:700])
    e.add_field(name="Проверка модератором",value=("\n".join(notes)[:1024] if notes else "Сверь счёт, команды и статистику со скриншотом."),inline=False)
    e.set_footer(text="DOMINION FACEIT · принять только после сверки скриншота")
    return e


def guild_match(guild_id,match_id):
    match=db.match(match_id)
    if not match or int(match.get("guild_id",0))!=int(guild_id):
        return None
    return match


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
    match=guild_match(interaction.guild_id,match_id)
    if not match:
        return await interaction.followup.send("Игры с таким номером нет.",ephemeral=True)
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
            error=" Модель распознавания ��едоступна — проверь `GEMINI_VISION_MODEL=gemini-3.6-flash` и `GEMINI_API_KEY`." if ("404" in raw or "NOT_FOUND" in raw) else f" Ошибка AI: `{raw[:180]}`"
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


class GameLookupModal(discord.ui.Modal, title="Поиск профиля"):
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
        card=await build_profile_card(p,name,avatar_url,recent,build_profile_meta(interaction.guild,p,member))
        await interaction.followup.send(file=discord.File(card,"profile.png"),ephemeral=True)


class MatchLookupDashboardModal(discord.ui.Modal, title="Поиск матча"):
    match_id = discord.ui.TextInput(label="ID матча", placeholder="Например: 700", max_length=10)

    async def on_submit(self, interaction):
        try: m=guild_match(interaction.guild_id,int(str(self.match_id)))
        except ValueError: m=None
        if not m:
            return await interaction.response.send_message("Игры с таким номером нет.",ephemeral=True)
        a=" ".join(f"<@{x}>" for x in m["team_a"].split(",") if x)
        b=" ".join(f"<@{x}>" for x in m["team_b"].split(",") if x)
        score=f"{m['score_a'] if m['score_a'] is not None else '?'}:{m['score_b'] if m['score_b'] is not None else '?'}"
        e=discord.Embed(title=f"🎮 Матч #{m['id']}",description=f"Лига: **{league_display_name(m['league'])}**\nКарта: **{m['map']}**\nСтатус: **{m['status']}**\nСчёт: **{score}**\n\n🛡 CT: {a}\n💣 T: {b}",color=color())
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
    e.set_footer(text="DOMINION CYBER • игровая панель")
    return e


def dashboard_home_embed():
    e=discord.Embed(title="🎛️ ПАНЕЛЬ УПРАВЛЕНИЯ",description="Твой центр управления матчами и профилем. Нажми кнопку ниже — панель откроется лично для тебя.",color=discord.Color.from_rgb(124,58,237))
    e.add_field(name="👤 Игрок",value="Профиль • статистика • рейтинг",inline=True)
    e.add_field(name="🎮 Матчи",value="История и поиск • результаты",inline=True)
    e.add_field(name="👥 Команда",value="Пати • совместный подбор",inline=True)
    e.add_field(name="🛡️ Персонал",value="Создание и выдача служебных ролей",inline=False)
    e.set_footer(text="DOMINION CYBER · FACEIT STANDOFF 2")
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
            self._button("Покинуть","��",discord.ButtonStyle.danger,self.party_leave)
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
        await i.response.send_message("Используй `/top` и выбери лигу: Default League, Dominion Rise, Dominion Ascend или Pro League.",ephemeral=True)

    async def place(self,i):
        rows=db.leaders(i.guild_id,1000); pos=next((n for n,p in enumerate(rows,1) if p["user_id"]==i.user.id),None); p=db.player(i.guild_id,i.user.id)
        await i.response.send_message(f"📍 Твоё место: **#{pos or '—'}**, рейтинг: **{p['points']} ELO**, уровень: **LVL {elo_level(p['points'])}**.",ephemeral=True)

    async def norms(self,i):
        await i.response.send_message(f"📗 Квалификация: **K/D {QUALIFICATION_KD:.2f}**. Игроки лиг **Division** и **Pro** освобождены от норматива.\n\n**Уровни ELO:**\n{elo_table_text()}",ephemeral=True)

    async def matches(self,i): await send_recent_matches(i)

    async def party_create(self,i): await i.response.send_message("Используй `/party create` и выбери лигу: Default League, Dominion Rise, Pro League или PC.",ephemeral=True)
    async def party_show(self,i):
        party=db.party_for_user(i.guild_id,i.user.id)
        if not party: return await i.response.send_message("👥 Ты не состоишь в активном пати.",ephemeral=True)
        await i.response.send_message(embed=party_embed(party),ephemeral=True)
    async def party_leave(self,i):
        result=db.leave_party(i.guild_id,i.user.id)
        await i.response.send_message("🚪 Ты покинул пати." if result!="not_in_party" else "Ты не состоишь в пати.",ephemeral=True)
    async def account(self,i):
        p=db.player(i.guild_id,i.user.id)
        await i.response.send_message(f"⚙️ Discord: {i.user.mention}\nИгровой ID: `{p['game_id'] or 'не указан'}`\nELO: **{p['points']}** · **LVL {elo_level(p['points'])}**\nМатчей: **{p['games']}**",ephemeral=True)

    async def back(self,i):
        await i.response.edit_message(embed=dashboard_home_embed(),view=DashboardView())

    async def role_panel(self,i):
        if not can_use_role_panel(i.user):
            return await i.response.send_message("У тебя нет доступа к управлению ролями.",ephemeral=True)
        await i.response.send_message(embed=discord.Embed(title="🛡️ Управление ролями",description="Выбери участника и роль, затем нажми **Выдать** или **Снять**. Доступные действия ограничены иерархией персонала.",color=color()),view=RolePanelView(i.user),ephemeral=True)

    async def create_roles(self,i):
        if not can_manage_staff(i.user):
            return await i.response.send_message("Создавать роли может только владелец сервера или Owner.",ephemeral=True)
        await i.response.defer(ephemeral=True,thinking=True)
        await ensure_staff_roles(i.guild)
        await i.followup.send("Служебные роли созданы и синхронизированы.",ephemeral=True)


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
        options += [discord.SelectOption(label=EXTRA_ROLE_SPECS[key][0],value=key,description="Расширенная роль DOMINION") for key in ROLE_PANEL_EXTRAS if key in allowed_keys]
        super().__init__(placeholder="Выбери доступную роль",options=options,min_values=1,max_values=1,row=1)
    async def callback(self,interaction):
        self.view.role_key=self.values[0]
        selected=next((option.label for option in self.options if option.value==self.values[0]),self.values[0])
        self.placeholder=f"Роль: {selected}"[:150]
        member=interaction.guild.get_member(self.view.target_id) if self.view.target_id else None
        who=member.mention if member else "сначала выбери участника"
        embed=discord.Embed(title="🛡️ Управление ролями",description=f"Участник: {who}\n��оль: **{selected}**\nНажми **Выдать** или **Снять**.",color=color())
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
            await member.add_roles(role,reason=f"DOMINION dashboard: {interaction.user}")
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
            await member.remove_roles(role,reason=f"DOMINION dashboard: {interaction.user}")
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


async def send_ticket_close_log(channel,closed_by,reason):
    """Save the complete ticket conversation as an HTML attachment before deletion."""
    log_channel=next((c for c in channel.guild.text_channels if c.name.endswith("журнал-тикетов")),None)
    if not log_channel:
        return False
    try:
        transcript,message_count=await build_ticket_transcript(channel,closed_by,reason)
        embed=discord.Embed(
            title="🔒 Тикет закрыт",
            description=(f"Канал: **{channel.name}**\nПричина: {reason}\n"
                         f"Закрыл: {closed_by.mention}\nСообщений в HTML: **{message_count}**"),
            color=discord.Color.dark_purple(),
            timestamp=datetime.now(timezone.utc),
        )
        filename=f"ticket-{channel.id}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.html"
        await log_channel.send(embed=embed,file=discord.File(transcript,filename=filename))
        return True
    except (discord.Forbidden,discord.HTTPException) as exc:
        print(f"Ticket transcript error in {channel.name}: {exc!r}",flush=True)
        return False


async def delete_ticket_fully(channel,closed_by,reason):
    """Delete the closed ticket, its inbox card and the empty TICKETS category."""
    guild=channel.guild
    category=channel.category
    channel_id=channel.id
    channel_mention=channel.mention

    # Remove the stale "Open ticket" card from the staff inbox.
    inbox=next((c for c in guild.text_channels if "входящие-тикеты" in c.name),None)
    if inbox:
        try:
            async for message in inbox.history(limit=200):
                descriptions="\n".join((embed.description or "") for embed in message.embeds)
                if message.author==guild.me and channel_mention in descriptions:
                    try: await message.delete()
                    except discord.HTTPException: pass
        except discord.HTTPException:
            pass

    try:
        await channel.delete(reason=f"DOMINION ticket closed by {closed_by}: {reason}")
    except (discord.Forbidden,discord.HTTPException) as exc:
        print(f"Ticket delete error for {channel.name}: {exc!r}",flush=True)
        return False

    # Delete the shared category only when this was the final ticket in it.
    if category and category.name=="🎫 TICKETS":
        remaining=[item for item in guild.channels if item.id!=channel_id and getattr(item,"category_id",None)==category.id]
        if not remaining:
            try:
                await category.delete(reason="DOMINION: last ticket closed")
            except (discord.Forbidden,discord.HTTPException) as exc:
                print(f"Empty ticket category delete error: {exc!r}",flush=True)
    return True


def find_punishment_channel(guild):
    for channel in guild.text_channels:
        compact="".join(char for char in channel.name.casefold() if char.isalnum())
        if "наказан" in compact or "punishment" in compact or "sanction" in compact:
            return channel
    return None


async def send_punishment_log(guild,title,description,log_color=None):
    channel=find_punishment_channel(guild)
    if not channel:
        print(f"{guild.name}: punishment channel not found",flush=True)
        return False
    embed=discord.Embed(title=title,description=description,color=log_color or discord.Color.orange(),timestamp=datetime.now(timezone.utc))
    try:
        await channel.send(embed=embed)
        return True
    except (discord.Forbidden,discord.HTTPException) as exc:
        print(f"{guild.name}: punishment embed log failed in {channel.name}: {exc!r}",flush=True)
        try:
            await channel.send(f"**{title}**\n{description}")
            return True
        except (discord.Forbidden,discord.HTTPException) as fallback_exc:
            print(f"{guild.name}: punishment text log failed in {channel.name}: {fallback_exc!r}",flush=True)
            return False


class SanctionModal(discord.ui.Modal,title="Выдать санкцию"):
    user_id=discord.ui.TextInput(label="Discord ID участника",placeholder="123456789012345678",max_length=20)
    action=discord.ui.TextInput(label="Действие",placeholder="timeout / kick / ban",max_length=10)
    duration=discord.ui.TextInput(label="Минуты для timeout",placeholder="Например: 60",required=False,max_length=6)
    reason=discord.ui.TextInput(label="Причина",style=discord.TextStyle.paragraph,max_length=500)
    async def on_submit(self,interaction):
        if not can_use_sanctions(interaction.user): return await interaction.response.send_message("Санкции доступны только администрации и профильным ролям поддержки.",ephemeral=True)
        try: member=interaction.guild.get_member(int(str(self.user_id).strip()))
        except ValueError: member=None
        if not member: return await interaction.response.send_message("Участник не найден.",ephemeral=True)
        action=str(self.action).strip().lower(); reason=str(self.reason).strip()
        if action not in {"timeout","kick","ban"}:
            return await interaction.response.send_message("Действие: `timeout`, `kick` или `ban`. Для варна используй выбор типа варна в панели.",ephemeral=True)
        if action in {"kick","ban"} and not can_administer(interaction.user):
            return await interaction.response.send_message("Kick и ban доступны только старшей администрации.",ephemeral=True)
        await interaction.response.defer(ephemeral=True,thinking=True)
        try:
            if action=="timeout":
                minutes=max(1,min(40320,int(str(self.duration) or "60")))
                await member.timeout(timedelta(minutes=minutes),reason=reason)
            elif action=="kick": await member.kick(reason=reason)
            elif action=="ban": await member.ban(reason=reason,delete_message_seconds=0)
        except (discord.Forbidden,discord.HTTPException,ValueError):
            return await interaction.followup.send("Не удалось применить санкцию. Проверь права и длительность.",ephemeral=True)
        sanction_description=f"Участник: {member.mention}\nДействие: **{action}**\nПричина: {reason}\nАдминистратор: {interaction.user.mention}"
        await send_staff_log(interaction.guild,"общий-журнал","⚖️ Санкция применена",sanction_description,discord.Color.orange())
        await send_punishment_log(interaction.guild,"⚖️ Санкция применена",sanction_description,discord.Color.orange())
        await interaction.followup.send(f"✅ Санкция **{action}** применена к {member.mention}.",ephemeral=True)


WARN_TYPE_LABELS={
    "anticheat":"Anticheat warn",
    "default":"Default warn",
    "pro":"Pro warn",
    "all":"ALL warn",
    "admin":"Admin warn",
}
WARN_TIER_KEYS={
    "pro":("warn_pro_1","warn_pro_2","warn_pro_3"),
    "anticheat":("anticheat_warn_1","anticheat_warn_2","anticheat_warn_3"),
    "all":("all_warn_1","all_warn_2","all_warn_3"),
    "admin":("admin_warn_1","admin_warn_2","admin_warn_3"),
}


def find_default_warn_roles(guild):
    roles=[]
    for level in (1,2,3):
        role=next((r for r in guild.roles if normalized_role_name(r.name).startswith(f"{level}/3") and ("default" in normalized_role_name(r.name) or "деф" in normalized_role_name(r.name)) and ("warn" in normalized_role_name(r.name) or "варн" in normalized_role_name(r.name))),None)
        roles.append(role)
    return roles


def can_issue_warn_type(member,warn_type):
    if not can_use_sanctions(member):
        return False
    senior=(STAFF_ROLES["owner"],EXTRA_ROLE_SPECS["developer"][0],EXTRA_ROLE_SPECS["director"][0],EXTRA_ROLE_SPECS["head_admin"][0])
    if member.id==member.guild.owner_id or any(has_role(member,name) for name in senior):
        return True
    if warn_type=="anticheat":
        return has_role(member,EXTRA_ROLE_SPECS["head_ac"][0]) or has_role(member,EXTRA_ROLE_SPECS["anticheat"][0]) or has_role(member,STAFF_ROLES["admin"])
    if warn_type=="admin":
        return has_role(member,STAFF_ROLES["admin"])
    if warn_type=="all":
        return False
    league_warn_roles=(
        STAFF_ROLES["admin"],EXTRA_ROLE_SPECS["ticket_admin"][0],
        EXTRA_ROLE_SPECS["games_admin"][0],EXTRA_ROLE_SPECS["moderator"][0],
    )
    return any(has_role(member,name) for name in league_warn_roles)


class WarnMemberSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="Выбери участника",min_values=1,max_values=1,row=0)
    async def callback(self,interaction):
        member=self.values[0]
        self.view.target_id=member.id
        self.placeholder=f"Участник: {member.display_name}"[:150]
        await interaction.response.edit_message(embed=self.view.make_embed(interaction.guild),view=self.view)


class WarnTypeSelect(discord.ui.Select):
    def __init__(self):
        options=[discord.SelectOption(label=label,value=key,emoji="⚠️") for key,label in WARN_TYPE_LABELS.items()]
        super().__init__(placeholder="Выбери тип варна",options=options,min_values=1,max_values=1,row=1)
    async def callback(self,interaction):
        self.view.warn_type=self.values[0]
        self.placeholder=f"Тип: {WARN_TYPE_LABELS[self.values[0]]}"[:150]
        await interaction.response.edit_message(embed=self.view.make_embed(interaction.guild),view=self.view)


class WarnReasonModal(discord.ui.Modal,title="Выдать варн"):
    reason=discord.ui.TextInput(label="Причина варна",style=discord.TextStyle.paragraph,min_length=2,max_length=500)
    def __init__(self,target_id,warn_type):
        super().__init__(); self.target_id=target_id; self.warn_type=warn_type

    async def on_submit(self,interaction):
        member=interaction.guild.get_member(self.target_id)
        if not member:
            return await interaction.response.send_message("Участник не найден.",ephemeral=True)
        if not can_issue_warn_type(interaction.user,self.warn_type):
            return await interaction.response.send_message("У тебя нет права выдавать этот тип варна.",ephemeral=True)
        await interaction.response.defer(ephemeral=True,thinking=True)
        roles=await ensure_staff_roles(interaction.guild)
        role=None; old_roles=[]
        if self.warn_type=="default":
            tier_roles=find_default_warn_roles(interaction.guild)
        else:
            tier_roles=[roles.get(key) for key in WARN_TIER_KEYS[self.warn_type]]
        if not all(tier_roles):
            return await interaction.followup.send("Не найдены роли 1/3, 2/3 и 3/3 для этого варна. Проверь их названия на сервере.",ephemeral=True)
        current=max((index for index,item in enumerate(tier_roles) if item in member.roles),default=-1)
        next_index=min(current+1,2)
        if current==2:
            return await interaction.followup.send(f"У участника уже максимальный варн **{tier_roles[2].name}**.",ephemeral=True)
        role=tier_roles[next_index]
        old_roles=[item for item in tier_roles if item in member.roles and item!=role]
        if not role:
            return await interaction.followup.send("Роль выбранного варна не найдена.",ephemeral=True)
        if role >= interaction.guild.me.top_role:
            return await interaction.followup.send("Бот не может выдать эту роль: подними роль бота выше ролей варнов.",ephemeral=True)
        try:
            if old_roles:
                await member.remove_roles(*old_roles,reason=f"DOMINION FACEIT warn upgrade by {interaction.user}")
            await member.add_roles(role,reason=f"DOMINION FACEIT {WARN_TYPE_LABELS[self.warn_type]} by {interaction.user}")
        except discord.Forbidden:
            return await interaction.followup.send("Discord не разрешил выдать роль варна. Проверь право `Управлять ролями` и иерархию ролей.",ephemeral=True)
        reason=str(self.reason).strip()
        try: await member.send(f"⚠️ На сервере **{interaction.guild.name}** тебе выдан **{role.name}**. Причина: {reason}")
        except discord.HTTPException: pass
        warn_description=f"Участник: {member.mention}\nТип: **{WARN_TYPE_LABELS[self.warn_type]}**\nРоль: {role.mention}\nПричина: {reason}\nВыдал: {interaction.user.mention}"
        await send_staff_log(interaction.guild,"общий-журнал","⚠️ Выдан варн",warn_description,discord.Color.orange())
        await send_punishment_log(interaction.guild,"⚠️ Выдан варн",warn_description,discord.Color.orange())
        await interaction.followup.send(f"✅ Участнику {member.mention} выдана роль {role.mention}.",ephemeral=True)


class WarnPanelView(discord.ui.View):
    def __init__(self,manager):
        super().__init__(timeout=300)
        self.manager_id=manager.id; self.target_id=None; self.warn_type=None
        self.add_item(WarnMemberSelect()); self.add_item(WarnTypeSelect())

    def make_embed(self,guild):
        member=guild.get_member(self.target_id) if self.target_id else None
        who=member.mention if member else "не выбран"
        warn=WARN_TYPE_LABELS.get(self.warn_type,"не выбран")
        return discord.Embed(title="⚠️ ВЫДАЧА ВАРНА",description=f"Участник: {who}\nТип варна: **{warn}**\n\nПосле выбора нажми **Выдать варн**.",color=discord.Color.orange())

    async def interaction_check(self,interaction):
        if interaction.user.id!=self.manager_id:
            await interaction.response.send_message("Эта панель открыта другим сотрудником.",ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Выдать варн",emoji="⚠️",style=discord.ButtonStyle.danger,row=2)
    async def issue_warn(self,interaction,button):
        if not self.target_id or not self.warn_type:
            return await interaction.response.send_message("Сначала выбери участника и тип варна.",ephemeral=True)
        if not can_issue_warn_type(interaction.user,self.warn_type):
            return await interaction.response.send_message("У тебя нет права выдавать этот тип варна.",ephemeral=True)
        await interaction.response.send_modal(WarnReasonModal(self.target_id,self.warn_type))

    @discord.ui.button(label="Timeout / Kick / Ban",emoji="🛡️",style=discord.ButtonStyle.secondary,row=2)
    async def other_sanction(self,interaction,button):
        await interaction.response.send_modal(SanctionModal())


REMOVE_SANCTION_LABELS={
    "all_warns":"Снять все варны",
    "anticheat":"Снять Anticheat warn",
    "default":"Снять Default warn",
    "pro":"Снять Pro warn",
    "admin":"Снять Admin warn",
    "timeout":"Снять мут / timeout",
}


def warning_roles_for_type(guild,warn_type,roles):
    if warn_type=="all_warns":
        result=[]
        for role in guild.roles:
            name=normalized_role_name(role.name)
            if "warn" in name or "варн" in name:
                result.append(role)
        return result
    if warn_type=="default":
        return [role for role in find_default_warn_roles(guild) if role]
    if warn_type in WARN_TIER_KEYS:
        return [roles.get(key) for key in WARN_TIER_KEYS[warn_type] if roles.get(key)]
    return []


def can_remove_sanction_type(member,action):
    if action=="timeout":
        return can_use_sanctions(member)
    warn_type="all" if action=="all_warns" else action
    return can_issue_warn_type(member,warn_type)


class RemoveSanctionMemberSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="Выбери участника",min_values=1,max_values=1,row=0)
    async def callback(self,interaction):
        member=self.values[0]
        self.view.target_id=member.id
        self.placeholder=f"Участник: {member.display_name}"[:150]
        await interaction.response.edit_message(embed=self.view.make_embed(interaction.guild),view=self.view)


class RemoveSanctionTypeSelect(discord.ui.Select):
    def __init__(self):
        options=[discord.SelectOption(label=label,value=key,emoji="♻️") for key,label in REMOVE_SANCTION_LABELS.items()]
        super().__init__(placeholder="Выбери, что снять",options=options,min_values=1,max_values=1,row=1)
    async def callback(self,interaction):
        self.view.action=self.values[0]
        self.placeholder=REMOVE_SANCTION_LABELS[self.values[0]][:150]
        await interaction.response.edit_message(embed=self.view.make_embed(interaction.guild),view=self.view)


class UnbanMemberModal(discord.ui.Modal,title="Разбанить и вернуть на сервер"):
    user_id=discord.ui.TextInput(label="Discord ID пользователя",placeholder="123456789012345678",max_length=20)
    reason=discord.ui.TextInput(label="Причина разбана",style=discord.TextStyle.paragraph,required=False,max_length=300)

    async def on_submit(self,interaction):
        if not can_administer(interaction.user):
            return await interaction.response.send_message("Разбан доступен только администрации.",ephemeral=True)
        try: user_id=int(str(self.user_id).strip())
        except ValueError: return await interaction.response.send_message("Укажи корректный Discord ID.",ephemeral=True)
        await interaction.response.defer(ephemeral=True,thinking=True)
        reason=str(self.reason).strip() or "не указана"
        try:
            user=await bot.fetch_user(user_id)
            await interaction.guild.unban(user,reason=f"DOMINION FACEIT unban by {interaction.user}: {reason}")
        except discord.NotFound:
            return await interaction.followup.send("Пользователь не найден в списке заблокированных.",ephemeral=True)
        except (discord.Forbidden,discord.HTTPException):
            return await interaction.followup.send("Не удалось разбанить пользователя. Проверь право бота `Банить участников`.",ephemeral=True)
        invite=None
        for channel in interaction.guild.text_channels:
            if channel.permissions_for(interaction.guild.me).create_instant_invite:
                try:
                    invite=await channel.create_invite(max_age=86400,max_uses=1,unique=True,reason="DOMINION FACEIT: возврат после разбана")
                    break
                except discord.HTTPException:
                    continue
        if invite:
            try: await user.send(f"✅ Ты разбанен на сервере **{interaction.guild.name}**. Одноразовая ссылка для возвращения: {invite.url}")
            except discord.HTTPException: pass
        unban_description=f"Пользователь: {user.mention} (`{user.id}`)\nПричина: {reason}\nАдминистратор: {interaction.user.mention}"
        await send_staff_log(interaction.guild,"общий-журнал","♻️ Пользователь разбанен",unban_description,discord.Color.green())
        await send_punishment_log(interaction.guild,"♻️ Пользователь разбанен",unban_description,discord.Color.green())
        suffix=" Одноразовое приглашение отправлено в личные сообщения." if invite else " Приглашение создать не удалось — отправь ссылку вручную."
        await interaction.followup.send(f"✅ {user.mention} разбанен.{suffix}",ephemeral=True)


class RemoveSanctionView(discord.ui.View):
    def __init__(self,manager):
        super().__init__(timeout=300)
        self.manager_id=manager.id; self.target_id=None; self.action=None
        self.add_item(RemoveSanctionMemberSelect()); self.add_item(RemoveSanctionTypeSelect())

    def make_embed(self,guild):
        member=guild.get_member(self.target_id) if self.target_id else None
        who=member.mention if member else "не выбран"
        action=REMOVE_SANCTION_LABELS.get(self.action,"не выбрано")
        return discord.Embed(title="♻️ СНЯТИЕ САНКЦИЙ",description=f"Участник: {who}\nДействие: **{action}**\n\nДля разбана пользователя, которого уже нет на сервере, используй отдельную кнопку.",color=discord.Color.green())

    async def interaction_check(self,interaction):
        if interaction.user.id!=self.manager_id:
            await interaction.response.send_message("Эта панель открыта другим сотрудником.",ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Снять санкцию",emoji="♻️",style=discord.ButtonStyle.success,row=2)
    async def remove_sanction(self,interaction,button):
        if not self.target_id or not self.action:
            return await interaction.response.send_message("Сначала выбери участника и санкцию.",ephemeral=True)
        if not can_remove_sanction_type(interaction.user,self.action):
            return await interaction.response.send_message("У тебя нет права снимать этот тип санкции.",ephemeral=True)
        member=interaction.guild.get_member(self.target_id)
        if not member:
            return await interaction.response.send_message("Участник не найден на сервере.",ephemeral=True)
        await interaction.response.defer(ephemeral=True,thinking=True)
        if self.action=="timeout":
            try:
                await member.timeout(None,reason=f"DOMINION FACEIT timeout removed by {interaction.user}")
            except (discord.Forbidden,discord.HTTPException):
                return await interaction.followup.send("Не удалось снять мут. Проверь права бота и иерархию ролей.",ephemeral=True)
            removed_text="мут / timeout"
        else:
            roles=await ensure_staff_roles(interaction.guild)
            candidates=warning_roles_for_type(interaction.guild,self.action,roles)
            removable=[role for role in candidates if role in member.roles and role < interaction.guild.me.top_role]
            if not removable:
                return await interaction.followup.send("У участника нет выбранного варна или бот не может управлять его ролью.",ephemeral=True)
            try:
                await member.remove_roles(*removable,reason=f"DOMINION FACEIT warnings removed by {interaction.user}")
            except discord.Forbidden:
                return await interaction.followup.send("Не удалось снять роли варнов. Подними роль бота выше них.",ephemeral=True)
            removed_text=", ".join(role.name for role in removable)
        removal_description=f"Участник: {member.mention}\nСнято: **{removed_text}**\nАдминистратор: {interaction.user.mention}"
        await send_staff_log(interaction.guild,"общий-журнал","♻️ Санкция снята",removal_description,discord.Color.green())
        await send_punishment_log(interaction.guild,"♻️ Санкция снята",removal_description,discord.Color.green())
        await interaction.followup.send(f"✅ С участника {member.mention} снято: **{removed_text}**.",ephemeral=True)

    @discord.ui.button(label="Разбанить / вернуть",emoji="🔓",style=discord.ButtonStyle.primary,row=2)
    async def unban(self,interaction,button):
        if not can_administer(interaction.user):
            return await interaction.response.send_message("Разбан доступен только администрации.",ephemeral=True)
        await interaction.response.send_modal(UnbanMemberModal())


class MatchAdminModal(discord.ui.Modal,title="Управление матчем"):
    match_id=discord.ui.TextInput(label="Номер матча",max_length=10)
    action=discord.ui.TextInput(label="Действие",placeholder="info или finish",max_length=10)
    score=discord.ui.TextInput(label="Счёт для finish",placeholder="13:9",required=False,max_length=7)
    async def on_submit(self,interaction):
        try: match_id=int(str(self.match_id)); match=db.match(match_id)
        except ValueError: match=None
        if not match: return await interaction.response.send_message("Игры с таким номером нет.",ephemeral=True)
        action=str(self.action).strip().lower()
        if action=="info":
            return await interaction.response.send_message(embed=discord.Embed(title=f"🎮 Матч #{match_id}",description=f"Лига: **{league_display_name(match['league'])}**\nКарта: **{match['map']}**\nСтатус: **{match['status']}**\nСчёт: **{match['score_a']}:{match['score_b']}**",color=color()),ephemeral=True)
        if action!="finish": return await interaction.response.send_message("Действие: `info` или `finish`.",ephemeral=True)
        try:
            a,b=[int(x) for x in str(self.score).replace("-",":").split(":",1)]
            assert (a==13 or b==13) and a!=b
        except Exception: return await interaction.response.send_message("Укажи корректный счёт, например `13:9`.",ephemeral=True)
        await interaction.response.defer(ephemeral=True,thinking=True)
        if not db.finish_match(match_id,a,b): return await interaction.followup.send("Матч уже завершён.",ephemeral=True)
        await send_staff_log(interaction.guild,"журнал-матчей","🎮 Матч завершён",f"Матч **#{match_id}** · счёт **{a}:{b}** · администратор {interaction.user.mention}",discord.Color.green())
        await interaction.followup.send(f"✅ Матч #{match_id} завершён: **{a}:{b}**.",ephemeral=True)


class CloseTicketModal(discord.ui.Modal,title="Закрыть тикет"):
    channel_id=discord.ui.TextInput(label="ID канала тикета",max_length=20)
    reason=discord.ui.TextInput(label="Причина закрытия",required=False,max_length=200)
    async def on_submit(self,interaction):
        try: channel=interaction.guild.get_channel(int(str(self.channel_id)))
        except ValueError: channel=None
        if not channel or not (channel.topic or "").startswith("ticket-owner:"):
            return await interaction.response.send_message("Канал тикета не найден.",ephemeral=True)
        name=channel.name
        await interaction.response.defer(ephemeral=True,thinking=True)
        reason=str(self.reason).strip() or "не указана"
        await send_ticket_close_log(channel,interaction.user,reason)
        await interaction.followup.send(f"Тикет **{name}** закрыт.",ephemeral=True)
        await delete_ticket_fully(channel,interaction.user,reason)


class StaffControlView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    async def allowed(self,i):
        if can_administer(i.user) or can_use_role_panel(i.user): return True
        await i.response.send_message("Нет доступа к панели штаба.",ephemeral=True); return False
    @discord.ui.button(label="Санкции",emoji="⚖️",style=discord.ButtonStyle.danger,custom_id="staff:sanction",row=0)
    async def sanctions(self,i,b):
        if not can_use_sanctions(i.user):
            return await i.response.send_message("Санкции доступны только администрации и профильным ролям поддержки.",ephemeral=True)
        view=WarnPanelView(i.user)
        await i.response.send_message(embed=view.make_embed(i.guild),view=view,ephemeral=True)
    @discord.ui.button(label="Снять санкцию",emoji="♻️",style=discord.ButtonStyle.success,custom_id="staff:remove_sanction",row=0)
    async def remove_sanction(self,i,b):
        if not can_use_sanctions(i.user):
            return await i.response.send_message("Снятие санкций доступно только администрации и профильным ролям поддержки.",ephemeral=True)
        view=RemoveSanctionView(i.user)
        await i.response.send_message(embed=view.make_embed(i.guild),view=view,ephemeral=True)
    @discord.ui.button(label="Роли",emoji="🛡️",style=discord.ButtonStyle.primary,custom_id="staff:roles",row=0)
    async def roles(self,i,b):
        if await self.allowed(i): await i.response.send_message(embed=discord.Embed(title="🛡️ Управление ролями",description="Выбери участника и доступную роль.",color=color()),view=RolePanelView(i.user),ephemeral=True)
    @discord.ui.button(label="Матчи",emoji="����",style=discord.ButtonStyle.primary,custom_id="staff:matches",row=0)
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


STAFF_APPLICATION_TYPES={
    "moderator":("Moderator","moderator","📨・заявки-модератор"),
    "ticket_support":("Game Support","ticket_support","📨・заявки-game-support"),
}


def can_review_staff_application(member,application_type):
    senior=(STAFF_ROLES["owner"],STAFF_ROLES["admin"],EXTRA_ROLE_SPECS["developer"][0],EXTRA_ROLE_SPECS["director"][0],EXTRA_ROLE_SPECS["head_admin"][0])
    if member.id==member.guild.owner_id or any(has_role(member,name) for name in senior): return True
    return application_type=="ticket_support" and has_role(member,EXTRA_ROLE_SPECS["ticket_admin"][0])


class StaffApplicationModal(discord.ui.Modal):
    age=discord.ui.TextInput(label="Возраст",placeholder="Например: 16",max_length=3)
    experience=discord.ui.TextInput(label="Опыт",style=discord.TextStyle.paragraph,placeholder="Опиши опыт модерации или поддержки",max_length=700)
    motivation=discord.ui.TextInput(label="Почему именно ты?",style=discord.TextStyle.paragraph,max_length=700)
    online=discord.ui.TextInput(label="Онлайн в день",placeholder="Например: 4–6 часов",max_length=80)
    def __init__(self,application_type):
        title=STAFF_APPLICATION_TYPES[application_type][0]
        super().__init__(title=f"Заявка: {title}"); self.application_type=application_type
    async def on_submit(self,interaction):
        try:
            await interaction.response.defer(ephemeral=True,thinking=True)
            title,role_key,channel_name=STAFF_APPLICATION_TYPES[self.application_type]
            channel=discord.utils.get(interaction.guild.text_channels,name=channel_name)
            if not channel:
                return await interaction.followup.send("Канал заявок не найден. Администратору нужно выполнить `/setup`.",ephemeral=True)
            permissions=channel.permissions_for(interaction.guild.me)
            if not permissions.view_channel or not permissions.send_messages or not permissions.embed_links:
                return await interaction.followup.send(
                    f"Бот не может отправить заявку в {channel.mention}. Выдай ему права `Просмотр канала`, `Отправка сообщений` и `Встраивание ссылок`.",
                    ephemeral=True,
                )
            embed=discord.Embed(title=f"📨 Заявка на {title}",description=f"Кандидат: {interaction.user.mention} (`{interaction.user.id}`)",color=discord.Color.purple(),timestamp=datetime.now(timezone.utc))
            embed.add_field(name="Возраст",value=self.age.value[:1024],inline=True)
            embed.add_field(name="Онлайн",value=self.online.value[:1024],inline=True)
            embed.add_field(name="Опыт",value=self.experience.value[:1024],inline=False)
            embed.add_field(name="Мотивация",value=self.motivation.value[:1024],inline=False)
            view=discord.ui.View(timeout=None)
            view.add_item(discord.ui.Button(label="Принять",emoji="✅",style=discord.ButtonStyle.success,custom_id=f"staffapp:accept:{self.application_type}:{interaction.user.id}"))
            view.add_item(discord.ui.Button(label="Отклонить",emoji="❌",style=discord.ButtonStyle.danger,custom_id=f"staffapp:reject:{self.application_type}:{interaction.user.id}"))
            await channel.send(embed=embed,view=view)
            await interaction.followup.send(f"✅ Заявка на **{title}** отправлена.",ephemeral=True)
        except Exception as exc:
            print(f"Staff application submit error: {type(exc).__name__}: {exc!r}",flush=True)
            message=f"Не удалось отправить заявку: `{type(exc).__name__}`. Проверь права бота в канале заявок."
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(message,ephemeral=True)
                else:
                    await interaction.response.send_message(message,ephemeral=True)
            except discord.HTTPException:
                pass


class StaffApplicationPanelView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Заявка на Moderator",emoji="🛡️",style=discord.ButtonStyle.primary,custom_id="staffapp:open:moderator")
    async def moderator(self,interaction,button): await interaction.response.send_modal(StaffApplicationModal("moderator"))
    @discord.ui.button(label="Заявка на Game Support",emoji="🎫",style=discord.ButtonStyle.secondary,custom_id="staffapp:open:ticket_support")
    async def ticket_support(self,interaction,button): await interaction.response.send_modal(StaffApplicationModal("ticket_support"))


async def handle_staff_application_review(interaction,cid):
    try: _,action,application_type,user_id=cid.split(":",3); user_id=int(user_id)
    except (ValueError,TypeError): return await interaction.response.send_message("Некорректная заявка.",ephemeral=True)
    if not can_review_staff_application(interaction.user,application_type):
        return await interaction.response.send_message("У тебя нет доступа к этой заявке.",ephemeral=True)
    await interaction.response.defer(ephemeral=True,thinking=True)
    member=interaction.guild.get_member(user_id)
    if not member:
        return await interaction.followup.send("Кандидат больше не находится на сервере.",ephemeral=True)
    title,role_key,_=STAFF_APPLICATION_TYPES[application_type]
    status="принята" if action=="accept" else "отклонена"
    if action=="accept":
        roles=await ensure_staff_roles(interaction.guild); role=roles.get(role_key)
        if not role: return await interaction.followup.send("Целевая роль не найдена.",ephemeral=True)
        try: await member.add_roles(role,reason=f"DOMINION staff application accepted by {interaction.user}")
        except discord.Forbidden: return await interaction.followup.send("Бот не может выдать роль. Проверь иерархию.",ephemeral=True)
    embed=interaction.message.embeds[0] if interaction.message.embeds else discord.Embed(title=f"Заявка на {title}")
    embed.color=discord.Color.green() if action=="accept" else discord.Color.red()
    embed.add_field(name="Решение",value=f"**{status.upper()}** • {interaction.user.mention}",inline=False)
    await interaction.message.edit(embed=embed,view=None)
    try: await member.send(f"Твоя заявка на **{title}** в **{interaction.guild.name}** {status}.")
    except discord.HTTPException: pass
    await interaction.followup.send(f"Заявка {status}.",ephemeral=True)


async def ensure_staff_application_system(guild):
    roles=await ensure_staff_roles(guild)
    staff_category=discord.utils.get(guild.categories,name="🛡️ DOMINION STAFF") or await guild.create_category("🛡️ DOMINION STAFF")
    senior_keys=("owner","admin","developer","director","head_admin")
    legacy_channels={
        "moderator":"📨・заявки-модераторы",
        "ticket_support":"📨・заявки-тикет-саппорт",
    }
    for application_type,(title,role_key,channel_name) in STAFF_APPLICATION_TYPES.items():
        channel=discord.utils.get(guild.text_channels,name=channel_name)
        legacy=discord.utils.get(guild.text_channels,name=legacy_channels[application_type])
        if not channel and legacy:
            try:
                await legacy.edit(name=channel_name,category=staff_category,reason="DOMINION: актуальные заявки на роли")
                channel=legacy
            except discord.HTTPException:
                pass
        overwrites={
            guild.default_role:discord.PermissionOverwrite(view_channel=False),
            guild.me:discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_messages=True),
        }
        for key in senior_keys:
            role=roles.get(key)
            if role:
                overwrites[role]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True)
        if application_type=="ticket_support" and roles.get("ticket_admin"):
            overwrites[roles["ticket_admin"]]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True)
        if not channel:
            channel=await guild.create_text_channel(channel_name,category=staff_category,overwrites=overwrites,reason="DOMINION /setup: заявки на роли")
        else:
            for target,overwrite in overwrites.items():
                await channel.set_permissions(target,overwrite=overwrite)

    support=(discord.utils.get(guild.categories,name="🆘 DOMINION SUPPORT")
             or discord.utils.get(guild.categories,name="💬 DOMINION COMMUNITY"))
    if not support:
        support=await guild.create_category("🆘 DOMINION SUPPORT")
    panel=discord.utils.get(guild.text_channels,name="📨・заявки-на-роли")
    legacy_panel=discord.utils.get(guild.text_channels,name="📨・заявки-на-стафф")
    if not panel and legacy_panel:
        try:
            await legacy_panel.edit(name="📨・заявки-на-роли",category=support,reason="DOMINION: заявки на роли")
            panel=legacy_panel
        except discord.HTTPException:
            pass
    if not panel:
        panel=await guild.create_text_channel("📨・заявки-на-роли",category=support,reason="DOMINION /setup: заявки на роли")
    registered=find_role(guild,REGISTERED_ROLE_NAME)
    await panel.set_permissions(guild.default_role,view_channel=False,send_messages=False,read_message_history=False,use_application_commands=False)
    if registered:
        await panel.set_permissions(registered,view_channel=True,send_messages=False,read_message_history=True,use_application_commands=True)
    await panel.set_permissions(guild.me,view_channel=True,send_messages=True,manage_messages=True,read_message_history=True)

    # Rebuild the bot panel so the visible buttons always say Moderator and Game Support.
    async for message in panel.history(limit=100):
        if message.author==guild.me and message.embeds and message.embeds[0].title=="👑 DOMINION STAFF APPLICATIONS":
            try: await message.delete()
            except discord.HTTPException: pass
    embed=discord.Embed(title="👑 DOMINION STAFF APPLICATIONS",description="Выбери роль и заполни анкету. Заявку увидит только ответственная администрация.",color=discord.Color.purple())
    embed.add_field(name="Moderator",value="Заявку рассматривают Admin и старшее руководство.",inline=False)
    embed.add_field(name="Game Support",value="Заявку рассматривают Game Support и старшее руководство.",inline=False)
    application_banner=BASE_DIR/"assets"/"applications-banner-v2.png"
    if application_banner.exists():
        embed.set_image(url="attachment://applications-banner-v2.png")
        await panel.send(embed=embed,view=StaffApplicationPanelView(),file=discord.File(application_banner,filename="applications-banner-v2.png"))
    else:
        await panel.send(embed=embed,view=StaffApplicationPanelView())
    return panel


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
        await interaction.response.defer(ephemeral=True,thinking=True)
        key=self.values[0]
        emoji,title,description,staff_keys=self.TICKET_TYPES[key]
        guild=interaction.guild
        staff_roles=await ensure_staff_roles(guild)
        existing=next((c for c in guild.text_channels if (c.topic or "").startswith(f"ticket-owner:{interaction.user.id}")),None)
        if existing:
            return await interaction.followup.send(f"У тебя уже есть открытый тикет: {existing.mention}",ephemeral=True)
        category=discord.utils.get(guild.categories,name="🎫 TICKETS") or await guild.create_category("🎫 TICKETS")
        overwrites={
            guild.default_role:discord.PermissionOverwrite(view_channel=False),
            interaction.user:discord.PermissionOverwrite(view_channel=True,send_messages=True,attach_files=True,read_message_history=True),
            guild.me:discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_channels=True,manage_messages=True),
        }
        oversight_keys=("owner","developer","director","head_admin")
        for staff_key in dict.fromkeys((*staff_keys,*oversight_keys)):
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
        await notify_ticket_inbox(guild,channel,title,interaction.user)
        await interaction.followup.send(f"Тикет создан: {channel.mention}",ephemeral=True)


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


def ticket_type_key(channel):
    parts=(channel.topic or "").split(":")
    return parts[2] if len(parts)>=3 and parts[0]=="ticket-owner" else None


def ticket_claimed_by(channel):
    parts=(channel.topic or "").split(":")
    if "claimed" not in parts:
        return None
    try:
        return int(parts[parts.index("claimed")+1])
    except (ValueError,IndexError):
        return None


def staff_role_name(key):
    if key in STAFF_ROLES:
        return STAFF_ROLES[key]
    spec=EXTRA_ROLE_SPECS.get(key)
    return spec[0] if spec else None


TICKET_CLAIM_ROLES={
    "cheats": ("head_ac","anticheat"),
    "player": ("ticket_admin","moderator"),
    "match": ("games_admin","curator_qualifications","curator_division","curator_pro"),
    "staff": ("head_admin",),
    "appeal": ("ticket_admin",),
    "other": ("ticket_admin",),
}


def can_claim_ticket(member,channel):
    keys=TICKET_CLAIM_ROLES.get(ticket_type_key(channel),())
    return any((name:=staff_role_name(key)) and has_role(member,name) for key in keys)


async def ensure_admin_panel_buttons(guild):
    channel=discord.utils.get(guild.text_channels,name="🎛️・панель-админа")
    if not channel:
        return False
    try:
        async for message in channel.history(limit=30):
            if message.author!=guild.me or not message.embeds:
                continue
            if message.embeds[0].title not in {"🎛️ ПАНЕЛЬ АДМИНА","🛡️ DOMINION CONTROL DESK"}:
                continue
            component_ids={getattr(child,"custom_id",None) for row in message.components for child in getattr(row,"children",())}
            if "staff:remove_sanction" not in component_ids:
                await message.edit(view=StaffControlView())
                return True
            return False
    except discord.HTTPException:
        return False
    return False


async def ensure_ticket_inbox(guild):
    """Создать единый канал входящих тикетов без дубликатов."""
    channel_name="🎫・входящие-тикеты"
    existing=discord.utils.get(guild.text_channels,name=channel_name)
    if existing:
        return existing
    category=discord.utils.get(guild.categories,name="🛡️ DOMINION STAFF")
    if not category:
        category=await guild.create_category("🛡️ DOMINION STAFF",reason="DOMINION FACEIT: раздел администрации")
    overwrites={
        guild.default_role:discord.PermissionOverwrite(view_channel=False),
        guild.me:discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_messages=True,read_message_history=True),
    }
    oversight_keys=("owner","developer","director","head_admin")
    handler_keys=tuple(dict.fromkeys(key for keys in TICKET_CLAIM_ROLES.values() for key in keys))
    for key in dict.fromkeys((*oversight_keys,*handler_keys)):
        name=staff_role_name(key)
        role=find_role(guild,name) if name else None
        if role:
            overwrites[role]=discord.PermissionOverwrite(view_channel=True,send_messages=False,read_message_history=True)
    channel=await guild.create_text_channel(channel_name,category=category,overwrites=overwrites,reason="DOMINION FACEIT: входящие тикеты")
    intro=discord.Embed(title="🎫 ВХОДЯЩИЕ ТИКЕТЫ",description="��юда поступают уведомления обо всех новых обращениях. Открыть сам тикет смо��ут только профильные сотрудники и старшее руководство.",color=color())
    await channel.send(embed=intro)
    return channel


async def notify_ticket_inbox(guild,ticket_channel,title,author):
    inbox=await ensure_ticket_inbox(guild)
    embed=discord.Embed(title="🎫 Новый тикет",description=f"Раздел: **{title}**\nАвтор: {author.mention}\nКанал: {ticket_channel.mention}",color=discord.Color.purple())
    view=discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Открыть тикет",emoji="🎫",style=discord.ButtonStyle.link,url=ticket_channel.jump_url))
    await inbox.send(embed=embed,view=view)


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
        await interaction.response.defer(ephemeral=True,thinking=True)
        await send_ticket_close_log(channel,interaction.user,reason)
        await interaction.followup.send("Тикет закрывается…",ephemeral=True)
        await asyncio.sleep(1)
        await delete_ticket_fully(channel,interaction.user,reason)


class TicketChannelView(discord.ui.View):
    def __init__(self,claimed=False):
        super().__init__(timeout=None)
        if claimed:
            self.claim_ticket.disabled=True
            self.claim_ticket.label="Тикет уже взят"

    @discord.ui.button(label="Взять тикет",emoji="🙋",style=discord.ButtonStyle.success,custom_id="ticket:claim:button")
    async def claim_ticket(self,interaction,button):
        channel=interaction.channel
        if not isinstance(channel,discord.TextChannel) or ticket_owner_id(channel) is None:
            return await interaction.response.send_message("Эта кнопка работает только внутри тикета.",ephemeral=True)
        claimed_by=ticket_claimed_by(channel)
        if claimed_by:
            return await interaction.response.send_message(f"Тикет уже взял <@{claimed_by}>.",ephemeral=True)
        if not can_claim_ticket(interaction.user,channel):
            return await interaction.response.send_message("Этот тип тикета может взять только профильная роль поддержки.",ephemeral=True)
        await interaction.response.defer(ephemeral=True,thinking=True)
        topic=(channel.topic or "").split(":claimed:",1)[0]+f":claimed:{interaction.user.id}"
        try:
            await channel.edit(topic=topic,reason=f"DOMINION FACEIT ticket claimed by {interaction.user}")
            await channel.send(embed=discord.Embed(title="🙋 Тикет взят в работу",description=f"Ответственный: {interaction.user.mention}",color=discord.Color.green()))
            await send_staff_log(interaction.guild,"журнал-тикетов","🙋 Тикет взят в работу",f"Канал: {channel.mention}\nОтветственный: {interaction.user.mention}",discord.Color.green())
            await interaction.followup.send("Ты взял этот тикет в работу.",ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("Не удалось закрепить тикет: боту нужно право `Управлять каналами`.",ephemeral=True)

    @discord.ui.button(label="Закрыть тикет",emoji="🔒",style=discord.ButtonStyle.danger,custom_id="ticket:close:button")
    async def close_ticket(self,interaction,button):
        if not isinstance(interaction.channel,discord.TextChannel) or ticket_owner_id(interaction.channel) is None:
            return await interaction.response.send_message("Эта кнопка работает только внутри тикета.",ephemeral=True)
        if not can_close_ticket(interaction.user,interaction.channel):
            return await interaction.response.send_message("Закрыть тикет может его автор или сотр��дник админ��страции.",ephemeral=True)
        await interaction.response.send_modal(CloseCurrentTicketModal())


async def ensure_ticket_close_buttons(guild):
    """Добавить или обновить панель только в тикетах, где нет кнопки «Взять тикет»."""
    changed=0
    for channel in guild.text_channels:
        if ticket_owner_id(channel) is None:
            continue
        control_message=None
        try:
            async for message in channel.history(limit=30):
                if message.author==guild.me and any(embed.title=="🔒 Управление тикетом" for embed in message.embeds):
                    control_message=message
                    break
        except discord.HTTPException:
            continue
        control=discord.Embed(title="🔒 Управление тикетом",description="Профильный сотрудник может взять тикет в работу. Автор или администрация могут закрыть его.",color=discord.Color.red())
        try:
            if control_message:
                component_ids={getattr(child,"custom_id",None) for row in control_message.components for child in getattr(row,"children",())}
                if "ticket:claim:button" not in component_ids:
                    await control_message.edit(embed=control,view=TicketChannelView(claimed=bool(ticket_claimed_by(channel))))
                    changed+=1
            else:
                await channel.send(embed=control,view=TicketChannelView(claimed=bool(ticket_claimed_by(channel))))
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
        if not guild_match(interaction.guild_id,self.match_id):
            return await interaction.response.send_message("Игры с таким номером нет.",ephemeral=True)
        if not db.finish_match(self.match_id,a,b):
            return await interaction.response.send_message("Игра уже завершена.",ephemeral=True)
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

    @discord.ui.button(label="Dominion Rise",emoji="🟡",style=discord.ButtonStyle.secondary,custom_id="top:qualifications",row=0)
    async def qualifications_top(self,i,b): await send_league_top(i,"Qualifications")

    @discord.ui.button(label="Division",emoji="🟣",style=discord.ButtonStyle.secondary,custom_id="top:division",row=0)
    async def division_top(self,i,b): await send_league_top(i,"Division")

    @discord.ui.button(label="Pro",emoji="🔴",style=discord.ButtonStyle.secondary,custom_id="top:pro",row=0)
    async def pro_top(self,i,b): await send_league_top(i,"Pro")


def league_top_embed():
    e=discord.Embed(title="🏆 ТОП СЕРВЕРА",description="Выбери лигу — бот пришлёт красочную карточку топ-10 игроков этой лиги.",color=color())
    e.add_field(name="⚪ Default",value="Участники Default League",inline=True)
    e.add_field(name="🟢 Dominion Rise",value="Участники квалификации",inline=True)
    e.add_field(name="🟣 Division",value="Участники Division",inline=True)
    e.add_field(name="🔴 Pro",value="Участники Pro",inline=True)
    e.set_footer(text="Топ строится по ELO и учитывает только игроков с ролью лиги")
    return e


def build_profile_meta(guild,player_data,member=None):
    current_league=player_league(int(player_data.get("points",0)))
    league_rows=[row for row in db.leaders(guild.id,1000) if player_league(int(row.get("points",0)))==current_league]
    position=next((i for i,row in enumerate(league_rows,1) if int(row["user_id"])==int(player_data["user_id"])),None)
    top=[]
    for row in league_rows[:3]:
        top_member=guild.get_member(int(row["user_id"]))
        top.append({"name":row.get("nickname") or (top_member.display_name if top_member else f"Player {row['user_id']}"),"avatar_url":str(top_member.display_avatar.with_size(128).url) if top_member else ""})
    joined_date=member.joined_at.strftime("%d.%m.%Y") if member and member.joined_at else "—"
    return {"position":position or "—","joined_date":joined_date,"league_top":top}


async def send_profile(interaction,member=None):
    await interaction.response.defer(ephemeral=True, thinking=True)
    member=member or interaction.user
    p = db.player(interaction.guild_id, member.id)
    recent=[]
    for m in db.recent_matches(interaction.guild_id,50):
        ids=set((m["team_a"]+","+m["team_b"]).split(","))
        if str(member.id) in ids: recent.append(m)
    avatar_url=member.display_avatar.with_size(256).url
    card=await build_profile_card(p,p.get("nickname") or member.display_name,str(avatar_url),recent,build_profile_meta(interaction.guild,p,member))
    view=None
    if member.id==interaction.user.id:
        view=discord.ui.View(timeout=60)
        button=discord.ui.Button(label="Изменить игровой ID",style=discord.ButtonStyle.primary)
        async def cb(i): await i.response.send_modal(GameIdModal())
        button.callback=cb; view.add_item(button)
    await interaction.followup.send(file=discord.File(card,"profile.png"),view=view,ephemeral=True)


async def update_queue(channel):
    """Не показывает очередь; при полном Lobby сразу запускает матч."""
    if not is_lobby(channel) or not league_of(channel): return
    text=ranked_channel_for_lobby(channel)
    if not text: return
    key=channel.id

    old_message_id=queue_messages.pop(key,None)
    if old_message_id:
        try:
            old_message=await text.fetch_message(old_message_id)
            await old_message.delete()
        except discord.HTTPException:
            pass

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
            e=discord.Embed(title="🗺️ РАСПИК КАРТ",description=f"Команды сформированы. Капитаны по очереди исключают карты. На ход даётся **{MAP_VETO_TIMEOUT} секунд**. Если капитан не отвечает, бот автоматически банит случайную карту.\n\n**Сейчас банит:** {self.captain.mention}\n**Доступные карты:**\n{available}",color=discord.Color.from_rgb(124,58,237))

        def team_with_elo(team):
            lines=[]
            for member in team:
                if member.bot:
                    lines.append(f"• {member.mention}")
                    continue
                player=db.player(self.lobby.guild.id,member.id)
                elo=int(player.get("points",STARTING_ELO) or STARTING_ELO)
                lines.append(f"• {member.mention} — **{elo} ELO**")
            return "\n".join(lines) or "—"

        e.add_field(name="🛡 CT",value=team_with_elo(self.team_a),inline=True)
        e.add_field(name="💣 T",value=team_with_elo(self.team_b),inline=True)
        if not selected:
            e.add_field(name="⏱️ Таймер",value=f"{MAP_VETO_TIMEOUT} сек.",inline=False)
            e.add_field(name="История банов",value=log,inline=False)
        e.set_footer(text=f"DOMINION MAP VETO • {league_display_name(self.league)} • осталось карт: {len(self.remaining)}")
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
            active_veto_players.pop(self.lobby.id,None)
            await finalize_match(self.lobby,self.text,self.members,self.team_a,self.team_b,self.league,self.host,selected)
            return
        self.turn+=1
        self.rebuild()
        await self.message.edit(embed=self.embed(),view=self)
        self.schedule_timer()


def split_match_teams(guild,members):
    """Балансирует команды по ELO и по возможности никогда не разделяет пати."""
    if len(members)<=1:
        return members[:],[guild.me]

    party_groups={}
    solo_groups=[]
    for member in members:
        party=db.party_for_user(guild.id,member.id)
        if party:
            party_groups.setdefault(int(party["id"]),[]).append(member)
        else:
            solo_groups.append([member])
    groups=list(party_groups.values())+solo_groups
    random.shuffle(groups)

    def group_elo(group):
        return sum(int(db.player(guild.id,member.id).get("points",STARTING_ELO) or STARTING_ELO) for member in group)

    target=len(members)//2
    total_elo=sum(group_elo(group) for group in groups)
    exact=[]
    fallback=[]
    for mask in range(1<<len(groups)):
        selected=[groups[index] for index in range(len(groups)) if mask&(1<<index)]
        size=sum(len(group) for group in selected)
        if size>target:
            continue
        elo=sum(group_elo(group) for group in selected)
        candidate=(abs(total_elo-2*elo),random.random(),mask)
        fallback.append((target-size,*candidate))
        if size==target:
            exact.append(candidate)

    if exact:
        mask=min(exact)[2]
        team_a=[member for index,group in enumerate(groups) if mask&(1<<index) for member in group]
        team_b=[member for index,group in enumerate(groups) if not mask&(1<<index) for member in group]
        return team_a,team_b

    # Редкий случай, когда размеры пати не позволяют собрать ровно 5/5.
    # Сохраняем максимум целых пати и делим только одну группу для заполнения.
    mask=min(fallback)[3] if fallback else 0
    team_a=[member for index,group in enumerate(groups) if mask&(1<<index) for member in group]
    remaining=[member for index,group in enumerate(groups) if not mask&(1<<index) for member in group]
    need=max(0,target-len(team_a))
    team_a.extend(remaining[:need])
    team_b=remaining[need:]
    return team_a,team_b


async def start_match(lobby,text):
    members=live_members(lobby)[:LOBBY_SIZE]
    if not members: return
    a,b=split_match_teams(lobby.guild,members)
    league=league_of(lobby) or "Default"
    host=random.choice(members)
    active_veto.add(lobby.id)
    active_veto_players[lobby.id]={member.id for member in members if not member.bot}
    veto=MapVetoView(lobby,text,members,a,b,league,host)
    try: await veto.start()
    except Exception:
        active_veto.discard(lobby.id)
        active_veto_players.pop(lobby.id,None)
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
    e=discord.Embed(title=f"🎮 Матч #{match_id}",description=f"{LEAGUES[league][0]} Лига **{league_display_name(league)}**\nКарта: **{map_name}**\nФормат: **до 13 раундов**\nХост: {host.mention}\n\n**Комнаты:** {va.mention} · {vb.mention}\nНажми **Получить ID** — бот автоматически покажет Standoff 2 ID хоста, указанный при регистрации.",color=color())
    e.add_field(name="🛡 CT",value="\n".join(f"• {m.mention}" for m in a))
    e.add_field(name="💣 T",value="\n".join(f"• {m.mention}" for m in b))
    view=discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Получить ID",emoji="🆔",style=discord.ButtonStyle.success,custom_id=f"match:getid:{match_id}"))
    def match_card_item(member):
        data=db.player(lobby.guild.id,member.id)
        return {**data,"name":data.get("nickname") or member.display_name,"avatar_url":str(member.display_avatar.with_size(128).url)}
    host_data=db.player(lobby.guild.id,host.id)
    match_image=await asyncio.to_thread(build_match_card,match_id,league,map_name,host_data.get("nickname") or host.display_name,host_data.get("game_id"),[match_card_item(m) for m in a],[match_card_item(m) for m in b])
    e.set_image(url="attachment://dominion-match.png")
    await text.send(content=" ".join(m.mention for m in members),embed=e,view=view,file=discord.File(match_image,filename="dominion-match.png"))
    await send_staff_log(
        lobby.guild,"журнал-матчей","🎮 Создан новый матч",
        f"Матч: **#{match_id}**\nЛига: **{league_display_name(league)}**\nКарта: **{map_name}**\nХост: {host.mention}\nИгроков: **{len(members)}**",
        discord.Color.purple(),
    )
    await update_queue(lobby)


@bot.event
async def setup_hook():
    db.init_db()
    bot.add_view(QueueView()); bot.add_view(RoomPanel()); bot.add_view(ResultSubmitView()); bot.add_view(DashboardView()); bot.add_view(TicketView()); bot.add_view(TicketChannelView()); bot.add_view(RegistrationView()); bot.add_view(StaffControlView()); bot.add_view(LeagueTopView()); bot.add_view(StaffApplicationPanelView())
    if GUILD_ID:
        guild=discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
    else:
        await bot.tree.sync()


async def ensure_special_warn_roles(guild):
    # The destination server owns its role list. Missing warn roles are never auto-created or renamed.
    return 0


async def default_league_role(guild):
    return next((role for role in guild.roles if any(role_name_matches(role.name,alias) for alias in DEFAULT_LEAGUE_ALIASES)),None)


async def give_default_league_to_member(member,reason="DOMINION: Default League для зарегистрированного игрока"):
    if member.bot:
        return False
    saved_profile=bool(db.player(member.guild.id,member.id).get("game_id"))
    if not has_role(member,REGISTERED_ROLE_NAME) and not saved_profile:
        return False
    role=await default_league_role(member.guild)
    if not role or role in member.roles:
        return False
    if role >= member.guild.me.top_role:
        print(f"Default League hierarchy error for {member} ({member.id})",flush=True)
        return False
    try:
        await member.add_roles(role,reason=reason)
        return True
    except (discord.Forbidden,discord.HTTPException) as exc:
        print(f"Default League assignment error for {member} ({member.id}): {exc!r}",flush=True)
        return False


async def give_default_league_to_registered(guild):
    """Загрузить полный список участников и выдать Default League всем зарегистрированным."""
    try:
        await asyncio.wait_for(guild.chunk(cache=True),timeout=30)
    except (asyncio.TimeoutError,discord.HTTPException):
        pass
    default_role=await default_league_role(guild)
    stats={"members":len(guild.members),"registered":0,"already":0,"assigned":0,"failed":0,"hierarchy":False}
    if not default_role:
        return stats
    if default_role >= guild.me.top_role:
        stats["hierarchy"]=True
        return stats
    for member in guild.members:
        if member.bot or not bool(db.player(guild.id,member.id).get("game_id")):
            continue
        stats["registered"]+=1
        if default_role in member.roles:
            stats["already"]+=1
            continue
        try:
            await member.add_roles(default_role,reason="DOMINION FACEIT: массовая синхронизация Default League")
            stats["assigned"]+=1
        except (discord.Forbidden,discord.HTTPException) as exc:
            stats["failed"]+=1
            print(f"Default League sync error for {member} ({member.id}): {exc!r}",flush=True)
    return stats


async def apply_overwrite_if_changed(target,role,**values):
    desired=discord.PermissionOverwrite(**values)
    if target.overwrites_for(role).pair()!=desired.pair():
        await target.set_permissions(role,overwrite=desired,reason="DOMINION FACEIT: приватный доступ лиги")
        return True
    return False


async def apply_league_channel_privacy(guild):
    """Закрыть все каналы лиги от обычных участников и открыть игрокам нужной лиги."""
    registered=find_role(guild,REGISTERED_ROLE_NAME)
    changed=0
    oversight_names=(
        STAFF_ROLES["owner"],STAFF_ROLES["admin"],EXTRA_ROLE_SPECS["developer"][0],
        EXTRA_ROLE_SPECS["director"][0],EXTRA_ROLE_SPECS["head_admin"][0],
    )
    for league_name,(emoji,_) in LEAGUES.items():
        league_key=league_name.lower()
        league_role_name=LEAGUE_ROLES.get(league_key)
        league_role=find_role(guild,league_role_name) if league_role_name else None
        curator_name=STAFF_ROLES.get(f"curator_{league_key}")
        curator=find_role(guild,curator_name) if curator_name else None
        if not league_role:
            continue
        category_name=league_category_name(league_name)
        categories=[category for category in guild.categories if category.name==category_name]
        for category in categories:
            targets=[category,*category.channels]
            for target in targets:
                changed+=await apply_overwrite_if_changed(target,guild.default_role,view_channel=False,connect=False,send_messages=False,use_application_commands=False)
                if registered:
                    changed+=await apply_overwrite_if_changed(target,registered,view_channel=True,connect=False,send_messages=False,read_message_history=True,use_application_commands=False)
                changed+=await apply_overwrite_if_changed(target,league_role,view_channel=True,connect=True,speak=True,send_messages=True,read_message_history=True,use_application_commands=True)
                if curator:
                    changed+=await apply_overwrite_if_changed(target,curator,view_channel=True,connect=True,speak=True,send_messages=True,read_message_history=True,manage_messages=True,move_members=True,mute_members=True,use_application_commands=True)
                for staff_name in oversight_names:
                    staff_role=find_role(guild,staff_name)
                    if staff_role:
                        changed+=await apply_overwrite_if_changed(target,staff_role,view_channel=True,connect=True,speak=True,send_messages=True,read_message_history=True,manage_messages=True,move_members=True,use_application_commands=True)

    # Чаты лиг вне категорий лиг также доступны только соответствующей лиге.
    chat_map={
        "чат-pro-league":"pro",
        "чат-dominion-ascend":"division",
        "чат-dominion-rise":"qualifications",
        "чат-default-league":"default",
    }
    for channel in guild.text_channels:
        normalized=normalized_role_name(channel.name).replace("・","-")
        league_key=next((key for fragment,key in chat_map.items() if fragment in normalized),None)
        if not league_key or (channel.category and channel.category.name=="🎫 TICKETS"):
            continue
        league_role=find_role(guild,LEAGUE_ROLES[league_key])
        if not league_role:
            continue
        changed+=await apply_overwrite_if_changed(channel,guild.default_role,view_channel=False,send_messages=False,read_message_history=False)
        if registered:
            changed+=await apply_overwrite_if_changed(channel,registered,view_channel=False,send_messages=False,read_message_history=False)
        changed+=await apply_overwrite_if_changed(channel,league_role,view_channel=True,send_messages=True,read_message_history=True)
        curator_name=STAFF_ROLES.get(f"curator_{league_key}")
        curator=find_role(guild,curator_name) if curator_name else None
        if curator:
            changed+=await apply_overwrite_if_changed(channel,curator,view_channel=True,send_messages=True,read_message_history=True,manage_messages=True)
    return changed


READONLY_CHANNEL_KEYWORDS=("магазин","топ-сервера","top-server","трансляц","настройка-лобби","история-игр","fpl-news","fpl-новост","новост","news","наказан","правил","регламент")


def is_public_readonly_channel(channel):
    name=normalized_role_name(channel.name).replace("・","-").replace("_","-")
    return any(keyword in name for keyword in READONLY_CHANNEL_KEYWORDS)


async def merge_channel_permissions(target,role,**values):
    overwrite=target.overwrites_for(role)
    before=overwrite.pair()
    for key,value in values.items():
        setattr(overwrite,key,value)
    if overwrite.pair()!=before:
        await target.set_permissions(role,overwrite=overwrite,reason="DOMINION FACEIT: канал только для чтения")
        return True
    return False


PRE_REGISTRATION_PUBLIC_CATEGORIES={
    "📡 DOMINION INFO", "⌨️ DOMINION COMMANDS", "💬 DOMINION COMMUNITY",
    "🆘 DOMINION SUPPORT", "🎧 DOMINION PRIVATE", "📮 DOMINION RESULTS",
}


async def apply_pre_registration_visibility(guild):
    """Before registration only registration and news are visible; Default League unlocks public areas."""
    registered_role=find_role(guild,REGISTERED_ROLE_NAME)
    if not registered_role:
        return 0
    changed=0
    onboarding=discord.utils.get(guild.categories,name="▶️ DOMINION START")
    if onboarding:
        changed+=await apply_overwrite_if_changed(onboarding,guild.default_role,view_channel=True,send_messages=False,connect=False,use_application_commands=False)
        changed+=await apply_overwrite_if_changed(onboarding,registered_role,view_channel=False,send_messages=False,connect=False,use_application_commands=False)
        for channel in onboarding.channels:
            changed+=await apply_overwrite_if_changed(channel,guild.default_role,view_channel=True,send_messages=False,read_message_history=True,use_application_commands=False)
            changed+=await apply_overwrite_if_changed(channel,registered_role,view_channel=False,send_messages=False,read_message_history=False,use_application_commands=False)
    for category in guild.categories:
        if category.name not in PRE_REGISTRATION_PUBLIC_CATEGORIES:
            continue
        changed+=await apply_overwrite_if_changed(category,guild.default_role,view_channel=False,send_messages=False,connect=False,use_application_commands=False)
        changed+=await apply_overwrite_if_changed(category,registered_role,view_channel=True,send_messages=True,connect=True,speak=True,read_message_history=True,use_application_commands=True)
        for channel in category.channels:
            is_news=isinstance(channel,discord.TextChannel) and ("новост" in normalized_role_name(channel.name) or "news" in normalized_role_name(channel.name))
            if is_news:
                changed+=await apply_overwrite_if_changed(channel,guild.default_role,view_channel=True,send_messages=False,read_message_history=True,use_application_commands=False)
                changed+=await apply_overwrite_if_changed(channel,registered_role,view_channel=True,send_messages=False,read_message_history=True,use_application_commands=False)
            elif isinstance(channel,discord.TextChannel):
                changed+=await apply_overwrite_if_changed(channel,guild.default_role,view_channel=False,send_messages=False,read_message_history=False,use_application_commands=False)
                changed+=await apply_overwrite_if_changed(channel,registered_role,view_channel=True,send_messages=True,read_message_history=True,use_application_commands=True)
            elif isinstance(channel,discord.VoiceChannel):
                changed+=await apply_overwrite_if_changed(channel,guild.default_role,view_channel=False,connect=False)
                changed+=await apply_overwrite_if_changed(channel,registered_role,view_channel=True,connect=True,speak=True)
    return changed


async def apply_public_readonly_channels(guild):
    """Публичные служебные каналы: все читают, писать может только старшее руководство."""
    registered=find_role(guild,REGISTERED_ROLE_NAME)
    allowed_writer_names=(
        STAFF_ROLES["owner"],STAFF_ROLES["admin"],
        EXTRA_ROLE_SPECS["head_admin"][0],EXTRA_ROLE_SPECS["developer"][0],
        EXTRA_ROLE_SPECS["director"][0],EXTRA_ROLE_SPECS["pro_lead"][0],
        "head curator","хед куратор",
    )
    allowed_roles=[]
    for role_name in allowed_writer_names:
        role=find_role(guild,role_name)
        if role and role not in allowed_roles:
            allowed_roles.append(role)
    known_staff_names=set(STAFF_ROLES.values()) | {
        EXTRA_ROLE_SPECS[key][0] for key in (
            "developer","director","head_admin","ticket_admin","head_ac","games_admin",
            "anticheat","moderator","content_creator","streamer","pro_lead",
        )
    }
    disallowed_roles=[]
    for role_name in known_staff_names:
        role=find_role(guild,role_name)
        if role and role not in allowed_roles and role not in disallowed_roles:
            disallowed_roles.append(role)
    changed=0
    for channel in guild.text_channels:
        if not is_public_readonly_channel(channel):
            continue
        readonly={
            "send_messages":False,"add_reactions":False,"create_public_threads":False,
            "create_private_threads":False,"send_messages_in_threads":False,
        }
        changed+=await merge_channel_permissions(channel,guild.default_role,**readonly)
        if registered:
            changed+=await merge_channel_permissions(channel,registered,view_channel=True,read_message_history=True,**readonly)
        for role in disallowed_roles:
            changed+=await merge_channel_permissions(channel,role,view_channel=True,read_message_history=True,**readonly)
        changed+=await merge_channel_permissions(channel,guild.me,view_channel=True,read_message_history=True,send_messages=True,embed_links=True,attach_files=True,add_reactions=True,send_messages_in_threads=True)
        for role in allowed_roles:
            changed+=await merge_channel_permissions(channel,role,view_channel=True,read_message_history=True,send_messages=True,add_reactions=True,create_public_threads=True,send_messages_in_threads=True)
    return changed


async def ensure_admin_panel_channel_name(guild):
    """Точечно переименовать старый канал панели без создания копии."""
    old_name="⌨️・команды-штаба"
    new_name="🎛️・панель-админа"
    existing=discord.utils.get(guild.text_channels,name=new_name)
    old_channel=discord.utils.get(guild.text_channels,name=old_name)
    if existing or not old_channel:
        return existing or old_channel
    try:
        await old_channel.edit(name=new_name,reason="DOMINION FACEIT: новое название панели администратора")
    except discord.Forbidden:
        return old_channel
    return old_channel


async def ensure_dominion_league_chats(guild):
    community=discord.utils.get(guild.categories,name="💬 DOMINION COMMUNITY")
    if not community:
        return 0
    roles=await ensure_staff_roles(guild)
    registered=find_role(guild,REGISTERED_ROLE_NAME)
    specs={
        "🔴・чат-pro-league":(("🔴・чат-pro",),"league_pro","curator_pro"),
        "🟣・чат-dominion-ascend":(("🟣・чат-division",),"league_division","curator_division"),
        "🟢・чат-dominion-rise":(("🟡・чат-qualifications","🟢・чат-qualifications"),"league_qualifications","curator_qualifications"),
        "⚪・чат-default-league":(("⚪・чат-default",),"league_default",None),
    }
    changed=0
    for new_name,(old_names,league_key,curator_key) in specs.items():
        channel=discord.utils.get(community.text_channels,name=new_name)
        if not channel:
            old_channel=next((discord.utils.get(community.text_channels,name=name) for name in old_names if discord.utils.get(community.text_channels,name=name)),None)
            if old_channel:
                try: await old_channel.edit(name=new_name,reason="Dominion league chat rebrand"); channel=old_channel; changed+=1
                except discord.HTTPException: channel=old_channel
            else:
                channel=await guild.create_text_channel(new_name,category=community,reason="Dominion league chat")
                changed+=1
        await channel.set_permissions(guild.default_role,view_channel=False,send_messages=False,read_message_history=False)
        if registered:
            await channel.set_permissions(registered,view_channel=False,send_messages=False,read_message_history=False)
        league_role=roles.get(league_key)
        if league_role:
            await channel.set_permissions(league_role,view_channel=True,send_messages=True,read_message_history=True)
        curator=roles.get(curator_key) if curator_key else None
        if curator:
            await channel.set_permissions(curator,view_channel=True,send_messages=True,manage_messages=True,read_message_history=True)
        for key in ("owner","admin","developer","director","head_admin"):
            role=roles.get(key)
            if role: await channel.set_permissions(role,view_channel=True,send_messages=True,manage_messages=True,read_message_history=True)
    return changed


async def migrate_dominion_branding(guild):
    general={
        "▶️ SEOR START":"▶️ DOMINION START","📡 SEOR INFO":"📡 DOMINION INFO","🏠 SEOR COMMUNITY":"🏠 DOMINION COMMUNITY",
        "🔍 SEOR SUPPORT":"🔍 DOMINION SUPPORT","🎧 SEOR PRIVATE":"🎧 DOMINION PRIVATE","📮 SEOR RESULTS":"📮 DOMINION RESULTS",
        "🛡️ SEOR STAFF":"🛡️ DOMINION STAFF","📡 SEOR AUDIT":"📡 DOMINION AUDIT",
    }
    for category in guild.categories:
        target=general.get(category.name)
        if target and not discord.utils.get(guild.categories,name=target):
            try: await category.edit(name=target,reason="Dominion FACEIT rebrand")
            except discord.HTTPException: pass
    for league,(emoji,_) in LEAGUES.items():
        target=league_category_name(league)
        old_names={f"{emoji} SEOR {league.upper()}",f"{emoji} DOMINION {league.upper()}"}
        category=next((c for c in guild.categories if c.name in old_names),None)
        if category and not discord.utils.get(guild.categories,name=target):
            try: await category.edit(name=target,reason="Dominion league rebrand")
            except discord.HTTPException: pass
        category=discord.utils.get(guild.categories,name=target) or category
        if category:
            old_ranked=discord.utils.get(category.text_channels,name="🎮・ranked")
            if old_ranked and not discord.utils.get(category.text_channels,name="ranked"):
                try: await old_ranked.edit(name="ranked",reason="Dominion league channel rebrand")
                except discord.HTTPException: pass
            for voice in category.voice_channels:
                if voice.name.startswith("🔊 Lobby "):
                    try: await voice.edit(name=voice.name.replace("🔊 ","",1),reason="Dominion lobby rebrand")
                    except discord.HTTPException: pass


@bot.event
async def on_ready():
    print(f"{bot.user} ready")
    await bot.change_presence(activity=discord.Game(f"очередь: {LOBBY_SIZE} игроков"))


@bot.event
async def on_message(message):
    if not message.guild or not bot.user or message.author.id==bot.user.id:
        return
    await bot.process_commands(message)


@bot.event
async def on_guild_channel_create(channel):
    category=getattr(channel,"category",None)
    if category and any(category.name==league_category_name(name) for name,(emoji,_) in LEAGUES.items()):
        await apply_league_channel_privacy(channel.guild)
    if isinstance(channel,discord.TextChannel) and is_public_readonly_channel(channel):
        await apply_public_readonly_channels(channel.guild)
    await send_staff_log(channel.guild,"журнал-сервера","➕ Создан канал",f"Канал: {channel.mention}\nТип: **{type(channel).__name__}**",discord.Color.green())


@bot.event
async def on_guild_channel_delete(channel):
    await send_staff_log(channel.guild,"журнал-сервера","➖ Удалён кан��л",f"Название: **{channel.name}**\nID: `{channel.id}`",discord.Color.orange())


@bot.event
async def on_member_join(member):
    if member.bot: return
    await send_staff_log(member.guild,"журнал-участников","📥 Новый участник",f"Участник: {member.mention}\nID: `{member.id}`\nАккаунт создан: <t:{int(member.created_at.timestamp())}:F>",discord.Color.green())
    try: await member.send(embed=registration_embed(member))
    except discord.HTTPException: pass


@bot.event
async def on_member_remove(member):
    if member.bot: return
    await send_staff_log(member.guild,"журнал-участников","📤 Участник покинул сервер",f"Участник: **{member}**\nID: `{member.id}`",discord.Color.orange())


@bot.event
async def on_member_update(before,after):
    if after.bot: return
    if has_role(after,REGISTERED_ROLE_NAME):
        await give_default_league_to_member(after,reason="DOMINION: Default League после получения роли регистрации")
    before_roles={role.id:role for role in before.roles}
    after_roles={role.id:role for role in after.roles}
    added=[role.mention for role_id,role in after_roles.items() if role_id not in before_roles]
    removed=[role.name for role_id,role in before_roles.items() if role_id not in after_roles]
    changes=[]
    if added: changes.append("Выданы роли: "+", ".join(added))
    if removed: changes.append("Сняты роли: "+", ".join(f"**{name}**" for name in removed))
    if before.nick!=after.nick: changes.append(f"Ник: **{before.display_name}** → **{after.display_name}**")
    if before.timed_out_until!=after.timed_out_until:
        changes.append(f"Тайм-аут до: **{after.timed_out_until or 'снят'}**")
    if changes:
        await send_staff_log(after.guild,"журнал-участников","👤 Изменение участника",f"Участник: {after.mention}\n"+"\n".join(changes),discord.Color.blue())


@bot.event
async def on_guild_role_create(role):
    await send_staff_log(role.guild,"журнал-сервера","➕ Создана роль",f"Роль: {role.mention}\nID: `{role.id}`",discord.Color.green())


@bot.event
async def on_guild_role_delete(role):
    await send_staff_log(role.guild,"журнал-сервера","➖ Удалена роль",f"Название: **{role.name}**\nID: `{role.id}`",discord.Color.orange())


@bot.event
async def on_app_command_completion(interaction,command):
    await send_staff_log(
        interaction.guild,"общий-журнал","⌨️ Выполнена команда",
        f"Команда: `/{command.qualified_name}`\nПользователь: {interaction.user.mention}\nКанал: {interaction.channel.mention if interaction.channel else 'неизвестно'}",
        discord.Color.blurple(),
    )


@bot.event
async def on_interaction(interaction):
    if interaction.type != discord.InteractionType.component: return
    cid=interaction.data.get("custom_id","")
    if cid.startswith("staffapp:accept:") or cid.startswith("staffapp:reject:"):
        return await handle_staff_application_review(interaction,cid)
    if cid in {"seor:registration:start","seor:registration:login"}:
        try:
            if has_role(interaction.user,REGISTERED_ROLE_NAME) or bool(db.player(interaction.guild_id,interaction.user.id).get("game_id")):
                message="Ты уже зарегистрирован. Для смены ID используй `/set_game_id` в канале команд." if cid.endswith(":start") else "Ты уже вошёл в профиль DOMINION."
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
        match_id=int(cid.rsplit(":",1)[1]); match_data=guild_match(interaction.guild_id,match_id)
        if not match_data:
            return await interaction.response.send_message("Игры с таким номером нет.",ephemeral=True)
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
        match_data=guild_match(interaction.guild_id,sub["match_id"])
        if not match_data:
            return await interaction.response.send_message("Игры с таким номером нет.",ephemeral=True)
        allowed=can_administer(interaction.user) or curator_league(interaction.user)==str(match_data["league"]).lower()
        if not allowed:
            return await interaction.response.send_message("Подтверждать игру может Admin, Owner или куратор этой лиги.", ephemeral=True)
        await interaction.response.defer()
        approved = cid.startswith("result:approve:")
        if approved:
            if not db.finish_match(sub["match_id"], sub["score_a"], sub["score_b"]):
                return await interaction.followup.send("Матч уже завершён или не найден.", ephemeral=True)
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
                e = discord.Embed(title=f"🎮 Матч #{sub['match_id']}", description=f"Итоговый счёт: **{sub['score_a']}:{sub['score_b']}**\nРезультат проверил: {interaction.user.mention}", color=clr)
                e.set_image(url=sub["screenshot_url"])
                await history.send(embed=e)
        else:
            db.review_submission(submission_id, "rejected", interaction.user.id)
            status, clr = "❌ отклонён", discord.Color.red()
        await send_staff_log(interaction.guild,"журнал-матчей",f"🎮 Проверка матча #{sub['match_id']}",f"Решение: **{status}**\nМодератор: {interaction.user.mention}\nЗаявка: **#{submission_id}**",clr)
        embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed()
        embed.color = clr
        embed.description = (embed.description or "") + f"\n\nСтатус: **{status}**\nПроверил: {interaction.user.mention}"
        await interaction.message.edit(embed=embed, view=None)


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

    # Выход или переход в другой голосовой канал во время пиков карт — timeout на 10 минут.
    if (before.channel and before.channel.id in active_veto
            and member.id in active_veto_players.get(before.channel.id,set())
            and after.channel!=before.channel):
        active_veto_players.get(before.channel.id,set()).discard(member.id)
        try:
            await member.timeout(
                timedelta(minutes=10),
                reason="DOMINION FACEIT: выход из Lobby во время пиков карт",
            )
            try:
                await member.send("Ты получил мут / timeout на **10 минут** за выход из Lobby во время пиков карт.")
            except discord.HTTPException:
                pass
            await send_staff_log(
                member.guild,"общий-журнал","🔇 Мут за выход во время пиков",
                f"Игрок: {member.mention}\nLobby: **{before.channel.name}**\nНаказание: **10 минут**",
                discord.Color.orange(),
            )
        except (discord.Forbidden,discord.HTTPException) as exc:
            print(f"Veto leave timeout error for {member} ({member.id}): {exc!r}",flush=True)

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
    return discord.Embed(title=f"👥 Пати #{party['id']}",description=f"Лига: **{league_display_name(party['league'])}**\nУчастники: **{len(party['members'])}/3**\n\n{members}",color=color())


party_group=app_commands.Group(name="party",description="Управление пати")

@party_group.command(name="create",description="Создать пати в выбранной лиге")
@app_commands.check(command_channel_access)
@app_commands.choices(league=[
    app_commands.Choice(name="Default",value="Default"),
    app_commands.Choice(name="Dominion Rise",value="Qualifications"),
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
    await interaction.response.send_message(content=f"{member.mention}, тебя приглашают в пати **{league_display_name(party['league'])}**.",embed=party_embed(party),view=view)

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
    await interaction.response.send_message("🚪 Ты покинул пати." if result!="not_in_party" else "Ты не состоишь в пати.",ephemeral=True)

bot.tree.add_command(party_group)


@bot.tree.command(name="setup",description="Создать структуру лиг и панели")
@app_commands.default_permissions(administrator=True)
@app_commands.check(command_channel_access)
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction:discord.Interaction):
    await interaction.response.defer(ephemeral=True,thinking=True)
    g=interaction.guild
    try:
        await g.edit(default_notifications=discord.NotificationLevel.only_mentions,reason="DOMINION FACEIT: уведомления сервера только по упоминаниям")
    except discord.Forbidden:
        await interaction.followup.send("Не удалось включить режим уведомлений «Только упоминания»: боту нужно право `Управлять сервером`.",ephemeral=True)
    removed_legacy_roles=0
    for legacy_name in LEGACY_UNUSED_ROLE_NAMES:
        legacy_role=find_role(g,legacy_name)
        if not legacy_role or legacy_role.managed or legacy_role>=g.me.top_role:
            continue
        try:
            await legacy_role.delete(reason="DOMINION /setup: удаление ролей старого сервера")
            removed_legacy_roles+=1
        except discord.HTTPException:
            pass
    try:
        staff_roles=await ensure_staff_roles(g,create_missing=True)
    except discord.Forbidden:
        return await interaction.followup.send("Не удалось создать недостающие роли: боту нужно право `Управлять ролями`.",ephemeral=True)
    registered_role=find_role(g,REGISTERED_ROLE_NAME)
    if not registered_role:
        try:
            registered_role=await g.create_role(name=REGISTERED_ROLE_NAME,reason="DOMINION /setup: обязательная роль регистрации")
        except discord.Forbidden:
            return await interaction.followup.send("Не удалось создать роль `зарегистрирован`: боту нужно право `Управлять ролями`.",ephemeral=True)
    default_role=staff_roles.get("league_default")
    if not default_role:
        return await interaction.followup.send("Не найдена существующая роль `Default League`. Роли сервера не изменены.",ephemeral=True)
    for member in g.members:
        if member.bot: continue
        has_saved_profile=bool(db.player(g.id,member.id).get("game_id"))
        is_registered=has_role(member,REGISTERED_ROLE_NAME) or has_saved_profile
        if not is_registered: continue
        if registered_role not in member.roles:
            try: await member.add_roles(registered_role,reason="DOMINION /setup: восстановление регистрации")
            except discord.Forbidden: pass
        if default_role not in member.roles:
            try: await member.add_roles(default_role,reason="DOMINION: Default League зарегистрированному игроку")
            except discord.Forbidden: pass

    # /setup синхронизирует только структуру, которой управляет бот.
    # По��торонн��е пользовательские категории и каналы не затрагиваются.
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

    onboarding=await category("▶️ DOMINION START")
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
    registration_panel=registration_embed()
    registration_banner=BASE_DIR/"assets"/"registration-banner.png"
    if registration_banner.exists():
        registration_panel.set_image(url="attachment://registration-banner.png")
        await registration_channel.send(embed=registration_panel,view=RegistrationView(),file=discord.File(registration_banner,filename="registration-banner.png"))
    else:
        await registration_channel.send(embed=registration_panel,view=RegistrationView())

    info = await category("📡 DOMINION INFO")
    old_news=discord.utils.get(info.text_channels,name="📣・объявления")
    current_news=discord.utils.get(info.text_channels,name="📣・news")
    if old_news and not current_news:
        try: await old_news.edit(name="📣・news",reason="DOMINION: объявления переименованы в news")
        except discord.HTTPException: pass
    info_names=("📣・news", "📜・регламент", "🛍️・магазин", "📨・новости-лиги", "🧩・настройка-лобби", "📺・трансляции")
    await sync_channels(info, text_names=info_names)
    for channel_name in info_names:
        info_channel=await text(info,channel_name)
        is_news="новост" in normalized_role_name(channel_name) or "news" in normalized_role_name(channel_name)
        await info_channel.set_permissions(g.default_role,view_channel=is_news,send_messages=False,read_message_history=is_news,use_application_commands=False)
        await info_channel.set_permissions(registered_role,view_channel=True,send_messages=False,read_message_history=True,use_application_commands=False)

    start = await category("⌨️ DOMINION COMMANDS")
    await start.set_permissions(g.default_role,view_channel=True,send_messages=True,read_message_history=True,use_application_commands=True)
    await sync_channels(start, text_names=("🤖・команды", "📊・дашборд", "🏆・топ-сервера"))
    commands_channel=await text(start, "🤖・команды")
    await commands_channel.set_permissions(g.default_role,view_channel=True,send_messages=True,read_message_history=True,use_application_commands=True)
    await commands_channel.set_permissions(g.me,view_channel=True,send_messages=True,manage_messages=True)
    owner_member=g.get_member(g.owner_id)
    if owner_member:
        await commands_channel.set_permissions(owner_member,view_channel=True,send_messages=True)
    for role in {role for role in staff_roles.values() if role}:
        await commands_channel.set_permissions(role,view_channel=True,send_messages=True,read_message_history=True)
    async for old_message in commands_channel.history(limit=20):
        if old_message.author == g.me:
            try: await old_message.delete()
            except discord.HTTPException: pass
    commands_embed=discord.Embed(title="⌨️ КОМАНДЫ DOMINION",description="Используй slash-команды только в этом канале.",color=color())
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

    community = await category("💬 DOMINION COMMUNITY")
    community_names=("💭・общий-чат", "🛡️・поиск-клана", "🎯・поиск-игроков", "🔴・чат-pro-league", "🟣・чат-dominion-ascend", "🟢・чат-dominion-rise", "⚪・чат-default-league", "🛠️・чат-кураторов")
    await sync_channels(community, text_names=community_names, voice_names=("🌐 Общий голос",))
    community_channels={channel_name:await text(community,channel_name) for channel_name in community_names}
    protected_chats={
        "🔴・чат-pro-league":("league_pro","curator_pro"),
        "🟣・чат-dominion-ascend":("league_division","curator_division"),
        "🟢・чат-dominion-rise":("league_qualifications","curator_qualifications"),
        "⚪・чат-default-league":("league_default",None),
    }
    for channel_name,(league_key,curator_key) in protected_chats.items():
        channel=community_channels[channel_name]
        await channel.set_permissions(g.default_role,view_channel=False,send_messages=False,read_message_history=False)
        await channel.set_permissions(staff_roles[league_key],view_channel=True,send_messages=True,read_message_history=True)
        if curator_key and staff_roles.get(curator_key):
            await channel.set_permissions(staff_roles[curator_key],view_channel=True,send_messages=True,manage_messages=True,read_message_history=True)
        await channel.set_permissions(staff_roles["owner"],view_channel=True,send_messages=True,manage_messages=True)
        await channel.set_permissions(staff_roles["admin"],view_channel=True,send_messages=True,manage_messages=True)
    curator_chat=community_channels["🛠️・чат-кураторов"]
    await curator_chat.set_permissions(g.default_role,view_channel=False,send_messages=False,read_message_history=False)
    for curator_key in ("curator_qualifications","curator_division","curator_pro"):
        await curator_chat.set_permissions(staff_roles[curator_key],view_channel=True,send_messages=True,read_message_history=True)
    await curator_chat.set_permissions(staff_roles["owner"],view_channel=True,send_messages=True,manage_messages=True)
    await curator_chat.set_permissions(staff_roles["admin"],view_channel=True,send_messages=True,manage_messages=True)
    if not discord.utils.get(community.voice_channels, name="🌐 Общий голос"):
        await g.create_voice_channel("🌐 Общий голос", category=community, user_limit=99)

    support = await category("🆘 DOMINION SUPPORT")
    await sync_channels(support, text_names=("🎫・создать-тикет", "⚠️・наказания"))
    tickets = await text(support, "🎫・создать-тикет")
    await text(support, "⚠️・наказания")
    async for old_message in tickets.history(limit=20):
        if old_message.author==g.me:
            try: await old_message.delete()
            except discord.HTTPException: pass
    e = discord.Embed(title="🎫 ЦЕНТР ОБРАЩЕНИЙ", description="Выбери раздел: нечестная игра, жалоба на игрока, спор по матчу, обращение по персоналу, обжалование наказания или другой вопрос. Бот создаст приватный канал только для нужной группы персонала.", color=color())
    await tickets.send(embed=e, view=TicketView())

    # Порядок блоков лиг сверху вниз: Pro → Ascend → Rise → Default.
    for name in ("Pro","Division","Qualifications","Default"):
        emoji,_=LEAGUES[name]
        cat_name=league_category_name(name)
        pair_count=LEAGUE_LOBBY_COUNTS[name]
        league_categories=sorted(
            [category for category in g.categories if category.name==cat_name],
            key=lambda category: category.position,
        )
        if not league_categories:
            league_categories.append(await g.create_category(cat_name))
        template_category=league_categories[0]

        # Discord всегда группирует текстовые каналы выше голосовых внутри одной
        # категории. Поэтому для вида ranked-1/Lobby 1, ranked-2/Lobby 2 создаём
        # отдельную категорию с тем же названием для каждой пары.
        while len(league_categories)<pair_count:
            new_category=await g.create_category(
                cat_name,
                overwrites=template_category.overwrites,
                position=template_category.position+len(league_categories),
                reason="DOMINION: отдельная категория для пары ranked/Lobby",
            )
            league_categories.append(new_category)

        curator=staff_roles.get(f"curator_{name.lower()}")
        league_role=staff_roles[f"league_{name.lower()}"]
        for pair_category in league_categories[:pair_count]:
            if curator:
                await pair_category.set_permissions(curator,view_channel=True,send_messages=True,manage_messages=True,manage_channels=True,connect=True,move_members=True,mute_members=True)
            await pair_category.set_permissions(g.default_role,view_channel=False,connect=False,send_messages=False,use_application_commands=False)
            await pair_category.set_permissions(registered_role,view_channel=True,connect=False,send_messages=False,read_message_history=True,use_application_commands=False)
            await pair_category.set_permissions(league_role,view_channel=True,connect=True,speak=True,send_messages=True,read_message_history=True,use_application_commands=True)
            await pair_category.set_permissions(staff_roles["owner"],view_channel=True,connect=True,send_messages=True,move_members=True)
            await pair_category.set_permissions(staff_roles["admin"],view_channel=True,connect=True,send_messages=True,move_members=True)

        def all_league_text_channels():
            return [channel for category in league_categories for channel in category.text_channels]

        def all_league_voice_channels():
            return [channel for category in league_categories for channel in category.voice_channels]

        lobby_names=tuple(f"Lobby {i}" for i in range(1,pair_count+1))
        # Во всех отдельных категориях текстовый канал называется одинаково: ranked.
        ranked_candidates=[
            channel for channel in all_league_text_channels()
            if channel.name=="ranked" or re.fullmatch(r"ranked-\\d+",channel.name)
        ]
        used_ranked_ids=set()

        for index,lobby_name in enumerate(lobby_names,1):
            pair_category=league_categories[index-1]
            ranked=(next((channel for channel in pair_category.text_channels if channel.name=="ranked"),None)
                    or next((channel for channel in pair_category.text_channels if channel.name==f"ranked-{index}"),None)
                    or next((channel for channel in ranked_candidates if channel.id not in used_ranked_ids),None)
                    or await g.create_text_channel("ranked",category=pair_category))
            used_ranked_ids.add(ranked.id)
            if ranked.name!="ranked":
                await ranked.edit(name="ranked",reason="DOMINION: единое название ranked без цифр")
            lobby=(discord.utils.get(pair_category.voice_channels,name=lobby_name)
                   or next((channel for channel in all_league_voice_channels() if channel.name==lobby_name),None)
                   or await g.create_voice_channel(lobby_name,category=pair_category,user_limit=LOBBY_SIZE))

            # Переносим существующие каналы без удаления и без переименования.
            if ranked.category!=pair_category:
                await ranked.edit(category=pair_category,reason="DOMINION: ranked и Lobby в одной категории")
            if lobby.category!=pair_category:
                await lobby.edit(category=pair_category,reason="DOMINION: ranked и Lobby в одной категории")

            await ranked.set_permissions(league_role,view_channel=True,send_messages=False,read_message_history=True,use_application_commands=True)
            if lobby.user_limit!=LOBBY_SIZE:
                await lobby.edit(user_limit=LOBBY_SIZE,reason="DOMINION: синхронизация LOBBY_SIZE")
            await lobby.set_permissions(g.default_role,view_channel=False,connect=False)
            await lobby.set_permissions(registered_role,view_channel=True,connect=False)
            await lobby.set_permissions(league_role,view_channel=True,connect=True,speak=True)

            # Очередь больше не показывается: удаляем старые панели очереди бота.
            async for message in ranked.history(limit=50):
                is_queue_panel=(message.author==g.me and message.embeds and message.embeds[0].title.startswith("⚔️ "))
                if is_queue_panel:
                    try: await message.delete()
                    except discord.HTTPException: pass
            queue_messages.pop(lobby.id,None)


        for stale_room in [
            voice for category in league_categories for voice in category.voice_channels
            if voice.name.startswith(("🛡 CT · #","💣 T · #")) and not voice.members
        ]:
            try: await stale_room.delete(reason="DOMINION /setup: удаление пустой комнаты матча")
            except discord.HTTPException: pass

    # Собираем категории в строгом порядке. В каждой категории находится одна
    # пара: ranked-N, затем Lobby N. Каналы и их названия не меняются.
    def pair_category_number(category):
        numbers=[]
        for voice in category.voice_channels:
            number=lobby_number(voice)
            if number:
                numbers.append(number)
        return min(numbers) if numbers else 999

    ordered_pair_categories=[]
    for league_name in ("Pro","Division","Qualifications","Default"):
        league_category_title=league_category_name(league_name)
        matching=sorted(
            [category for category in g.categories if category.name==league_category_title],
            key=lambda category:(pair_category_number(category),category.position),
        )
        required=LEAGUE_LOBBY_COUNTS[league_name]
        ordered_pair_categories.extend(matching[:required])
        # Удаляем только лишние пустые дубликаты категорий; каналы не удаляются.
        for extra_category in matching[required:]:
            if not extra_category.channels:
                try: await extra_category.delete(reason="DOMINION: лишняя пустая категория лиги")
                except discord.HTTPException: pass

    if ordered_pair_categories:
        first_position=min(category.position for category in ordered_pair_categories)
        # Перемещение с конца сохраняет точный итоговый порядок категорий.
        for category_to_move in reversed(ordered_pair_categories):
            try:
                await category_to_move.edit(
                    position=first_position,
                    reason="DOMINION: порядок Pro, Ascend, Rise, Default",
                )
            except discord.HTTPException:
                pass

    private=discord.utils.get(g.categories,name="🎧 DOMINION PRIVATE") or await g.create_category("🎧 DOMINION PRIVATE")
    await sync_channels(private, text_names=("⚙️・управление-комнатой",), voice_names=("➕ Создать комнату DOMINION",), preserve_voice_prefixes=("🏠 Комната ",))
    panel=discord.utils.get(private.text_channels,name="⚙️・управление-комнатой") or await g.create_text_channel("⚙️・управление-комнатой",category=private)
    if not discord.utils.get(private.voice_channels,name="➕ Создать комнату DOMINION"):
        await g.create_voice_channel("➕ Создать комнату DOMINION",category=private)
    if not panel.last_message_id:
        e=discord.Embed(title="🎧 Управление приватной комнатой",description="Зайди в **➕ Создать комнату** — бот создаст твой голосовой канал и перенесёт тебя. Настраивай его кнопками ниже. Комната удалится, когда опустеет.",color=color())
        await panel.send(embed=e,view=RoomPanel())

    results = await category("📮 DOMINION RESULTS")
    await sync_channels(results, text_names=("📤・отправить-результаты", "📚・история-игр"))
    send_results = await text(results, "📤・отправить-результаты")
    await text(results, "📚・история-игр")
    if not send_results.last_message_id:
        e=discord.Embed(title="📌 ОТПРАВКА РЕЗУЛЬТАТА МАТЧА",description="Нажми кнопку, введи ID матча и счёт, затем отправь скриншот итогового экрана игры. Результат попадёт на ручную проверку администрации.",color=color())
        await send_results.send(embed=e,view=ResultSubmitView())

    await gate_registered(info,touch_existing_channels=False)
    for public_category in (start,community,support,private,results):
        await gate_registered(public_category)
    for protected_name in protected_chats:
        await community_channels[protected_name].set_permissions(registered_role,view_channel=False,send_messages=False,read_message_history=False)
    await community_channels["🛠️・чат-кураторов"].set_permissions(registered_role,view_channel=False,send_messages=False,read_message_history=False)

    admin_overwrites={g.default_role:discord.PermissionOverwrite(view_channel=False),g.me:discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_channels=True),staff_roles["owner"]:discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_messages=True),staff_roles["admin"]:discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_messages=True)}
    for staff_key in (
        "developer", "director", "head_admin", "ticket_admin", "head_ac",
        "games_admin", "anticheat", "moderator", "pro_lead",
        "curator_qualifications", "curator_division", "curator_pro",
    ):
        admin_overwrites[staff_roles[staff_key]]=discord.PermissionOverwrite(view_channel=True,send_messages=True,read_message_history=True)
    admin = discord.utils.get(g.categories,name="🛡️ DOMINION STAFF") or await g.create_category("🛡️ DOMINION STAFF",overwrites=admin_overwrites)
    for target,overwrite in admin_overwrites.items(): await admin.set_permissions(target,overwrite=overwrite)
    await ensure_admin_panel_channel_name(g)
    staff_text_names=("💬・штаб-команды","🎛️・панель-админа","🎫・входящие-тикеты","⚠️・центр-санкций","🧾・архив-доказательств","✅・проверка-результатов", "📝・регистрация-игр", "🎛️・управление-матчами", "📋・логи-бота")
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
    staff_commands=staff_channels["🎛️・панель-админа"]
    async for old_message in staff_commands.history(limit=20):
        if old_message.author==g.me:
            try: await old_message.delete()
            except discord.HTTPException: pass
    panel=discord.Embed(title="🎛️ ПАНЕЛЬ АДМИНА",description="Рабочая панель администрации. Все действия выполняются кнопками ниже и записываются в журналы.",color=color())
    panel.add_field(name="⚖️ Модерация",value="`Санкции` — warn, timeout, kick, ban\n`Роли` — выдача и снятие ролей",inline=True)
    panel.add_field(name="🎮 Матчи",value="`Матчи` — информация и завершение\n`Результаты` — каналы проверки",inline=True)
    panel.add_field(name="📡 Аудит и поддержка",value="`Тикеты` — список открытых\n`Закрыть тикет` • `Аудит`",inline=True)
    panel.set_footer(text="DOMINION CYBER • каждое дей��твие проверяет права")
    await staff_commands.send(embed=panel,view=StaffControlView())
    if not review.last_message_id:
        await review.send(embed=discord.Embed(title="🧾 Проверка результатов",description="Сюда поступают скриншоты игроков. Администратор проверяет данные и нажимает **Принять** или **Отклонить**.",color=color()))
    if not registration.last_message_id:
        await registration.send(embed=discord.Embed(title="🤖 АВТО-РЕГИСТРАЦИЯ ИГР",description="Бот автоматически считывает со скриншота счёт, карту и K/D/A/MVP. Модератор сверяет распознанные данные с изображением и нажимает **Принять** или **Отклонить**. Куратор может подтверждать только матчи своей лиги.",color=discord.Color.orange()))

    audit=await category("📡 DOMINION AUDIT")
    for target,overwrite in admin_overwrites.items(): await audit.set_permissions(target,overwrite=overwrite)
    audit_names=("🎫・журнал-тикетов","🆘・журнал-поддержки","🎮・журнал-матчей","👥・журнал-участников","🧱・журнал-сервера","📡・общий-журнал")
    await sync_channels(audit,text_names=audit_names)
    audit_channels={name:await text(audit,name,overwrites=admin_overwrites) for name in audit_names}
    if not audit_channels["📡・общий-журнал"].last_message_id:
        await audit_channels["📡・общий-журнал"].send(embed=discord.Embed(title="📡 DOMINION AUDIT STREAM",description="Системные события, действия бота и служебные записи проекта.",color=discord.Color.dark_purple()))

    await send_staff_log(g,"общий-журнал","✅ Структура DOMINION синхронизирована",f"Запустил: {interaction.user.mention}\nРоли и закрытые разделы обновлены.",discord.Color.green())
    applications_panel=await ensure_staff_application_system(g)
    # Роль `Новости` больше не используется: /setup удаляет её с сервера.
    for obsolete_role in [role for role in g.roles if normalized_role_name(role.name)==normalized_role_name("Новости")]:
        if obsolete_role<g.me.top_role:
            try: await obsolete_role.delete(reason="DOMINION /setup: роль Новости удалена")
            except discord.HTTPException: pass
    await apply_pre_registration_visibility(g)
    await apply_league_channel_privacy(g)
    await apply_public_readonly_channels(g)
    # Requested sidebar order: results and private-room creation at the top; staff at the bottom.
    try:
        await results.edit(position=0,reason="DOMINION /setup: результаты наверх")
        await private.edit(position=1,reason="DOMINION /setup: создание комнат наверх")
        await admin.edit(position=max((category.position for category in g.categories),default=0),reason="DOMINION /setup: staff вниз")
    except discord.HTTPException:
        pass

    await interaction.followup.send("Готово: структура синхронизирована. Создана панель заявок Moderator/Game Support и роль `Новости` удалена и больше не создаётся. Старые тестовые и warn-роли удалены. Без `/setup` бот не создаёт каналы.",ephemeral=True)


@bot.tree.command(name="sync_default_league",description="Выдать Default League всем зарегистрированным")
@app_commands.default_permissions(administrator=True)
@app_commands.check(command_channel_access)
async def sync_default_league(interaction:discord.Interaction):
    if not can_manage_staff(interaction.user) and not can_administer(interaction.user):
        return await interaction.response.send_message("Команда доступна только администрации.",ephemeral=True)
    await interaction.response.defer(ephemeral=True,thinking=True)
    stats=await give_default_league_to_registered(interaction.guild)
    default_role=await default_league_role(interaction.guild)
    if not default_role:
        return await interaction.followup.send("Не найдена роль `Default League`.",ephemeral=True)
    if stats["hierarchy"]:
        return await interaction.followup.send("Discord запрещает выдачу: подними роль бота **выше `Default League`** в настройках ролей сервера, затем повтори команду.",ephemeral=True)
    await interaction.followup.send(
        f"Синхронизация завершена. Загружено участников: **{stats['members']}** · с профилем в базе: **{stats['registered']}** · уже имели Default League: **{stats['already']}** · выдано: **{stats['assigned']}** · ошибок: **{stats['failed']}**.",
        ephemeral=True,
    )


@bot.tree.command(name="league_role",description="Выдать или снять роль лиги по иерархии DOMINION")
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
    await interaction.response.defer(ephemeral=True,thinking=True)
    roles=await ensure_staff_roles(interaction.guild)
    role=roles.get(role_key)
    if not role:
        return await interaction.followup.send("Роль лиги не найдена. Владелец должен один раз выполнить `/setup`.",ephemeral=True)
    if role >= interaction.guild.me.top_role:
        return await interaction.followup.send("Discord блокирует выдачу: владелец сервера должен поднять роль бота выше ролей лиг в настройках ролей.",ephemeral=True)
    try:
        if action.value=="give":
            await member.add_roles(role,reason=f"DOMINION FACEIT /league_role by {interaction.user}")
            text=f"{role.mention} выдана участнику {member.mention}."
        else:
            await member.remove_roles(role,reason=f"DOMINION FACEIT /league_role by {interaction.user}")
            text=f"{role.mention} снята с участника {member.mention}."
    except discord.Forbidden:
        return await interaction.followup.send("Discord не разрешил изменить роль. Проверь право бота `Управлять ролями` и поставь роль бота выше ролей лиг.",ephemeral=True)
    await interaction.followup.send(text,ephemeral=True)


@bot.tree.command(name="roles_setup",description="Создать или восстановить служе��ные роли")
@app_commands.default_permissions(administrator=True)
@app_commands.check(command_channel_access)
async def roles_setup(interaction:discord.Interaction):
    if not can_manage_staff(interaction.user):
        return await interaction.response.send_message("Команда доступна только владельцу сервера или Owner.",ephemeral=True)
    await interaction.response.defer(ephemeral=True,thinking=True)
    try:
        roles=await ensure_staff_roles(interaction.guild,create_missing=True)
    except discord.Forbidden:
        return await interaction.followup.send("Не удалось создать недостающие роли: боту нужно право `Управлять ролями`.",ephemeral=True)
    await interaction.followup.send("Роли готовы: "+", ".join(dict.fromkeys(role.mention for role in roles.values() if role)),ephemeral=True)


@bot.tree.command(name="delete",description="Полный снос каналов Dominion FACEIT")
@app_commands.default_permissions(administrator=True)
@app_commands.describe(confirm="Введи DOMINION DELETE",scope="channels — только каналы; all — каналы и доступные роли")
@app_commands.choices(scope=[app_commands.Choice(name="Только каналы",value="channels"),app_commands.Choice(name="Каналы и роли",value="all")])
async def delete_server(interaction:discord.Interaction,confirm:str,scope:app_commands.Choice[str]):
    if interaction.user.id!=interaction.guild.owner_id:
        return await interaction.response.send_message("Команда доступна только владельцу Discord-сервера.",ephemeral=True)
    if confirm.strip().upper()!="DOMINION DELETE":
        return await interaction.response.send_message("Отменено. Для подтверждения введи точно `DOMINION DELETE`.",ephemeral=True)
    await interaction.response.defer(ephemeral=True,thinking=True)
    deleted_roles=0
    if scope.value=="all":
        for role in sorted(interaction.guild.roles,reverse=True):
            if role.is_default() or role.managed or role>=interaction.guild.me.top_role: continue
            try: await role.delete(reason=f"Dominion full wipe by {interaction.user}"); deleted_roles+=1
            except discord.HTTPException: pass
    await interaction.followup.send(f"Снос запущен. Ролей удалено: **{deleted_roles}**. Сейчас будут удалены все каналы.",ephemeral=True)
    deleted_channels=0
    for channel in list(interaction.guild.channels):
        try: await channel.delete(reason=f"Dominion channel wipe by {interaction.user}"); deleted_channels+=1
        except discord.HTTPException: pass
    print(f"{interaction.guild.name}: wipe completed by {interaction.user.id}; channels={deleted_channels}; roles={deleted_roles}",flush=True)


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
            await member.remove_roles(*removable,reason=f"DOMINION mass role reset by {interaction.user}")
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
            await member.add_roles(*desired,reason=f"DOMINION launch role restore by {interaction.user}")
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
        return await interaction.response.send_message("Команда доступна только владельцу и администрации DOMINION.",ephemeral=True)
    nickname=nickname.strip()
    if not 2 <= len(nickname) <= 32:
        return await interaction.response.send_message("Ник должен содержать от 2 до 32 символов.",ephemeral=True)
    if member.id==interaction.guild.owner_id:
        return await interaction.response.send_message("Discord не разрешает боту менять ник владельца сервера.",ephemeral=True)
    await interaction.response.defer(ephemeral=True,thinking=True)
    try:
        await member.edit(nick=nickname,reason=f"DOMINION /set_nickname by {interaction.user}")
    except discord.Forbidden:
        return await interaction.followup.send("Не удалось изменить ник. Подними роль бота выше роли этого участника и выдай право **Manage Nicknames**.",ephemeral=True)
    except discord.HTTPException:
        return await interaction.followup.send("Discord не принял новый ник. Проверь символы и попробуй ещё раз.",ephemeral=True)
    db.set_nickname(interaction.guild_id,member.id,nickname)
    await send_staff_log(interaction.guild,"общий-журнал","✏️ Изменён ник участника",f"Участник: {member.mention}\nНовый ник: **{nickname}**\nИзменил: {interaction.user.mention}",discord.Color.blue())
    await interaction.followup.send(f"✅ Ник участника {member.mention} изменён на **{nickname}**.",ephemeral=True)


@bot.tree.command(name="admin_result",description="Вручную зарегистрировать результат")
@app_commands.default_permissions(manage_messages=True)
@app_commands.check(command_channel_access)
@app_commands.check(result_admin_access)
async def admin_result(interaction:discord.Interaction,match_id:int,score_a:int,score_b:int):
    if not ((score_a == 13 or score_b == 13) and score_a != score_b and min(score_a,score_b) >= 0):
        return await interaction.response.send_message("Некорректный счёт: одна команда должна иметь 13.",ephemeral=True)
    await interaction.response.defer(ephemeral=True,thinking=True)
    if not db.finish_match(match_id,score_a,score_b):
        return await interaction.followup.send("Матч уже завершён или не найден.",ephemeral=True)
    history=next((c for c in interaction.guild.text_channels if c.name.endswith("история-игр")),None)
    if history:
        await history.send(embed=discord.Embed(title=f"🎮 Матч #{match_id}",description=f"Результат вручную зарегистрирован администрацией: **{score_a}:{score_b}**",color=discord.Color.green()))
    await interaction.followup.send(f"Матч #{match_id} зарегистрирован: {score_a}:{score_b}.",ephemeral=True)


@bot.tree.command(name="matches",description="Показать последние матчи карточкой")
@app_commands.check(command_channel_access)
async def matches_command(interaction:discord.Interaction): await send_recent_matches(interaction)


@bot.tree.command(name="match_info",description="Показать информацию о матче")
@app_commands.check(command_channel_access)
async def match_info(interaction:discord.Interaction,match_id:int):
    m=db.match(match_id)
    if not m: return await interaction.response.send_message("Игры с таким номером нет.",ephemeral=True)
    a=" ".join(f"<@{x}>" for x in m["team_a"].split(",")); b=" ".join(f"<@{x}>" for x in m["team_b"].split(","))
    e=discord.Embed(title=f"🎮 Матч #{match_id}",description=f"Лига: **{league_display_name(m['league'])}**\nКарта: **{m['map']}**\nСтатус: **{m['status']}**\nСчёт: **{m['score_a'] if m['score_a'] is not None else '?'}:{m['score_b'] if m['score_b'] is not None else '?'}**\n\n🛡 CT: {a}\n💣 T: {b}",color=color())
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
    return discord.Embed(title="📗 Стандарт квалификации",description=f"Лига: **{league_display_name(league)}**\nТекущий K/D: **{kd:.2f}**\nСтандарт: **{QUALIFICATION_KD:.2f} K/D**\nОсвобождение: **Division и Pro**\n\n{result}",color=discord.Color.green() if passed else discord.Color.red())


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
    app_commands.Choice(name="Dominion Rise",value="Qualifications"),
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
            message="Команды временно доступны только владельцу и участникам со служебными ролями DOMINION."
    else:
        original=getattr(error,"original",error)
        print(f"Application command error: {type(original).__name__}: {original!r}",flush=True)
        message=f"Ошибка команды: `{type(original).__name__}`. {str(original)[:160] or 'Подробности записаны в Railway Logs.'}"
    if interaction.response.is_done():
        await interaction.followup.send(message,ephemeral=True)
    else:
        await interaction.response.send_message(message,ephemeral=True)

if __name__ == "__main__":
    if not TOKEN: raise SystemExit("DISCORD_TOKEN не задан. Скопируй .env.example в .env")
    bot.run(TOKEN)
