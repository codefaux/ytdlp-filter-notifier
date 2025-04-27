# ytdlp-telegram-filter-notify

A lightweight YouTube watcher that monitors channels and sends Telegram messages for new uploads matching user-defined filters.

## Features
- Monitor YouTube channels for new uploads
- Flexible title/description/length filtering
- Sends notifications via Telegram
- Works manually or in Docker

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
   docker pull ghcr.io/your-repo/ytdlp-telegram-filter-notify:latest
   ```
2. Create a persistent data directory and configure:
   ```bash
   mkdir data
   docker run --rm -it -v "$PWD/data":/data ghcr.io/your-repo/ytdlp-telegram-filter-notify config
   ```
3. Add channels:
   ```bash
   docker run --rm -it -v "$PWD/data":/data ghcr.io/your-repo/ytdlp-telegram-filter-notify add
   ```
4. Run continuously:
   ```bash
   docker-compose up
   ```

(See also `docker-compose.yaml`)

## Adding Channels
When you run in `add` mode (`python3 ytdlp-filter-notify.py add` or Docker equivalent), you'll be prompted to:
- Enter the YouTube channel URL
- Optionally set title keywords, exclude keywords, description keywords
- Optionally set minimum/maximum video length

## Notes
- Default data directory is `./` manually, `/data` in Docker
- To reconfigure the Telegram bot, rerun with `config` mode
- Use `--interval-hours` to repeat runs on a timer
- Use `--suppress-skip-msgs` to hide messages about skipped or already-notified videos
- Use `dry-run` mode to simulate notifications without sending

## License
This project is licensed under the Creative Commons Attribution-NonCommercial 4.0 International License (CC BY-NC 4.0).  
See the [LICENSE](./LICENSE) file for details.

