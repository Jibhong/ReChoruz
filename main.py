import asyncio
import os
import discord
from discord import FFmpegPCMAudio, app_commands
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp
from yt_dlp.utils import sanitize_filename
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse



# Load environment variables from .env file
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
# GUILD_ID = int(os.getenv('GUILD_ID', 0))
TIMEOUT = 3

bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

server_list = []

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"[on_ready] Error syncing commands: {e}")
        quit()
    
    bot.loop.create_task(auto_remove_player())

@bot.tree.command(name="play", description="Play music from a link")
async def play(interaction: discord.Interaction, link: str):
    if interaction.guild.id not in [x[1] for x in server_list]:
        newPlayer = MusicPlayer(guild=interaction.guild)
        server_list.append((newPlayer, interaction.guild.id, TIMEOUT))
        server_list.sort(key=lambda x: x[1])
        bot.loop.create_task(newPlayer.download_music())
        bot.loop.create_task(newPlayer.play_music())
        print(f"Created new MusicPlayer for guild {interaction.guild.id}")
        
    musicPlayer = next((x[0] for x in server_list if x[1] == interaction.guild.id), None)
    if musicPlayer is None:
        return
    
    link = await clean_url(link)
    toDownload = musicPlayer.toDownload

    await interaction.response.send_message(f"Playing music from: {link}")
    toDownload.append(link)
    print(f"toDownload list added: {toDownload}")

    vc = interaction.user.voice.channel
    # connect to VC (or move if already connected)
    if interaction.guild.voice_client is None:
        await vc.connect()
    else:
        await interaction.guild.voice_client.move_to(vc)

    await musicPlayer.join_vc(vc)
    # Set playing to True only if not already playing
    musicPlayer.playing = True


@bot.tree.command(name="stop", description="Stop playing music and disconnect")
async def stop(interaction: discord.Interaction):
    if(interaction.guild.id not in [x[1] for x in server_list]):
        await interaction.response.send_message("Not connected to a voice channel.")
        return
    
    musicPlayer = next((x[0] for x in server_list if x[1] == interaction.guild.id), None)
    musicPlayer.playing = False
    musicPlayer.toDownload.clear()
    musicPlayer.toPlay.clear()

    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.stop()
        await interaction.response.send_message("Stopped playing.")
    else:
        await interaction.response.send_message("No song is currently playing.")

@bot.tree.command(name="disconnect", description="Stop playing music and disconnect")
async def disconnect(interaction: discord.Interaction):
    if(interaction.guild.id not in [x[1] for x in server_list]):
        await interaction.response.send_message("Not connected to a voice channel.")
        return
    
    musicPlayer = next((x[0] for x in server_list if x[1] == interaction.guild.id), None)
    musicPlayer.playing = False
    musicPlayer.toDownload.clear()
    musicPlayer.toPlay.clear()

    if interaction.guild.voice_client is not None:
        await interaction.guild.voice_client.disconnect()
    await interaction.response.send_message("Stopped playing and disconnected.")

@bot.tree.command(name="skip", description="Skip the current song")
async def skip(interaction: discord.Interaction):
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.stop()
        await interaction.response.send_message("Skipped the current song.")
    else:
        await interaction.response.send_message("No song is currently playing.")

@bot.tree.command(name="playlist", description="Display the current playlist")
async def playlist(interaction: discord.Interaction):
    if(interaction.guild.id not in [x[1] for x in server_list]):
        await interaction.response.send_message("Not connected to a voice channel.")
        return
    
    musicPlayer = next((x[0] for x in server_list if x[1] == interaction.guild.id), None)

    if len(musicPlayer.toPlay) == 0 and len(musicPlayer.toProcessName) == 0:
        await interaction.response.send_message("The playlist is empty.")
    else:
        playlist_str = f"▶️ **{musicPlayer.playingName}**\n"
        for i in range(len(musicPlayer.toPlay)):
            playlist_str += f"{i+1}. ✅ {musicPlayer.toPlay[i]}\n"
        for i in range(len(musicPlayer.toProcessName)):
            playlist_str += f"{len(musicPlayer.toPlay)+i+1}. ⚙️ {musicPlayer.toProcessName[i]}\n"
        embed = discord.Embed(
            title="🎵 Playlist",
            description="\n".join(
                [playlist_str]
            ),
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed)

class MusicPlayer:

    def __init__(self, guild:discord.Guild):
        self.guild = guild
        self.toDownload = []
        self.toPlay = []
        self.toProcessName = []
        self.playingName = ""
        self.playing = False
        self.stopped = False

    async def download_music(self):
        while True:
            if(self.stopped):
                return
            if not self.toDownload:
                await asyncio.sleep(1)
                continue
            link = self.toDownload.pop(0)
            try:
                title_list,url_list = await get_mp3_list(link)
            except Exception as e:
                print(f"[get_link_title] Error in function: {e}")
                continue
            for title in title_list:
                self.toProcessName.append(title)
            for title, url in zip(title_list, url_list):
                print(f"Processing link: {url} with title: {title}")
                if os.path.exists(os.path.join("./downloaded/", title)):
                    print(f"File already exists for link: {title}")
                    self.toPlay.append(title)
                    self.toProcessName.pop(0)
                    print(f"toPlay list added: {self.toPlay}")
                    continue
                
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': f'./downloaded/{title[:-4]}.%(ext)s',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                    'quiet': True,
                    'noplaylist': True,
                    'overwrites': False,
                }
                try:
                    loop = asyncio.get_running_loop()
                    def _download():
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            ydl.download([url])
                    await loop.run_in_executor(None, _download)
                    print(f"Downloaded: {url}")
                    self.toPlay.append(title)
                    print(f"toPlay list added: {self.toPlay}")
                except Exception as e:
                    print(f"[download_music] Error fetching link {url}: {e}")
                finally:
                    self.toProcessName.pop(0)
                
    async def play_music(self):
        print("play_music task started")
        while True:
            self.playingName = "Nothing..."
            if(self.stopped):
                return
            vc = self.guild.voice_client
            if self.playing == False or len(self.toPlay) == 0 or vc is None:
                await asyncio.sleep(1)
                continue
            print(f"toPlay list: {self.toPlay}")
            filename = self.toPlay.pop(0)
            filepath = os.path.join("./downloaded/", filename)
            if not os.path.exists(filepath):
                print(f"File not found: {filepath}")
                continue
            
            audio_source = None
            try:
                audio_source = FFmpegPCMAudio(filepath)
                vc.play(audio_source)
                print(f"Now playing: {filepath}")
                self.playingName = filename
                while vc.is_playing():
                    if(vc.is_connected() == False):
                        vc.stop()
                        self.playing = False
                        self.toDownload.clear()
                        self.toPlay.clear()
                        break
                    await asyncio.sleep(1)
            except Exception as e:
                print(f"[play_music] Playback error: {e}")

            finally:
                print(f"Finished playing: {filepath}")
                # Make sure FFmpeg process is terminated
                if audio_source:
                    audio_source.cleanup()
    
    async def join_vc(self, vc: discord.VoiceChannel):
        if vc.guild.voice_client is None:
            await vc.connect()
        else:
            await vc.guild.voice_client.move_to(vc)

async def auto_remove_player():
    while True:
        await asyncio.sleep(1)
        for i, (player, guild_id, time_left) in enumerate(server_list):
            if time_left <= 0:
                if player.guild.voice_client is None:
                    player.stopped = True
                    server_list.remove((player, guild_id, time_left))
                    print(f"Removed MusicPlayer for guild {guild_id}")
                    continue
                server_list[i] = (player, guild_id, TIMEOUT)
                continue
            server_list[i] = (player, guild_id, time_left - 1)

async def get_mp3_list(url: str):
    loop = asyncio.get_running_loop()

    ydl_opts = {
        "quiet": True,
        "extract_flat": True,  # don’t download, just list
    }
    def _extract():
        name_list = []
        url_list = []
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            # If it's a playlist loop entries
            if "entries" in info:
                for entry in info["entries"]:
                    name_list.append(sanitize_filename(f"{entry['title']}.mp3"))
                    url_list.append(entry['url'])
            else:  # single video
                if("url" in info):
                    url_list.append(entry['url'])
                else:
                    url_list.append(info['webpage_url'])
                name_list.append(sanitize_filename(f"{info['title']}.mp3"))

        return name_list, url_list
    return await loop.run_in_executor(None, _extract)
    

async def clean_url(url: str) -> str:
    parsed = urlparse(url)

    # only clean if it's a watch URL
    if "watch" in parsed.path:
        query = parse_qs(parsed.query)
        query.pop("list", None)  # remove &list= if present
        new_query = urlencode(query, doseq=True)
        return urlunparse(parsed._replace(query=new_query))
    
    return url

if __name__ == '__main__':
    if TOKEN is None:
        print("DISCORD_TOKEN not found in .env file.")
        quit()

    bot.run(TOKEN)
    

