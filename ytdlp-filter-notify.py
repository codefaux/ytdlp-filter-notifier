#!/usr/bin/env python3

import subprocess
import json
import requests
import os
import sys
import time
import random
import argparse
from datetime import datetime
import prettytable

# === CONFIGURATION ===
HAMMER_DELAY_RANGE = (5, 8)  # Seconds between requests

# === FUNCTIONS ===
def ensure_dir(directory):
    if not os.path.exists(directory):
        os.makedirs(directory)

def load_json(file_path, default):
    if not os.path.exists(file_path):
        return default
    with open(file_path, 'r') as f:
        return json.load(f)

def save_json(file_path, data):
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=2)

def load_config(config_file):
    config = load_json(config_file, {})
    if not config:
        config['telegram_bot_token'] = input("Enter your Telegram bot token: ").strip()
        config['telegram_chat_id'] = input("Enter your Telegram chat ID (@username or ID): ").strip()
        save_json(config_file, config)
    return config

def edit_config(config_file):
    config = {}
    config['telegram_bot_token'] = input("Enter your new Telegram bot token: ").strip()
    config['telegram_chat_id'] = input("Enter your new Telegram chat ID (@username or ID): ").strip()
    save_json(config_file, config)
    print("Configuration updated.")

def load_channels(channels_file, skip_add=False):
    channels = load_json(channels_file, [])
    if (not channels) and (not skip_add):
        print("No channels found. Let's add one.")
        interactive_add_channel(channels_file)
        channels = load_json(channels_file, [])
    return channels

def save_channels(channels_file, channels):
    save_json(channels_file, sorted(channels, key=lambda x: x.get('url', '')))

def load_cache(cache_file):
    return load_json(cache_file, {})

def save_cache(cache_file, cache):
    save_json(cache_file, cache)

def get_latest_videos(channel_url):
    result = subprocess.run([
        "yt-dlp",
        "--flat-playlist",
        "--dump-single-json",
        "--no-warnings",
        "--no-check-certificate",
        channel_url
    ], capture_output=True, text=True)
    if result.returncode != 0:
        print("\033[91myt-dlp error:\033[0m", result.stderr)
        return [], None
    try:
        data = json.loads(result.stdout)
        return data.get('entries', []), data.get('channel')
    except json.JSONDecodeError:
        print("\033[91mFailed to parse yt-dlp output.\033[0m")
        return [], None

def matches_filters(info, criteria):
    title = info.get('title', '').lower()
    description = info.get('description', '').lower()
    duration = info.get('duration', 0)

    includes = criteria.get('title_include', [])
    if includes and not any(word.lower() in title for word in includes):
        return False

    excludes = criteria.get('title_exclude', [])
    if any(word.lower() in title for word in excludes):
        return False

    desc_includes = criteria.get('description_include', [])
    if desc_includes and not any(word.lower() in description for word in desc_includes):
        return False

    desc_excludes = criteria.get('description_exclude', [])
    if any(word.lower() in description for word in desc_excludes):
        return False

    min_length = criteria.get('min_length_seconds', 0)
    if min_length and duration < min_length:
        return False

    max_length = criteria.get('max_length_seconds', 0)
    if max_length and duration > max_length:
        return False

    return True

def send_telegram_message(bot_token, chat_id, text, dry_run=False):
    if dry_run:
        print(f"\033[94m[Dry-Run]\033[0m {text}")
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": False
    }
    response = requests.post(url, json=payload)
    if response.status_code != 200:
        print("\033[91mFailed to send Telegram message:\033[0m", response.text)

def explain_skip_reason(info, criteria):
    title = info.get('title', '').lower()
    description = info.get('description', '').lower()
    duration = info.get('duration', 0)

    includes = criteria.get('title_include', [])
    if includes and not any(word.lower() in title for word in includes):
        return f"Title missing required keywords: {includes}"

    excludes = criteria.get('title_exclude', [])
    if any(word.lower() in title for word in excludes):
        return f"Title contains excluded keywords: {excludes}"

    desc_includes = criteria.get('description_include', [])
    if desc_includes and not any(word.lower() in description for word in desc_includes):
        return f"Description missing required keywords: {desc_includes}"

    desc_excludes = criteria.get('description_exclude', [])
    if any(word.lower() in description for word in desc_excludes):
        return f"Description contains excluded keywords: {desc_excludes}"

    min_length = criteria.get('min_length_seconds', 0)
    if min_length and duration < min_length:
        return f"Duration too short ({duration}s < {min_length}s)"

    max_length = criteria.get('max_length_seconds', 0)
    if max_length and duration > max_length:
        return f"Duration too long ({duration}s > {max_length}s)"

    return "Matched"

def interactive_add_channel(channels_file):
    url = input("Enter the channel URL: ").strip()

    criteria = {}
    while True:
        if input("Filter by title includes? (y/n): ").strip().lower() == 'y':
            includes = input("Enter title keywords (comma separated): ").strip()
            criteria['title_include'] = [word.strip() for word in includes.split(",")] if includes else []

        if input("Filter by title excludes? (y/n): ").strip().lower() == 'y':
            excludes = input("Enter title exclude keywords (comma separated): ").strip()
            criteria['title_exclude'] = [word.strip() for word in excludes.split(",")] if excludes else []

        if input("Filter by description includes? (y/n): ").strip().lower() == 'y':
            desc_includes = input("Enter description keywords (comma separated): ").strip()
            criteria['description_include'] = [word.strip() for word in desc_includes.split(",")] if desc_includes else []

        if input("Filter by description excludes? (y/n): ").strip().lower() == 'y':
            desc_excludes = input("Enter description exclude keywords (comma separated): ").strip()
            criteria['description_exclude'] = [word.strip() for word in desc_excludes.split(",")] if desc_excludes else []

        if input("Set minimum length (seconds)? (y/n): ").strip().lower() == 'y':
            min_length = int(input("Enter minimum length in seconds: ").strip())
            criteria['min_length_seconds'] = min_length

        if input("Set maximum length (seconds)? (y/n): ").strip().lower() == 'y':
            max_length = int(input("Enter maximum length in seconds: ").strip())
            criteria['max_length_seconds'] = max_length

        print("\nFetching recent videos to preview matches...")
        videos, cname = get_latest_videos(url)
        if not videos:
            print("No videos found or error fetching.")
            return

        videos = videos[:15]

        table = prettytable.PrettyTable()
        table.field_names = ["Title", "Duration", "Result"]
        table.max_width["Title"] = 60
        for video in videos:
            reason = explain_skip_reason(video, criteria)
            duration = video.get('duration')
            duration = f"{duration}s" if duration else "N/A"
            title = video.get('title', 'N/A')
            title = "\n".join([title[i:i+60] for i in range(0, len(title), 60)])
            table.add_row([title, duration, reason])

        print("\nRecent videos analysis:")
        print(table)

        confirm = input("Are you happy with these filters? (y to accept, n to edit again, q to cancel): ").strip().lower()
        if confirm == 'y':
            channels = load_channels(channels_file, skip_add=True)
            channels.append({"url": url, "criteria": criteria})
            save_channels(channels_file, channels)
            print("Channel added.")
            return
        elif confirm == 'q':
            print("Canceled.")
            return
        else:
            print("Let's edit the filters again.\n")

def run_monitor(bot_token, chat_id, channels_file, cache_file, dry_run=False, suppress_skip_msgs=False):
    channels = load_channels(channels_file)
    seen_videos = load_cache(cache_file)

    for channel in channels:
        url = channel.get('url')
        criteria = channel.get('criteria', {})
        if not url:
            continue

        print(f"\033[92mChecking channel:\033[0m {url}")
        videos, cname = get_latest_videos(url)
        channel_cache = set(seen_videos.get(url, []))

        for video in videos[:5]:
            video_id = video['id']
            if video_id in channel_cache:
                if not suppress_skip_msgs:
                    print("\033[90mAlready notified for:\033[0m", video_id)
                continue
            if matches_filters(video, criteria):
                message = f"{cname} :: {video['title']}\n\nhttps://www.youtube.com/watch?v={video_id}"
                send_telegram_message(bot_token, chat_id, message, dry_run=dry_run)
                print("\033[92mNotified for:\033[0m", video['title'])
                channel_cache.add(video_id)
            else:
                if not suppress_skip_msgs:
                    print("\033[93mSkipped:\033[0m", video['title'])

        seen_videos[url] = list(channel_cache)
        time.sleep(random.randint(*HAMMER_DELAY_RANGE))

    save_cache(cache_file, seen_videos)

# === MAIN ===
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YouTube channel monitor and Telegram notifier.")
    parser.add_argument("mode", nargs="?", choices=["run", "add", "dry-run", "config"], default="run", help="Operation mode.")
    parser.add_argument("--data-dir", type=str, default=".", help="Directory to store config, channels and cache files.")
    parser.add_argument("--interval-hours", type=float, default=0.0, help="Interval in hours to repeat run mode. Default off.")
    parser.add_argument("--suppress-skip-msgs", action="store_true", help="Suppress skipped/already-seen video messages.")
    args = parser.parse_args()

    data_dir = args.data_dir
    ensure_dir(data_dir)
    config_file = os.path.join(data_dir, "config.json")
    channels_file = os.path.join(data_dir, "channels.json")
    cache_file = os.path.join(data_dir, "seen_videos.json")

    if args.mode == "config":
        edit_config(config_file)
        sys.exit(0)

    config = load_config(config_file)
    bot_token = config['telegram_bot_token']
    chat_id = config['telegram_chat_id']

    if args.mode == "add":
        interactive_add_channel(channels_file)
        sys.exit(0)

    dry_run = args.mode == "dry-run"

    if args.mode in ("run", "dry-run"):
        while True:
            run_monitor(bot_token, chat_id, channels_file, cache_file, dry_run=dry_run, suppress_skip_msgs=args.suppress_skip_msgs)
            if args.interval_hours <= 0:
                break
            print(f"\033[94mSleeping for {args.interval_hours} hours before next scan...\033[0m")
            time.sleep(args.interval_hours * 3600)
