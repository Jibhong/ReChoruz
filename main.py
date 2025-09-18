import asyncio
import os
import discord
from discord import FFmpegPCMAudio, app_commands
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp

# Load environment variables from .env file
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = int(os.getenv('GUILD_ID', 0))

bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

toDownload = []
toPlay = []

playing = False

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    try:
        # synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        # print(f"Synced {len(synced)} slash commands to guild {GUILD_ID}.")

        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")

    except Exception as e:
        print(f"Error syncing commands: {e}")
        quit()

    bot.loop.create_task(download_music())
    bot.loop.create_task(play_music())

@bot.tree.command(name="play", description="Play music from a link")
async def play(interaction: discord.Interaction, link: str):
    global playing
    playing = True
    await interaction.response.send_message(f"Playing music from: {link}")
    toDownload.append(link)
    print(f"toDownload list added: {toDownload}")

    vc = interaction.user.voice.channel
    # connect to VC (or move if already connected)
    if interaction.guild.voice_client is None:
        await vc.connect()
    else:
        await interaction.guild.voice_client.move_to(vc)

    await join_vc(vc)
    while (len(toPlay) == 0):
        await asyncio.sleep(1)
    playing = True

async def download_music():
    while True:
        if not toDownload:
            await asyncio.sleep(1)
            continue
        link = toDownload.pop(0)
        title = await get_link_title(link)
        if os.path.exists(title):
            print(f"File already exists for link: {title}")
            toPlay.append(title)
            print(f"toPlay list added: {toPlay}")
            continue
        
        print(f"Downloading music from: {link}")
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': './downloaded/%(title)s.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
            'noplaylist': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                ydl.download([link])
                print(f"Downloaded: {link}")
                toPlay.append(title)
                print(f"toPlay list added: {toPlay}")
            except Exception as e:
                print(f"Error downloading {link}: {e}")
                
async def play_music():
    global playing
    global toDownload, toPlay
    while True:
        if playing == False or len(toPlay) == 0:
            await asyncio.sleep(1)
            continue
        print(f"toPlay list: {toPlay}")
        filepath = toPlay.pop(0)
        if not os.path.exists(filepath):
            print(f"File not found: {filepath}")
            return
        
        for guild in bot.guilds:
            vc = guild.voice_client
            if vc and vc.is_connected():
                break
        if vc is None:
            await asyncio.sleep(1)
            continue
        
        audio_source = None
        try:
            audio_source = FFmpegPCMAudio(filepath)
            vc.play(audio_source)
            print(f"Now playing: {filepath}")

            while vc.is_playing():
                if(vc.is_connected() == False):
                    vc.stop()
                    playing = False
                    toDownload.clear()
                    toPlay.clear()
                    break
                await asyncio.sleep(1)
            print(f"Finished playing: {filepath}")

        except Exception as e:
            print(f"Playback error: {e}")

        finally:
            # Make sure FFmpeg process is terminated
            if audio_source:
                audio_source.cleanup()
   
async def join_vc(vc: discord.VoiceChannel):
    if vc.guild.voice_client is None:
        await vc.connect()
    else:
        await vc.guild.voice_client.move_to(vc)

async def get_link_title(link: str):
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': './downloaded/%(title)s.%(ext)s',
        'quiet': True,
        'noplaylist': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info_dict = ydl.extract_info(link, download=False)  # metadata only
        # Get original filename (before postprocessing)
        filename = ydl.prepare_filename(info_dict)
        # Replace extension with postprocessor target (mp3 here)
        final_name = filename.rsplit('.', 1)[0] + ".mp3"
        return final_name

if __name__ == '__main__':
    if TOKEN is None:
        print("DISCORD_TOKEN not found in .env file.")
        quit()

    bot.run(TOKEN)
    

