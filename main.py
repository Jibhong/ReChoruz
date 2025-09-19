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
    toPlay = musicPlayer.toPlay

    if len(toPlay) == 0:
        await interaction.response.send_message("The playlist is empty.")
    else:
        playlist_str = "\n".join([f"{i+1}. {os.path.basename(song)}" for i, song in enumerate(toPlay)])
        await interaction.response.send_message(f"Current Playlist:\n{playlist_str}")

class MusicPlayer:

    def __init__(self, guild:discord.Guild):
        self.guild = guild
        self.toDownload = []
        self.toPlay = []
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
                title = await get_link_title(link)
            except Exception as e:
                print(f"[get_link_title] Error in function: {e}")
                continue
            if os.path.exists(title):
                print(f"File already exists for link: {title}")
                self.toPlay.append(title)
                print(f"toPlay list added: {self.toPlay}")
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
                    self.toPlay.append(title)
                    print(f"toPlay list added: {self.toPlay}")
                except Exception as e:
                    print(f"[download_music] Error fetching link {link}: {e}")
                
    async def play_music(self):
        while True:
            if(self.stopped):
                return
            vc = self.guild.voice_client
            if self.playing == False or len(self.toPlay) == 0 or vc is None:
                await asyncio.sleep(1)
                continue
            print(f"toPlay list: {self.toPlay}")
            filepath = self.toPlay.pop(0)
            if not os.path.exists(filepath):
                print(f"File not found: {filepath}")
                return
            
            audio_source = None
            try:
                audio_source = FFmpegPCMAudio(filepath)
                vc.play(audio_source)
                print(f"Now playing: {filepath}")

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
            try:
                info_dict = ydl.extract_info(link, download=False)  # metadata only
                # Get original filename (before postprocessing)
                filename = ydl.prepare_filename(info_dict)
                # Replace extension with postprocessor target (mp3 here)
                final_name = filename.rsplit('.', 1)[0] + ".mp3"
                return final_name
            except Exception as e:
                print(f"[get_link_title] Error fetching link {link}: {e}")
                raise e

if __name__ == '__main__':
    if TOKEN is None:
        print("DISCORD_TOKEN not found in .env file.")
        quit()

    bot.run(TOKEN)
    

