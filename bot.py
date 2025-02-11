import os
import re
import pandas as pd
import asyncio
import logging
import telegram
from telethon import TelegramClient, events
from telethon.tl.functions.channels import GetFullChannelRequest, EditBannedRequest
from telethon.tl.functions.phone import GetGroupCallRequest
from telethon.tl.types import ChatBannedRights
from telegram import Bot

# ✅ Telethon API Credentials
API_ID = 21993163
API_HASH = "7fce093ad6aaf5508e00a0ce6fdf1d8c"
SESSION_FILE = "session_name.session"

# ✅ Telegram Bot API Token (Use your own bot token here)
BOT_TOKEN = "6991746723:AAFEDm_Rub5o3Khw7DSg1eEQSGtiQmrsS7E"

# ✅ Group & User Details
GROUP_USERNAME = '@iesp_0401'  # Replace with your group's username
ALLOWED_GROUP_ID = -1002137866227  # Only this group can add channels
TARGET_USER_ID = -1002137866227  # User ID of the person who will receive the file

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
    chat_id = event.chat_id

    if chat_id != ALLOWED_GROUP_ID:
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
async def monitor_vc_and_ban():
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

                for p in participants:
                    # Check if the participant is a channel
                    if hasattr(p.peer, 'channel_id'):
                        channel_id = p.peer.channel_id
                        if channel_id in ALLOWED_CHANNELS:
                            print(f"✅ Allowed Channel Joined: {channel_id} (Not Banned)")
                        else:
                            channel = await client.get_entity(channel_id)
                            print(f"🚨 BANNING CHANNEL: {channel.title} (Channel ID: {channel_id})")

                            # Ban the channel
                            await client(EditBannedRequest(
                                group,
                                channel,
                                ChatBannedRights(
                                    until_date=None,
                                    view_messages=True,
                                )
                            ))

                    else:
                        user = await client.get_entity(p.peer)
                        user_id = user.id
                        user_name = f"{user.first_name} {user.last_name or ''}"

                        if (p.video or p.presentation):
                            print(f"🚨 BANNING {user_name} (User ID: {user_id}) for enabling camera/screen sharing.")
                            await client(EditBannedRequest(
                                group,
                                user,
                                ChatBannedRights(until_date=None, view_messages=True)
                            ))

                        else:
                            print(f"✅ {user_name} is safe (No camera/screen sharing).")

                await asyncio.sleep(10)

            except Exception as e:
                print(f"⚠️ Error: {e}")
                await asyncio.sleep(5)

# ✅ Run the bot
async def main():
    await client.start()
    await asyncio.gather(client.run_until_disconnected(), monitor_vc_and_ban())

if __name__ == "__main__":
    asyncio.run(main())
