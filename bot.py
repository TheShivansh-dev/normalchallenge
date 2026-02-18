import os,time
import re
import pandas as pd
import asyncio
import logging
import telegram
from collections import defaultdict
from telethon import TelegramClient, events
from telethon.tl.functions.channels import GetFullChannelRequest, EditBannedRequest
from telethon.tl.functions.phone import GetGroupCallRequest
from telethon.tl.types import ChatBannedRights

from telegram import Bot

# ✅ Telethon API Credentials
API_ID = 21993163
API_HASH = "7fce093ad6aaf5508e00a0ce6fdf1d8c"
SESSION_FILE = "session_name.session"
monitor_task = None 
monitor_task2 = None  # Holds the monitoring task

# ✅ Telegram Bot API Token (Use your own bot token here)
BOT_TOKEN = "7506333604:AAE15hSwfje6V7jGQqUx1P6KaGP_9Phxxgo"
EXCEL_FILE_PATH = "allowed_StickerUserID.xlsx"
EOWNER_EXCEL_FILE_PATH  = "owner_ExcelFile.xlsx"
ALLOWED_ADMIN_GROUP = -1002137866227
sticker_tracker = {}
muted_users = set()
GROUP_USERNAME = '@iesp_0401'  # Replace with your group's username
ALLOWED_GROUP_ID = -1002137866227  # Only this group can add channels
TARGET_USER_ID = -1002137866227  # User ID of the person who will receive the file

VC_Log = "vc_log.xlsx"
target_VC_lof_id = -1002359766306
ALLOWED_GROUP_ID = -1001817635995 
# ✅ Excel file for allowed channels
EXCEL_FILE = "allowed_channels.xlsx"

# ✅ Start Telethon client
client = TelegramClient(SESSION_FILE, API_ID, API_HASH)

# ✅ Start Telegram Bot
bot = Bot(token=BOT_TOKEN)

# ✅ Ensure Excel file exists
def ensure_excel_file():
    if not os.path.exists(EXCEL_FILE):
        df = pd.DataFrame({"Channel ID": []})  # Create an empty DataFrame
        df.to_excel(EXCEL_FILE, index=False)
        print("📁 Created new allowed_channels.xlsx file.")

# ✅ Load Allowed Channels
def load_allowed_channels():
    ensure_excel_file()
    df = pd.read_excel(EXCEL_FILE)
    return set(df["Channel ID"].astype(int).tolist()) if not df.empty else set()

ALLOWED_CHANNELS = load_allowed_channels()

# ✅ Extract Channel Username from a Link
def extract_channel_username(text):
    match = re.search(r"https://t\.me/([a-zA-Z0-9_]+)", text)
    return match.group(1) if match else None

# ✅ Save Channel to Excel
def save_channel_to_excel(channel_id):
    global ALLOWED_CHANNELS
    if channel_id in ALLOWED_CHANNELS:
        return False  # Channel already exists

    # ✅ Add the new channel
    ALLOWED_CHANNELS.add(channel_id)
    df = pd.DataFrame({"Channel ID": list(ALLOWED_CHANNELS)})
    df.to_excel(EXCEL_FILE, index=False)

    return True

# ✅ Handles /addchannel command and sends updated Excel file after adding
@client.on(events.NewMessage(pattern=r"/addchannel (.+)"))
async def add_channel(event):
    global log_data
    chat_id = event.chat_id

    if chat_id != ALLOWED_GROUP_ID :
        await bot.send_document(chat_id=target_VC_lof_id, document=open(VC_Log, 'rb'),
                                        caption="📄 Updated VC Log List")
        log_data.clear()
        os.remove(VC_Log)
        await event.reply("❌ This command can only be used in the allowed group.")
        return

    channel_link = event.pattern_match.group(1)
    channel_username = extract_channel_username(channel_link)

    if not channel_username:
       
        await event.reply("❌ Invalid channel link. Example:\n`/addchannel https://t.me/example_channel`")
        return

    try:
        channel_entity = await client.get_entity(channel_username)
        channel_id = channel_entity.id

        if save_channel_to_excel(channel_id):
            await event.reply(f"✅ Channel {channel_username} (ID: {channel_id}) added successfully!")

            # ✅ Send updated file using Telegram Bot API
            if os.path.exists(EXCEL_FILE):
                await bot.send_document(chat_id=TARGET_USER_ID, document=open(EXCEL_FILE, 'rb'),
                                        caption="📄 Updated Allowed Channels List")
            else:
                await bot.send_message(chat_id=TARGET_USER_ID, text="❌ The updated channel list is missing.")

        else:
            await event.reply(f"⚠️ Channel {channel_username} is already in the list.")

    except Exception as e:
        await event.reply(f"❌ Error: {e}")


@client.on(events.NewMessage(pattern=r"/restart"))
async def restart_bot(event):
    global monitor_task  # Ensure we can stop and restart monitoring

    chat_id = event.chat_id
    if chat_id != target_VC_lof_id:
        await event.reply("❌ This command can only be used in the allowed group.")
        return

    await event.reply("🔄 Restarting bot...")

    try:
        # ✅ Stop the monitoring task if it's running
        if monitor_task and not monitor_task.done():
            print("cancelling")
            monitor_task.cancel()  # Properly cancel the task
            try:
                print("cancelling2")
                await monitor_task  # Wait for the task to be cancelled
            except asyncio.CancelledError:
                pass  # Task was canceled successfully
        print("cancelling 3")
        # ✅ Disconnect and reconnect client (restarting process)
        
        await client.connect()
        # ✅ Restart monitoring task
        monitor_task = asyncio.create_task(monitor_vc_and_ban())  # Start a new task

        await event.reply("✅ Bot restarted successfully and VC monitoring resumed!")

    except Exception as e:
        await event.reply(f"❌ Error during restart: {e}")

    # Ensure bot continues running if the task is canceled properly
    await continue_running()

# Ensure the event loop continues running even if monitor_task is cancelled
async def continue_running():
    try:
        while True:
            await asyncio.sleep(10)  # Keeps the event loop alive, no tasks will block
    except Exception as e:
        print(f"⚠️ Error in continue_running: {e}")
        await asyncio.sleep(5)


# ✅ Command to manually download the updated list using Telegram Bot API
@client.on(events.NewMessage(pattern=r"/downloadlist"))
async def download_scores_command(event):
    """Sends the updated allowed_channels.xlsx file using Telegram Bot API."""
    try:
        if os.path.exists(EXCEL_FILE):
            await bot.send_document(chat_id=TARGET_USER_ID, document=open(EXCEL_FILE, 'rb'),
                                    caption="📄 Updated Allowed Channels List")
        else:
            await bot.send_message(chat_id=TARGET_USER_ID, text="❌ The score file is not available.")
    except Exception as e:
        await bot.send_message(chat_id=TARGET_USER_ID, text=f"⚠️ Error sending file: {e}")

# ✅ Monitor VC and Ban Unauthorized Users
user_requests = defaultdict(list)

# Rate limit parameters
MAX_REQUESTS = 5
TIME_WINDOW = 4  # seconds

log_data = []

# Rate limit parameters
MAX_REQUESTS = 5
TIME_WINDOW = 4  # seconds



async def save_log():
    df = pd.DataFrame(log_data, columns=["Username", "User ID", "DateTime", "Action"])
    
    try:
        existing_df = pd.read_excel("vc_log.xlsx")
        df = pd.concat([existing_df, df], ignore_index=True)  # Append new data
    except FileNotFoundError:
        pass  # If the file doesn't exist, create a new one

    df.to_excel("vc_log.xlsx", index=False)

count = 1
async def monitor_vc_and_ban():
    global count
    """Monitors the voice chat and bans unauthorized users/channels who start screen sharing or camera."""
    async with client:
        group = await client.get_entity(GROUP_USERNAME)
        full_chat = await client(GetFullChannelRequest(group))

        if not full_chat.full_chat.call:
            print("❌ No active voice chat found!")
            return

        call_id = full_chat.full_chat.call.id
        print(f"🎙 Active Voice Chat ID: {call_id}")

        while True:
            try:
                global ALLOWED_CHANNELS
                ALLOWED_CHANNELS = load_allowed_channels()

                # ✅ Fetch current VC participants
                group_call = await client(GetGroupCallRequest(call=full_chat.full_chat.call, limit=100))
                participants = group_call.participants
                
                print(f"👥 Total Participants: {len(participants)}")

                current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

                for p in participants:
                    if hasattr(p.peer, 'channel_id'):
                        channel_id = p.peer.channel_id
                        if channel_id in ALLOWED_CHANNELS:
                            print(f"✅ Allowed Channel Joined: {channel_id} (Not Banned)")
                        else:
                            channel = await client.get_entity(channel_id)
                            print(f"🚨 BANNING CHANNEL: {channel.title} (Channel ID: {channel_id})")

                            await client(EditBannedRequest(
                                group,
                                channel,
                                ChatBannedRights(
                                    until_date=None,
                                    view_messages=True,
                                )
                            ))
                            log_data.append([channel.title, channel_id, current_time, "Banned (Unauthorized Channel)"])
                    else:
                        user = await client.get_entity(p.peer)
                        user_id = user.id
                        user_name = f"{user.first_name} {user.last_name or ''}"
                        
                        # Log user joining
                        log_data.append([user_name, user_id, current_time, "Joined VC"])
                        
                        # Rate limiting check
                        user_requests[user_id].append(time.time())
                        user_requests[user_id] = [t for t in user_requests[user_id] if time.time() - t <= TIME_WINDOW]
                        
                        if len(user_requests[user_id]) > MAX_REQUESTS:
                            print(f"🚨 BANNING {user_name} (User ID: {user_id}) for spamming requests!")
                            await client(EditBannedRequest(
                                group,
                                user,
                                ChatBannedRights(until_date=None, view_messages=True)
                            ))
                            log_data.append([user_name, user_id, current_time, "Banned (Spam Requests)"])
                            continue
                        
                        if (p.video or p.presentation):
                            print(f"🚨 BANNING {user_name} (User ID: {user_id}) for enabling camera/screen sharing.")
                            await client(EditBannedRequest(
                                group,
                                user,
                                ChatBannedRights(until_date=None, view_messages=True)
                            ))
                            await bot.send_message(chat_id=target_VC_lof_id, text=f"⚠️ Banned For Sharing Screen or Camera {user_name} {user_id}")
                            log_data.append([user_name, user_id, current_time, "Banned (Camera/Screen Sharing)"])
                        else:
                            print(f"✅ {user_name} is safe (No camera/screen sharing).")

                await save_log()
                log_data.clear()
                count = count +1
                if count>350:
                    asyncio.create_task(vclogsendafter10minute())  # Runs in the background

                await asyncio.sleep(4)

            except Exception as e:
                print(f"⚠️ Error: {e}")
                await asyncio.sleep(5)

async def vclogsendafter10minute():
    global log_data, count
    count =1
    try:
        await bot.send_document(chat_id=target_VC_lof_id, document=open(VC_Log, 'rb'),
                                        caption="📄 Updated VC Log List")
        log_data.clear()
        os.remove(VC_Log)
    except Exception as e:
        print(f"⚠️ Error in sending file: {e}")

@client.on(events.NewMessage(pattern=r"/addsticker (.+)"))
async def add_sticker_user(event):
    chat_id = event.chat_id

    # Reload allowed users
    ALLOWED_USERS = load_allowed_users()

    # Allow only in admin group
    if chat_id != ALLOWED_ADMIN_GROUP:
        await event.reply("❌ This command can only be used in the admin group.")
        return

    try:
        new_user_id = int(event.pattern_match.group(1))

        if new_user_id in ALLOWED_USERS:
            await event.reply("✅ This user is already allowed to send stickers.")
            return

        # Read existing Excel
        df = pd.read_excel(EXCEL_FILE_PATH)

        # Append new user
        new_entry = pd.DataFrame({"User ID": [new_user_id]})
        df = pd.concat([df, new_entry], ignore_index=True)

        # Save file
        df.to_excel(EXCEL_FILE_PATH, index=False)

        await event.reply(f"✅ User {new_user_id} is now allowed to send stickers.")

        # Send updated file
        if os.path.exists(EXCEL_FILE_PATH):
            await bot.send_document(
                chat_id=ALLOWED_ADMIN_GROUP,
                document=open(EXCEL_FILE_PATH, 'rb'),
                caption="📄 Updated Allowed User List"
            )

    except ValueError:
        await event.reply("⚠️ Invalid user ID. Please enter a valid number.")
    except Exception as e:
        await event.reply(f"⚠️ Error adding user: {e}")

def ensure_user_excel():
    if not os.path.exists(EXCEL_FILE_PATH):
        df = pd.DataFrame({"User ID": []})
        df.to_excel(EXCEL_FILE_PATH, index=False)

def load_allowed_users():
    ensure_user_excel()
    df = pd.read_excel(EXCEL_FILE_PATH)
    return set(df["User ID"].astype(int).tolist()) if not df.empty else set()

from telegram import ChatPermissions

@client.on(events.NewMessage(incoming=True))
async def handle_sticker(event):
    if not event.sticker:
        return
    print("sticker")
    user_id = event.sender_id
    chat_id = event.chat_id
    current_time = time.time()

    ALLOWED_USERS = load_allowed_users()

    if user_id in ALLOWED_USERS:
        return

    try:
        await event.delete()
    except Exception as e:
        print(f"Failed to delete sticker: {e}")
        return

    if user_id not in sticker_tracker:
        sticker_tracker[user_id] = []

    sticker_tracker[user_id].append(current_time)

    sticker_tracker[user_id] = [
        t for t in sticker_tracker[user_id]
        if current_time - t <= 3
    ]

    if len(sticker_tracker[user_id]) > 3:
        if user_id not in muted_users:
            try:
                await bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                    permissions=ChatPermissions(
                        can_send_messages=False
                    ),
                    until_date=int(current_time) + 600  # 10 min
                )

                await bot.send_message(
                    chat_id=chat_id,
                    text=f"🚫 User {user_id} muted for 10 minutes due to sticker spam."
                )

                muted_users.add(user_id)
                sticker_tracker[user_id] = []

            except Exception as e:
                print(f"Bot mute failed: {e}")

        return

    # Warning message
    if user_id not in muted_users:
        await bot.send_message(
            chat_id=chat_id,
            text="🚫 Only allowed users can send stickers."
        )


@client.on(events.NewMessage(incoming=True, chats=ALLOWED_GROUP_ID))
async def handle_video(event):
    if not event.video:
        return  # Ignore non-video messages

    user_id = event.sender_id
    chat_id = event.chat_id

    allowed_users = load_allowed_owner()

    if user_id not in allowed_users:
        try:
            await event.delete()

            await bot.send_message(
                    chat_id=ALLOWED_ADMIN_GROUP,
                    text=f"🚫 Not Allowed To Send here, Send in Study Stuff Group then Pin a Link here."
                )
            

        except Exception as e:
            print(f"Error deleting video: {e}")

def load_allowed_owner():
    try:
        if not os.path.exists(EOWNER_EXCEL_FILE_PATH):
            df = pd.DataFrame({"User ID": []})
            df.to_excel(EOWNER_EXCEL_FILE_PATH, index=False)

        df = pd.read_excel(EOWNER_EXCEL_FILE_PATH)
        return set(df["User ID"].dropna().astype(int)) if not df.empty else set()

    except Exception as e:
        print(f"Error loading allowed users: {e}")
        return set()

# ✅ Run the bot
async def main():
    
    global monitor_task,monitor_task2
    await client.start()
    monitor_task = asyncio.create_task(monitor_vc_and_ban())  # Start monitoring VC
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())

