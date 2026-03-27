<p align="center">
  <img src="assets/logo.png" alt="little-yt-bot logo" width="300" />
</p>

# 🎵 little-yt-bot

A Discord bot that plays YouTube and Spotify audio in voice channels, with queue management, search, and playback controls.

This project exists because no other public bot solves this issue easily enough for me.

## Features

- Play YouTube videos and playlists by URL
- Play Spotify tracks, albums, and playlists (requires Spotify API credentials)
- Search YouTube by name and pick from results with thumbnails
- Queue management
- Playback controls via buttons (pause, skip, stop)
- Auto-disconnect when the voice channel is empty
- No system FFmpeg required

## Requirements

- Python 3.11+
- A Discord bot token
- (Optional) Spotify Developer credentials

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/yourname/little-yt-bot.git
cd little-yt-bot
```

### 2. Create a virtual environment

**macOS / Linux**

```bash
python3 -m venv venv
source venv/bin/activate.fish   # fish shell
source venv/bin/activate        # bash / zsh
```

**Windows**

```bash
python -m venv venv
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

> FFmpeg is downloaded automatically on first run — no system install needed.

### 4. Configure environment

Copy the example file and fill in your values:

```bash
cp .env.example .env
```

```env
DISCORD_TOKEN=your_bot_token_here
GUILD_ID=your_server_id_here

# Optional: Spotify support
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
```

**Getting your Discord token:**

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Create a new application → go to **Bot**
3. Click **Reset Token** and copy it
4. Under **Privileged Gateway Intents**, enable **Message Content Intent**
5. Go to **OAuth2 → URL Generator**, check `bot`, then check `Send Messages`, `Connect`, and `Speak`
6. Open the generated URL and add the bot to your server

**Getting your Guild (server) ID:**

1. In Discord, go to **User Settings → Advanced** and enable **Developer Mode**
2. Right-click your server icon → **Copy Server ID**

**Getting Spotify credentials (optional):**

1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
2. Create an app and copy the **Client ID** and **Client Secret**

## Running the bot

```bash
python bot.py
```

You should see `Logged in as YourBot` in the terminal. Slash commands will appear in Discord instantly (guild sync).

## Commands

| Command           | Description                                               |
| ----------------- | --------------------------------------------------------- |
| `/play <url>`     | Play a YouTube or Spotify URL (video, playlist, or track) |
| `/search <query>` | Search YouTube by name and pick from 5 results            |
| `/pause`          | Pause playback                                            |
| `/resume`         | Resume paused playback                                    |
| `/skip`           | Skip the current track                                    |
| `/stop`           | Stop playback, clear the queue, and disconnect            |
| `/queue`          | Show the current queue                                    |
| `/volume <0-100>` | Set the playback volume                                   |
| `/join`           | Join your voice channel                                   |
| `/leave`          | Disconnect from the voice channel                         |

### Playback buttons

Every **Now Playing** message includes interactive buttons:

| Button             | Action                 |
| ------------------ | ---------------------- |
| ⏸ Pause / ▶ Resume | Toggle pause           |
| ⏭ Skip            | Skip to the next track |
| ⏹ Stop             | Stop and disconnect    |

## Running as a service

### macOS (launchd)

Create a file at `~/Library/LaunchAgents/com.yourname.ytbot.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.yourname.ytbot</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/little-yt-bot/venv/bin/python3</string>
        <string>/path/to/little-yt-bot/bot.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/little-yt-bot</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/path/to/little-yt-bot/bot.log</string>
    <key>StandardErrorPath</key>
    <string>/path/to/little-yt-bot/bot.log</string>
</dict>
</plist>
```

Replace `/path/to/little-yt-bot` with the actual path (run `pwd` inside the folder to get it).

```bash
launchctl load ~/Library/LaunchAgents/com.yourname.ytbot.plist
```

**Useful commands:**

```bash
launchctl start com.yourname.ytbot   # start
launchctl stop com.yourname.ytbot    # stop
launchctl unload ~/Library/LaunchAgents/com.yourname.ytbot.plist  # remove
tail -f /path/to/little-yt-bot/bot.log  # view logs
```

### Windows (NSSM)

[NSSM](https://nssm.cc) (Non-Sucking Service Manager) is the easiest way to run a Python script as a Windows service.

**1. Download NSSM** from [nssm.cc/download](https://nssm.cc/download) and extract it somewhere (e.g. `C:\nssm\`).

**2. Open a terminal as Administrator and run:**

```cmd
C:\nssm\win64\nssm.exe install YTBot
```

A GUI will open. Fill in:

| Field                 | Value                                              |
| --------------------- | -------------------------------------------------- |
| **Path**              | `C:\path\to\little-yt-bot\venv\Scripts\python.exe` |
| **Startup directory** | `C:\path\to\little-yt-bot`                         |
| **Arguments**         | `bot.py`                                           |

Go to the **I/O** tab and set **Output** and **Error** to `C:\path\to\little-yt-bot\bot.log` to capture logs.

Click **Install service**.

**3. Start the service:**

```cmd
C:\nssm\win64\nssm.exe start YTBot
```

The bot will now start automatically on boot and restart itself if it crashes.

**Useful commands:**

```cmd
nssm start YTBot      # start
nssm stop YTBot       # stop
nssm restart YTBot    # restart
nssm remove YTBot     # uninstall service
```

## License

GNU General Public License v3.0 — see [LICENSE](LICENSE) for details.
