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
intents.message_content = True
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


class DashboardView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Мой профиль", emoji="👤", style=discord.ButtonStyle.primary, custom_id="dashboard:profile")
    async def profile_button(self, interaction, button):
        await send_profile(interaction)

    @discord.ui.button(label="Последние матчи", emoji="🎮", style=discord.ButtonStyle.secondary, custom_id="dashboard:matches")
    async def matches_button(self, interaction, button):
        rows = db.recent_matches(interaction.guild_id, 10)
        text = "\n".join(f"`#{m['id']}` · {m['league']} · {m['map']} · {m['score_a'] if m['score_a'] is not None else '?'}:{m['score_b'] if m['score_b'] is not None else '?'} · {m['status']}" for m in rows) or "Матчей пока нет."
        await interaction.response.send_message(embed=discord.Embed(title="🎮 Последние матчи", description=text, color=color()), ephemeral=True)


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Создать тикет", emoji="🎫", style=discord.ButtonStyle.success, custom_id="ticket:create")
    async def create_ticket(self, interaction, button):
        guild = interaction.guild
        existing = discord.utils.get(guild.text_channels, topic=f"ticket-owner:{interaction.user.id}")
        if existing:
            return await interaction.response.send_message(f"У тебя уже есть тикет: {existing.mention}", ephemeral=True)
        category = discord.utils.get(guild.categories, name="🎫 TICKETS") or await guild.create_category("🎫 TICKETS")
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
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
    await bot.change_presence(activity=discord.Game("очереди 5×5"))


@bot.event
async def on_interaction(interaction):
    if interaction.type != discord.InteractionType.component: return
    cid=interaction.data.get("custom_id","")
    if cid.startswith("match:lobby:"):
        await interaction.response.send_modal(LobbyModal(int(cid.rsplit(":",1)[1])))
    elif cid.startswith("match:result:"):
        await interaction.response.send_modal(ResultSubmitModal(int(cid.rsplit(":",1)[1])))
    elif cid.startswith("result:approve:") or cid.startswith("result:reject:"):
        if not interaction.user.guild_permissions.manage_guild:
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
    league_managed = {f"{emoji} SEOR {name.upper()}": 5 for name, (emoji, _) in LEAGUES.items()}
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
    await sync_channels(start, text_names=("🤖・команды", "📊・панель", "🏆・лидеры"))
    await text(start, "🤖・команды")
    dashboard = await text(start, "📊・панель")
    await text(start, "🏆・лидеры")
    if not dashboard.last_message_id:
        e = discord.Embed(title="🎛 ПАНЕЛЬ УПРАВЛЕНИЯ", description="Всё управление проектом — в одном окне.\n\n📊 Профиль и статистика\n🏆 Рейтинг и место в таблице\n🎮 Последние матчи\n👥 Пати и совместная игра\n⚙️ Игровой аккаунт", color=color())
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
        while len(cats) < 5:
            cats.append(await g.create_category(cat_name))
        for i,cat in enumerate(cats[:5],1):
            await sync_channels(cat, text_names=("🎮・ranked",), voice_names=(f"🔊 Lobby {i}",), preserve_voice_prefixes=("🛡 CT · #", "💣 T · #"))
            ranked=discord.utils.get(cat.text_channels,name="🎮・ranked") or await g.create_text_channel("🎮・ranked",category=cat)
            lobby=discord.utils.get(cat.voice_channels,name=f"🔊 Lobby {i}")
            if not lobby:
                lobby=next((v for v in cat.voice_channels if is_lobby(v)),None) or await g.create_voice_channel(f"🔊 Lobby {i}",category=cat,user_limit=10)
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

    admin_overwrites={g.default_role:discord.PermissionOverwrite(view_channel=False),g.me:discord.PermissionOverwrite(view_channel=True,send_messages=True,manage_channels=True)}
    admin = discord.utils.get(g.categories,name="🛡️ SEOR STAFF") or await g.create_category("🛡️ SEOR STAFF",overwrites=admin_overwrites)
    await sync_channels(admin, text_names=("✅・проверка-результатов", "📝・регистрация-игр", "🎛️・управление-матчами", "📋・логи-бота"))
    review = await text(admin,"✅・проверка-результатов",overwrites=admin_overwrites)
    await text(admin,"📝・регистрация-игр",overwrites=admin_overwrites)
    await text(admin,"🎛️・управление-матчами",overwrites=admin_overwrites)
    await text(admin,"📋・логи-бота",overwrites=admin_overwrites)
    if not review.last_message_id:
        await review.send(embed=discord.Embed(title="🧾 Проверка результатов",description="Сюда поступают скриншоты игроков. Администратор проверяет данные и нажимает **Принять** или **Отклонить**.",color=color()))
    await interaction.followup.send("Готово: структура синхронизирована — лишние управляемые каналы удалены, нужные добавлены. Посторонние категории не затронуты.",ephemeral=True)


@bot.tree.command(name="profile",description="Показать игровой профиль")
async def profile(interaction:discord.Interaction): await send_profile(interaction)


@bot.tree.command(name="set_game_id",description="Сохранить игровой ID")
async def set_game_id(interaction:discord.Interaction): await interaction.response.send_modal(GameIdModal())


@bot.tree.command(name="result",description="Отправить результат матча")
async def result(interaction:discord.Interaction): await interaction.response.send_modal(ResultSubmitModal())


@bot.tree.command(name="admin_result",description="Вручную зарегистрировать результат")
@app_commands.checks.has_permissions(manage_guild=True)
async def admin_result(interaction:discord.Interaction,match_id:int,score_a:int,score_b:int):
    if not ((score_a == 13 or score_b == 13) and score_a != score_b and min(score_a,score_b) >= 0):
        return await interaction.response.send_message("Некорректный счёт: одна команда должна иметь 13.",ephemeral=True)
    if not db.finish_match(match_id,score_a,score_b):
        return await interaction.response.send_message("Матч уже завершён или не найден.",ephemeral=True)
    history=discord.utils.get(interaction.guild.text_channels,name="история-игр")
    if history:
        await history.send(embed=discord.Embed(title=f"🎮 Матч #{match_id}",description=f"Результат вручную зареги��трирован администрацией: **{score_a}:{score_b}**",color=discord.Color.green()))
    await interaction.response.send_message(f"Матч #{match_id} зарегистрирован: {score_a}:{score_b}.",ephemeral=True)


@bot.tree.command(name="match_info",description="Показать информацию о матче")
async def match_info(interaction:discord.Interaction,match_id:int):
    m=db.match(match_id)
    if not m: return await interaction.response.send_message("Матч не найден.",ephemeral=True)
    a=" ".join(f"<@{x}>" for x in m["team_a"].split(",")); b=" ".join(f"<@{x}>" for x in m["team_b"].split(","))
    e=discord.Embed(title=f"🎮 Матч #{match_id}",description=f"Лига: **{m['league']}**\nКарта: **{m['map']}**\nСтатус: **{m['status']}**\nСчёт: **{m['score_a'] if m['score_a'] is not None else '?'}:{m['score_b'] if m['score_b'] is not None else '?'}**\n\n🛡 CT: {a}\n💣 T: {b}",color=color())
    await interaction.response.send_message(embed=e,ephemeral=True)


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
