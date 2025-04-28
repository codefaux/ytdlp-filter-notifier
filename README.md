# ytdlp-telegram-filter-notify

A lightweight watcher that monitors channels and sends Telegram messages for new uploads matching user-defined filters.

## Features
- DOES NOT DOWNLOAD VIDEOS. Will not rip videos. Can not pirate/steal videos. JUST a notifier.
- Monitor yt-dlp supported channels for new uploads
-  (only Youtube and Nebula verified, most should work in theory)
- Flexible title/description/length filtering
- Regex processing on URLs (to strip tags / rewrite shorter URLs / etc)
- Sends notifications via Telegram
- Works manually or in Docker
- Interactive add/edit mode with previews, explanations
- Reasonable suggestions will be considered

## Quick Start

### Manual
1. Install requirements:  
   ```bash
   pip install requests
   sudo apt install yt-dlp
   ```
2. Configure:
   ```bash
   python3 ytdlp-filter-notify.py config
   ```
3. Add channels:
   ```bash
   python3 ytdlp-filter-notify.py add
   ```
4. Run:
   ```bash
   python3 ytdlp-filter-notify.py run
   ```

### Docker
1. Pull the image:
   ```bash
   docker pull ghcr.io/codefaux/ytdlp-telegram-filter-notifier:latest
   ```
2. Create a persistent data directory and configure:
   ```bash
   mkdir data
   docker run --rm -it -v "$PWD/data":/data ghcr.io/codefaux/ytdlp-telegram-filter-notifier config
   ```
3. Add channels:
   ```bash
   docker run --rm -it -v "$PWD/data":/data ghcr.io/codefaux/ytdlp-telegram-filter-notifier add
   ```
4. Run continuously:
   ```bash
   docker-compose up
   ```

(See also `docker-compose.yaml`)

## Adding Channels
When you run in `add` mode (`python3 ytdlp-filter-notify.py add` `./ytdlp-filter-notify.py add` or Docker equivalent), you'll be prompted to:
- Enter the channel URL
- Set count of recent videos to pull. Impacts how many videos scanned per interval. Will trigger up to `count` videos on first notification, and always scan most recent `count` videos.
- Optionally set title and description include / exclude keywords
- Optionally set minimum/maximum video length in seconds
- Optionally set regex pattern and replacement for outgoing URL
- - You may manually specify a regex pattern and replacement, configure and use named presets, or import presets from another channel
The script will provide a preview of `count` videos, marked to indicate decisions, with in/out URL display for you to confirm.

## Editing Channels
When you run in `edit` mode (`python3 ytdlp-filter-notify.py edit` `./ytdlp-filter-notify.py edit` or Docker equivalent), prompts and capabilities are similar.
- Select a channel URL
- Adjust count of recent videos, min/max length in seconds
- Adjust keyword lists (set, append, clear)
- Adjust regex (set, clear)

## Editing URL Regex Presets
When you run in 'regex' mode `python3 ytdlp-filter-notify.py edit` `./ytdlp-filter-notify.py edit` or Docker equivalent), the script will allow you to add or edit existing presets.

## Notes
- Default data directory is `./` manually, `/data` in Docker
- To reconfigure the Telegram bot, rerun with `config` mode
- Use `--interval-hours` to repeat runs on a timer
- Use `--suppress-skip-msgs` to hide messages about skipped or already-notified videos
- Use `dry-run` mode to simulate notifications without sending

## License
This project is licensed under the Creative Commons Attribution-NonCommercial 4.0 International License (CC BY-NC 4.0).  
See the [LICENSE](./LICENSE) file for details.

