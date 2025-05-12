import discord
import aiohttp
import asyncio
import io
import os
import re
import psutil
import platform
import logging
from discord.ext import commands, tasks
from discord import app_commands, ui
from datetime import datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
import time
import asyncpg

# ---------------------- Import Your DB Helpers ----------------------
from database import create_pool, init_db, get_or_create_user, create_or_update_user, get_global_state, set_global_state, get_highest_count, update_highest_count

# ---------------------- Load environment variables ----------------------
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# ---------------------- Booster Role ID ----------------------
# Load from environment. Example:
EXTRA_BOOSTER_ROLE_ID = int(os.getenv('EXTRA_BOOSTER_ROLE_ID', 1340585194125660211))

# ---------------------- Configuration & Global Variables ----------------------
PING_LIMIT = int(os.getenv('PING_LIMIT'))
TIME_FRAME = int(os.getenv('TIME_FRAME'))
LOG_CHANNEL_ID = int(os.getenv('PING_CHANNEL_LOGGING_ID'))  # For excessive ping alerts
LOGGING_CHANNEL_ID = int(os.getenv('LOGGING_CHANNEL_ID'))    # For message deletion logs
REACTION_LOG_CHANNEL_ID = int(os.getenv('REACTION_LOG_CHANNEL_ID'))  # For reaction logs
counting_log_channel_id = int(os.getenv('COUNT_LOG_CHANNEL_ID'))
bad_counter_role_id = int(os.getenv('BAD_COUNTER_ROLE_ID'))
COUNTDOWN_CHANNEL_ID = int(os.getenv("COUNTDOWN_CHANNEL_ID"))
TARGET_DATE = datetime(2026, 5, 26, 0, 0, 0, tzinfo=timezone.utc)  # Set the target date (26th May 2026)
# ---------------------- Couting Data Variables ----------------------
SAVE_LIMIT = int(os.getenv('SAVE_LIMIT'))
SAVE_COOLDOWN_HOURS = int(os.getenv('SAVE_COOLDOWN_HOURS'))
DECAY_DAYS = int(os.getenv('DECAY_DAYS'))
LOCKOUT_HOURS = int(os.getenv('LOCKOUT_HOURS'))
LOCKOUT_LIMIT = int(os.getenv('LOCKOUT_LIMIT'))

bot_start_time = datetime.now(timezone.utc)
error_log = []

# Intents configuration
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.members = True
intents.reactions = True
client = discord.Client(intents=intents)

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------------- Counting Bot Globals ----------------------
db_pool = None
user_data = {}       # Not strictly necessary if using DB which we are
count_channel_id = None
current_count = 1
last_counter_id = None
ping_logs = {}
media_cache = {}

# ---------------------- Logging Setup ----------------------
logging.basicConfig(level=logging.INFO)

# ---------------------- Helper Functions ----------------------
def current_time():
    return datetime.utcnow()

def get_local_time():
    # Example: UTC+5 offset
    LOCAL_TIMEZONE_OFFSET = timedelta(hours=5)
    return datetime.now(timezone.utc) + LOCAL_TIMEZONE_OFFSET

def get_unix_timestamp():
    return int(get_local_time().timestamp())

def get_bot_uptime():
    now = datetime.now(timezone.utc)
    uptime_duration = now - bot_start_time
    days, remainder = divmod(uptime_duration.total_seconds(), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{int(days)}d {int(hours)}h {int(minutes)}m {int(seconds)}s"

def get_system_info():
    cpu_percent = psutil.cpu_percent(interval=1)
    memory_usage = psutil.virtual_memory().percent
    return cpu_percent, memory_usage

def log_error(error_message):
    error_log.append({"message": error_message, "time": datetime.now(timezone.utc)})

# ---------------------- Booster Logic ----------------------
@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    booster_role = after.guild.get_role(EXTRA_BOOSTER_ROLE_ID)
    if not booster_role:
        return  # Booster role not found, exit

    # Retrieve the muted role if set
    muted_role_id = os.getenv("MUTED_ROLE_ID")
    muted_role = after.guild.get_role(int(muted_role_id)) if muted_role_id else None

    # Check if the member's boosting status has changed
    if before.premium_since is None and after.premium_since is not None:
        # User started boosting: assign booster role if not muted
        if booster_role not in after.roles:
            if muted_role is None or muted_role not in after.roles:
                try:
                    await after.add_roles(booster_role)
                    logging.info(f"Added booster role to {after.display_name}")
                except Exception as e:
                    logging.error(f"Failed to add booster role to {after.display_name}: {e}")
    elif before.premium_since is not None and after.premium_since is None:
        # User stopped boosting: remove booster role
        if booster_role in after.roles:
            try:
                await after.remove_roles(booster_role)
                logging.info(f"Removed booster role from {after.display_name}")
            except Exception as e:
                logging.error(f"Failed to remove booster role from {after.display_name}: {e}")

    # If the member gets muted, remove the booster role
    if muted_role and muted_role in after.roles:
        if booster_role in after.roles:
            try:
                await after.remove_roles(booster_role)
                logging.info(f"Removed booster role from muted member {after.display_name}")
            except Exception as e:
                logging.error(f"Error removing booster role from muted member {after.display_name}: {e}")
    else:
        # If the member is unmuted and still boosting, re-add the booster role if missing
        if after.premium_since is not None and booster_role not in after.roles:
            try:
                await after.add_roles(booster_role)
                logging.info(f"Re-added booster role to {after.display_name} after unmute")
            except Exception as e:
                logging.error(f"Failed to re-add booster role to {after.display_name}: {e}")


class BoosterRoleView(ui.View):
    """
    A View with a button to manually assign the booster role to
    all current boosters who don't have it yet.
    """
    def __init__(self, boosters, role):
        # Remove timeout to avoid "Unknown interaction" error which is ass after 60s
        super().__init__(timeout=None)
        self.boosters = boosters
        self.role = role

    @discord.ui.button(
    label="Assign Extra Booster Role",
    style=discord.ButtonStyle.primary,
    custom_id="assign_booster"
)
    async def assign_booster(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Immediately defer the interaction (acknowledge it) to avoid expiration.
        await interaction.response.defer(ephemeral=True)
    
        count = 0
        for member in self.boosters:
            if self.role not in member.roles:
                try:
                    await member.add_roles(self.role)
                    count += 1
                except Exception as e:
                    print(f"Error assigning role to {member.display_name}: {e}")
        # Use followup.send since we've already deferred the response.
        await interaction.followup.send(f"Assigned extra booster role to {count} member(s).", ephemeral=True)


@bot.tree.command(name="listboosters", description="List all current server boosters.")
async def listboosters(interaction: discord.Interaction):
    """
    Slash command to list all current boosters. 
    Also includes a button to mass-assign the extra booster role.
    """
    role = interaction.guild.get_role(EXTRA_BOOSTER_ROLE_ID)
    if not role:
        await interaction.response.send_message("Extra Booster role not found. Please check your config.", ephemeral=True)
        return

    # Filter members who are currently boosting
    boosters = [m for m in interaction.guild.members if m.premium_since is not None]

    embed = discord.Embed(
        title="Server Boosters",
        description=f"Total Boosters: {len(boosters)}",
        color=discord.Color.blue()
    )

    if boosters:
        # Only show the first 20 in the embed to avoid hitting character limits
        booster_names = "\n".join(member.display_name for member in boosters[:20])
        embed.add_field(name="Some Boosters:", value=booster_names, inline=False)
    else:
        embed.add_field(name="Boosters", value="No boosters found.", inline=False)

    view = BoosterRoleView(boosters, role)
    await interaction.response.send_message(embed=embed, view=view)

# ---------------------- Counting Bot Commands & Cogs ----------------------
class CountChannelCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.command(name="count_channel", description="Set a channel for the counting game.")
    async def set_count_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        global count_channel_id
        count_channel_id = channel.id
        await set_global_state(db_pool, 'count_channel_id', str(channel.id))
        await interaction.response.send_message(f"Counting channel has been set to {channel.mention}.")

class CollectSaveCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="collectsave", description="Collect your daily save.")
    async def collect_save(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        now = current_time()
        user_row = await get_or_create_user(db_pool, user_id)
        user = dict(user_row)
        time_since_last = now - user["last_collected"]

        if time_since_last < timedelta(hours=SAVE_COOLDOWN_HOURS):
            remaining_time = timedelta(hours=SAVE_COOLDOWN_HOURS) - time_since_last
            hours, remainder = divmod(remaining_time.seconds, 3600)
            minutes = remainder // 60
            await interaction.response.send_message(
                f"You can collect your next save in {hours} hour(s) and {minutes} minute(s)."
            )
            return

        if user["saves"] >= SAVE_LIMIT:
            await interaction.response.send_message(
                f"You already have the maximum number of saves ({SAVE_LIMIT}). Use them wisely!"
            )
            return

        user["saves"] += 1
        user["last_collected"] = now
        await create_or_update_user(
            db_pool, user_id, user["saves"],
            user["last_collected"],
            user["locked_until"],
            user["lockout_count"]
        )
        await interaction.response.send_message(f"Save collected! You now have {user['saves']} save(s).")

@bot.tree.command(name="save", description="Check your current number of saves.")
async def check_saves(interaction: discord.Interaction):
    user_id = interaction.user.id
    user_row = await get_or_create_user(db_pool, user_id)
    user = dict(user_row)
    await interaction.response.send_message(f"{interaction.user.mention}, you currently have {user['saves']} save(s).")

@bot.tree.command(name="count_record", description="Display the highest count achieved in the counting game.")
async def count_record(interaction: discord.Interaction):
    """Display the highest count achieved in the counting game."""
    highest_count = await get_highest_count(db_pool)
    
    embed = discord.Embed(
        title="🏆 Counting Game Record",
        description=f"The highest count achieved in the counting game is **{highest_count}**!",
        color=discord.Color.gold(),
        timestamp=get_local_time()
    )
    
    embed.add_field(
        name="Current Count", 
        value=f"The current count is **{current_count}**", 
        inline=True
    )
    
    embed.add_field(
        name="Progress", 
        value=f"**{round((current_count / highest_count) * 100 if highest_count > 0 else 0)}%** of the record", 
        inline=True
    )
    
    embed.set_footer(text=f"Requested by {interaction.user}", icon_url=interaction.user.avatar.url)
    
    await interaction.response.send_message(embed=embed)

# ---------------------- Counting Logic & Lockouts ----------------------
async def log_bad_counter(member, lockout_count, timestamp):
    log_channel = bot.get_channel(counting_log_channel_id)
    if not log_channel:
        logging.warning("Counting log channel not found. Please check the channel ID.")
        return
    embed = discord.Embed(
        title="Bad Counter Role Assigned",
        description=f"{member.mention} has been locked out {lockout_count} times and was assigned the 'bad counter' role.",
        color=discord.Color.red(),
    )
    embed.add_field(name="User", value=f"{member} ({member.id})", inline=False)
    embed.add_field(name="Timestamp", value=timestamp.strftime("%Y-%m-%d %H:%M:%S UTC"), inline=False)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="Counting Game Log")
    await log_channel.send(embed=embed)

@tasks.loop(hours=24)
async def decay_saves():
    """Decay saves for inactive users."""
    now = current_time()
    async with db_pool.acquire() as connection:
        rows = await connection.fetch('SELECT user_id, last_collected, saves FROM user_data')
        for row in rows:
            time_since_last = now - row['last_collected']
            if time_since_last > timedelta(days=DECAY_DAYS):
                new_saves = max(0, row['saves'] - 1)
                await connection.execute('UPDATE user_data SET saves = $1 WHERE user_id = $2', new_saves, row['user_id'])

# ---------------------- on_message Event ----------------------
@bot.event
async def on_message(message):
    # 1. Cache media attachments (for logging message deletions)
    if message.attachments:
        for attachment in message.attachments:
            asyncio.create_task(cache_media(attachment, message))

    # 2. Skip if message is from a bot
    if message.author.bot:
        return

    # 3. Counting channel logic
    global current_count, last_counter_id
    if count_channel_id is not None and message.channel.id == count_channel_id:
        user_id = message.author.id
        now = current_time()
        user_row = await get_or_create_user(db_pool, user_id)
        user = dict(user_row)

        # Check lockout
        if user["locked_until"] and now < user["locked_until"]:
            try:
                int(message.content)  # Only respond if numeric
                remaining_time = user["locked_until"] - now
                hours, remainder = divmod(remaining_time.seconds, 3600)
                minutes = remainder // 60
                await message.reply(
                    f"{message.author.mention}, you're locked out for another {hours} hour(s) and {minutes} minute(s)."
                )
            except ValueError:
                pass
            await bot.process_commands(message)
            return

        try:
            number = int(message.content)
            # If count is reset and user didn't type 1, warn them
            if current_count == 1 and number != 1:
                await message.add_reaction("⚠️")
                await message.reply(f"{message.author.mention}, the next number is **1**!")
                await bot.process_commands(message)
                return

            # Prevent counting twice in a row
            if last_counter_id == user_id and current_count != 1:
                if user["saves"] > 0:
                    user["saves"] -= 1
                    await create_or_update_user(
                        db_pool, user_id, user["saves"],
                        user["last_collected"],
                        user["locked_until"],
                        user["lockout_count"]
                    )
                    await message.add_reaction("⚠️")
                    await message.reply(
                        f"{message.author.mention}, you can't count twice in a row! You've lost a save. "
                        f"Remaining saves: **{user['saves']}**. The next number is **{current_count}**."
                    )
                else:
                    await message.add_reaction("❌")
                    await message.reply(
                        f"{message.author.mention}, **RUINED** it at **{number}**, Next number is **1**. "
                        f"You can't count twice in a row."
                    )
                    current_count = 1
                    last_counter_id = None
                    await set_global_state(db_pool, 'current_count', str(current_count))
                    await set_global_state(db_pool, 'last_counter_id', "0")
                await bot.process_commands(message)
                return

            # Correct count
            if number == current_count:
                await message.add_reaction("✅")
                current_count += 1
                last_counter_id = user_id
                await set_global_state(db_pool, 'current_count', str(current_count))
                await set_global_state(db_pool, 'last_counter_id', str(last_counter_id))
                
                # Update highest count if needed and add trophy reaction only for new records
                is_new_record = await update_highest_count(db_pool, number)  # Check the current number, not the next count
                if is_new_record:
                    await message.add_reaction("🏆")
            else:
                # Wrong number
                await message.add_reaction("❌")
                if user["saves"] > 0:
                    user["saves"] -= 1
                    await create_or_update_user(
                        db_pool, user_id, user["saves"],
                        user["last_collected"],
                        user["locked_until"],
                        user["lockout_count"]
                    )
                    await message.reply(
                        f"{message.author.mention}, you messed up the counting at **{number}**. "
                        f"You've used a save! Remaining saves: **{user['saves']}**. "
                        f"The next number is **{current_count}**."
                    )
                else:
                    user["locked_until"] = now + timedelta(hours=LOCKOUT_HOURS)
                    user["lockout_count"] += 1
                    current_count = 1
                    last_counter_id = None
                    await create_or_update_user(
                        db_pool, user_id, user["saves"],
                        user["last_collected"],
                        user["locked_until"],
                        user["lockout_count"]
                    )
                    await set_global_state(db_pool, 'current_count', str(current_count))
                    await set_global_state(db_pool, 'last_counter_id', "0")

                    if user["lockout_count"] >= LOCKOUT_LIMIT:
                        guild = message.guild
                        member = guild.get_member(user_id) or await guild.fetch_member(user_id)
                        role = guild.get_role(bad_counter_role_id)
                        if member and role:
                            await member.add_roles(role)
                            await log_bad_counter(member, user["lockout_count"], now)
                        await message.reply(
                            f"{message.author.mention}, you've been locked out {LOCKOUT_LIMIT} times. "
                            "You've been assigned the 'bad counter' role!"
                        )
                    else:
                        await message.reply(
                            f"{message.author.mention}, you messed up the counting at **{number}**. "
                            f"The count has been reset to 1, and you're locked out for the next **{LOCKOUT_HOURS} hours!**"
                        )
        except ValueError:
            pass  # Ignore non-numeric messages

        await bot.process_commands(message)
        return

    # 4. Ping logging / other logic
    if message.mentions:
        for mentioned_user in message.mentions:
            uid = mentioned_user.id
            timestamp = time.time()
            if uid not in ping_logs:
                ping_logs[uid] = []
            ping_logs[uid].append((timestamp, message.author.id))
            # Keep only pings within TIME_FRAME
            ping_logs[uid] = [(t, p) for t, p in ping_logs[uid] if timestamp - t <= TIME_FRAME]

            if len(ping_logs[uid]) >= PING_LIMIT:
                log_channel = bot.get_channel(LOG_CHANNEL_ID)
                if log_channel:
                    pingers = [f"<@{pinger}>" for _, pinger in ping_logs[uid]]
                    embed = discord.Embed(
                        title="🚨 Excessive Ping Alert",
                        description=f"User **{mentioned_user}** received excessive pings!",
                        color=discord.Color.red()
                    )
                    embed.add_field(name="Pinged User", value=f"<@{uid}>", inline=False)
                    embed.add_field(
                        name="Pings Received",
                        value=f"{len(ping_logs[uid])} pings within {TIME_FRAME} seconds",
                        inline=False
                    )
                    embed.add_field(name="Pingers", value=", ".join(pingers), inline=False)
                    embed.set_footer(text=f"Detected by {bot.user.name}", icon_url=bot.user.avatar.url)
                    embed.timestamp = discord.utils.utcnow()
                    await log_channel.send(embed=embed)
                ping_logs[uid] = []

    await bot.process_commands(message)

async def cache_media(attachment, message):
    async with aiohttp.ClientSession() as session:
        async with session.get(attachment.url) as response:
            if response.status == 200:
                media_data = await response.read()
                if message.id not in media_cache:
                    media_cache[message.id] = {
                        "author": message.author,
                        "channel": message.channel,
                        "attachments": [],
                        "content": message.content,
                        "timestamp": message.created_at
                    }
                media_cache[message.id]["attachments"].append({
                    "media_data": media_data,
                    "filename": attachment.filename
                })
            else:
                logging.warning(f"Failed to download attachment {attachment.filename}, status: {response.status}")

@bot.event
async def on_message_delete(message):
    if message.author == bot.user:
        return
    channel = bot.get_channel(LOGGING_CHANNEL_ID)
    if channel:
        truncated_content = (message.content or '[Media deleted]')[:2048]
        embed = discord.Embed(
            title="🗑️ Message Deleted",
            description=(
                f"A message sent by **{message.author}** was deleted in **{message.channel}**\n\n"
                f"**Original Message Content:**\n{truncated_content}"
            ),
            color=discord.Color.red()
        )
        embed.set_author(name=message.author, icon_url=message.author.avatar.url)
        embed.set_footer(text=f"User ID: {message.author.id} | Message ID: {message.id}")
        timestamp = int(message.created_at.timestamp())
        embed.add_field(name="Timestamp", value=f"Sent at <t:{timestamp}:f>", inline=False)
        urls = re.findall(r'(https?://\S+)', message.content or "")
        if urls:
            embed.add_field(name="Links in Message", value="Links have been logged separately.", inline=False)

        cached_message = media_cache.pop(message.id, None)
        image_files = []
        video_files = []
        if cached_message:
            for media_item in cached_message["attachments"]:
                media_file = discord.File(io.BytesIO(media_item["media_data"]), filename=media_item["filename"])
                if media_item["filename"].lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")):
                    image_files.append(media_file)
                elif media_item["filename"].lower().endswith((".mp4", ".mov", ".avi", ".mkv")):
                    video_files.append(media_file)

            await channel.send(embed=embed)
            if image_files:
                await channel.send(files=image_files)
            if video_files:
                await channel.send(files=video_files)
        else:
            await channel.send(embed=embed)

        for url in urls:
            await channel.send(f"🔗 **Link:** {url}")

@bot.tree.command(name="ping", description="Check the bot's status and health")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    uptime = get_bot_uptime()
    total_members = sum(guild.member_count for guild in bot.guilds)
    cpu_usage, memory_usage = get_system_info()
    recent_errors = "\n".join(
        [f"{e['time'].strftime('%Y-%m-%d %H:%M:%S')} - {e['message']}" for e in error_log[-3:]]
    ) if error_log else "No recent errors."

    embed = discord.Embed(
        title="🏓 Pong!",
        description="Detailed Bot Status and Health Information",
        color=discord.Color.blue(),
        timestamp=get_local_time()
    )
    embed.add_field(name="Latency", value=f"{latency}ms", inline=True)
    embed.add_field(name="Uptime", value=uptime, inline=True)
    embed.add_field(name="Servers", value=len(bot.guilds), inline=True)
    embed.add_field(name="Members", value=total_members, inline=True)
    embed.add_field(name="CPU Usage", value=f"{cpu_usage}%", inline=True)
    embed.add_field(name="Memory Usage", value=f"{memory_usage}%", inline=True)
    embed.add_field(name="Clusters", value="1", inline=True)
    embed.add_field(name="Recent Errors", value=recent_errors, inline=False)
    embed.set_footer(text=f"Requested by {interaction.user}", icon_url=interaction.user.avatar.url)
    await interaction.response.send_message(embed=embed)

@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return
    try:
        log_channel = bot.get_channel(REACTION_LOG_CHANNEL_ID)
        if log_channel is None:
            logging.error(f"Reaction log channel not found: {REACTION_LOG_CHANNEL_ID}")
            return
        embed = discord.Embed(title="Reaction Added", color=discord.Color.green(), timestamp=get_local_time())
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="Channel", value=reaction.message.channel.mention, inline=True)
        embed.add_field(name="Message", value=f"[Jump to message]({reaction.message.jump_url})", inline=True)
        embed.add_field(name="Reaction", value=str(reaction.emoji), inline=True)
        embed.add_field(name="Time", value=f"<t:{get_unix_timestamp()}:f>", inline=False)
        await log_channel.send(embed=embed)
        logging.info(f"Logged reaction add by {user} in {reaction.message.channel}")
    except Exception as e:
        logging.error(f"Error in on_reaction_add: {e}")

@bot.event
async def on_reaction_remove(reaction, user):
    if user.bot:
        return
    try:
        log_channel = bot.get_channel(REACTION_LOG_CHANNEL_ID)
        if log_channel is None:
            logging.error(f"Reaction log channel not found: {REACTION_LOG_CHANNEL_ID}")
            return
        embed = discord.Embed(title="Reaction Removed", color=discord.Color.red(), timestamp=get_local_time())
        embed.add_field(name="User", value=user.mention, inline=True)
        embed.add_field(name="Channel", value=reaction.message.channel.mention, inline=True)
        embed.add_field(name="Message", value=f"[Jump to message]({reaction.message.jump_url})", inline=True)
        embed.add_field(name="Reaction", value=str(reaction.emoji), inline=True)
        embed.add_field(name="Time", value=f"<t:{get_unix_timestamp()}:f>", inline=False)
        await log_channel.send(embed=embed)
        logging.info(f"Logged reaction remove by {user} in {reaction.message.channel}")
    except Exception as e:
        logging.error(f"Error in on_reaction_remove: {e}")

def calculate_total_months(start, end):
    return (end.year - start.year) * 12 + end.month - start.month - (1 if end.day < start.day else 0)


# ---------------------- on_ready Event ----------------------
@bot.event
async def on_ready():

    global db_pool, count_channel_id, current_count, last_counter_id

    db_pool = await create_pool()
    await init_db(db_pool)

    # Countdown logic
    channel = bot.get_channel(COUNTDOWN_CHANNEL_ID)

    embed = discord.Embed(title="Lucia GTA 6", description="Counting down to the target date...", color=discord.Color.yellow())

    # Try to fetch existing countdown message
    message_id = await get_global_state(db_pool, 'countdown_message_id')
    message = None

    if message_id:
        try:
            message = await channel.fetch_message(int(message_id))
        except discord.NotFound:
            pass  # Message deleted or invalid ID

    if message is None:
        message = await channel.send(embed=embed)
        await set_global_state(db_pool, 'countdown_message_id', str(message.id))

    async def update_countdown():
        while True:
            now = datetime.now(timezone.utc)

            # Total months left (realistically)
            months = calculate_total_months(now, TARGET_DATE)

            # Days, hours, minutes, seconds still from relativedelta
            delta = relativedelta(TARGET_DATE, now)
            days = delta.days
            hours = delta.hours
            minutes = delta.minutes
            seconds = delta.seconds

            embed.description = (
                f"Time remaining until {TARGET_DATE.strftime('%d %b %Y')}:\n"
                f"**{months}** months, **{days}** days, "
                f"**{hours}** hours, **{minutes}** minutes, **{seconds}** seconds"
            )

            try:
                await message.edit(embed=embed)
            except discord.HTTPException as e:
                logging.warning(f"Failed to edit countdown message: {e}")

            await asyncio.sleep(10)

    bot.loop.create_task(update_countdown())



    # Load counting state from DB
    count_channel_value = await get_global_state(db_pool, 'count_channel_id')
    if count_channel_value is not None:
        count_channel_id = int(count_channel_value)

    current_count_value = await get_global_state(db_pool, 'current_count')
    if current_count_value is not None:
        current_count = int(current_count_value)

    last_counter_value = await get_global_state(db_pool, 'last_counter_id')
    if last_counter_value is not None and last_counter_value != "0":
        last_counter_id = int(last_counter_value)
    else:
        last_counter_id = None

    # Add cogs
    await bot.add_cog(CountChannelCommand(bot))
    await bot.add_cog(CollectSaveCommand(bot))

    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        logging.info(f"Synced {len(synced)} commands.")
    except Exception as e:
        logging.error(f"Failed to sync commands: {e}")
        log_error(f"Failed to sync commands: {e}")

    decay_saves.start()

    logging.info(f"Logged in as {bot.user} (ID: {bot.user.id})")

# ---------------------- Run the Bot ----------------------
bot.run(DISCORD_TOKEN)
