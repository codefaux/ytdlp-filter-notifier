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
import re

# === CONFIGURATION ===
HAMMER_DELAY_RANGE = (2, 4)  # Seconds between requests

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

def get_latest_videos(channel_url, playlist_end=None):
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-single-json",
        "--no-warnings",
        "--no-check-certificate",
    ]
    if playlist_end:
        cmd.extend(["--playlist-end", str(playlist_end)])
    cmd.append(channel_url)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("\033[91myt-dlp error:\033[0m", result.stderr)
        return [], None
    try:
        data = json.loads(result.stdout)
        return data.get('entries', [])[::-1], data.get('channel') or data.get('title') or data.get('uploader')
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

    retries = 0
    max_retries = 3

    while retries <= max_retries:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            break
        elif response.status_code == 429:
            try:
                retry_after = response.json().get('parameters', {}).get('retry_after')
                if retry_after is None:
                    print("\033[91mRate limit encountered, but retry_after missing. Exiting.\033[0m")
                    sys.exit(1)
                print(f"\033[93mRate limited by Telegram. Retrying after {retry_after} seconds...\033[0m")
                time.sleep(retry_after + 3)
                retries += 1
            except (ValueError, KeyError, json.JSONDecodeError):
                print("\033[91mRate limit encountered, but failed to parse retry_after. Exiting.\033[0m")
                sys.exit(1)
        else:
            print(f"\033[91mFailed to send Telegram message (HTTP {response.status_code}):\033[0m", response.text)
            sys.exit(1)

    if retries > max_retries:
        print("\033[91mExceeded maximum retries. Exiting.\033[0m")
        sys.exit(1)

    time.sleep(2)

def preview_recent_videos(url, criteria, playlist_end, url_regex=None):
    print("\nFetching recent videos to preview matches...")
    videos, cname = get_latest_videos(url, playlist_end=playlist_end)
    if not videos:
        print("No videos found or error fetching.")
        return None, None

    # ANSI color codes
    GREEN = '\033[92m'
    RED = '\033[91m'
    RESET = '\033[0m'

    table = prettytable.PrettyTable()

    if url_regex:
        table.field_names = ["Title", "Duration", "Result", "URL"]
        table.max_width["URL"] =  60
    else:
        table.field_names = ["Title", "Duration", "Result"]


    table.max_width["Title"] = 70
    table.hrules = prettytable.HRuleStyle.ALL

    for video in videos:
        reason = explain_skip_reason(video, criteria)
        duration_val = video.get('duration')
        raw_title = video.get('title', 'N/A')

        video_url = video.get('url', '')
        modified_url = video_url

        if url_regex:
            try:
                pattern, repl = url_regex
                modified_url = re.sub(pattern, repl, video_url)
            except Exception as e:
                modified_url = f"Regex error: {e}"

        if duration_val:
            duration_str = f"{duration_val}s"
        else:
            duration_str = "N/A"

        title_lines = [raw_title[i:i+60] for i in range(0, len(raw_title), 60)]

        if reason == "Matched":
            colored_title_lines = [f"{GREEN}{line}{RESET}" for line in title_lines]
            colored_duration = f"{GREEN}{duration_str}{RESET}"
        else:
            if "title" in reason.lower():
                colored_title_lines = [f"{RED}{line}{RESET}" for line in title_lines]
            else:
                colored_title_lines = title_lines

            if "short" in reason.lower() or "long" in reason.lower():
                colored_duration = f"{RED}{duration_str}{RESET}"
            else:
                colored_duration = duration_str

        color_title = "\n".join(colored_title_lines)

        if url_regex:
            url_display = f"{RED}IN:{RESET}{video_url}\n{GREEN}OUT:{RESET}{modified_url}"
            table.add_row([color_title, colored_duration, reason, url_display])
        else:
            table.add_row([color_title, colored_duration, reason])

    print("\nRecent videos analysis:")
    print(table)
    return videos, cname

def explain_skip_reason(info, criteria):
    reasons = []

    title = info.get('title', '').lower()
    description = info.get('description', '').lower()
    duration = info.get('duration', 0)

    includes = criteria.get('title_include', [])
    if includes and not any(word.lower() in title for word in includes):
        reasons.append(f"Title missing: {includes}")

    excludes = criteria.get('title_exclude', [])
    if any(word.lower() in title for word in excludes):
        reasons.append(f"Title excluded: {excludes}")

    desc_includes = criteria.get('description_include', [])
    if desc_includes and not any(word.lower() in description for word in desc_includes):
        reasons.append(f"Description missing: {desc_includes}")

    desc_excludes = criteria.get('description_exclude', [])
    if any(word.lower() in description for word in desc_excludes):
        reasons.append(f"Description excluded: {desc_excludes}")

    min_length = criteria.get('min_length_seconds', 0)
    if min_length and duration < min_length:
        reasons.append(f"Too short ({duration}s)")

    max_length = criteria.get('max_length_seconds', 0)
    if max_length and duration > max_length:
        reasons.append(f"Too long ({duration}s)")

    return "\n".join(reasons) if reasons else "Matched"

def interactive_add_channel(channels_file):
    # TODO: Handle URL error, handle regex error, mod preview_recent_videos for non-match use (include orig. URL)

    url = input("Enter the channel URL: ").strip()

    criteria = {}
    playlist_end = 25
    url_regex = None

    videos, discarded = preview_recent_videos(url, criteria, playlist_end, url_regex)


    try:
        playlist_end = int(input("How many videos to pull during scan (max)? (e.g., 25): ").strip())
    except ValueError:
        print("Invalid input, defaulting to 25.")

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

        if input("Do you want to set a URL regex replacement? (y/n): ").strip().lower() == 'y':
            while True:
                pattern = input("Enter regex pattern to match in URL: ").strip()
                replacement = input("Enter replacement string: ").strip()
                url_regex = [pattern, replacement]

                if videos:
                    print("\nSample URL previews with your regex:")
                    for sample_video in videos:
                        original_url = sample_video.get('url', '')
                        modified_url = original_url
                        try:
                            modified_url = re.sub(pattern, replacement, original_url)
                        except Exception as e:
                            print(f"\033[91mRegex error:\033[0m {e}")
                        print(f"Original: {original_url}")
                        print(f"Modified: {modified_url}\n")

                confirm = input("Are you happy with this regex? (y to accept, n to re-enter): ").strip().lower()
                if confirm == 'y':
                    break
                else:
                    print("Let's re-enter the regex.\n")

        videos, discarded = preview_recent_videos(url, criteria, playlist_end, url_regex)

        confirm = input("Are you happy with these filters? (y to accept, n to edit again, q to cancel): ").strip().lower()
        if confirm == 'y':
            channels = load_channels(channels_file, skip_add=True)
            channels.append({"url": url, "criteria": criteria, "playlist_end": playlist_end, "url_regex": url_regex})
            save_channels(channels_file, channels)
            print("Channel added.")
            return
        elif confirm == 'q':
            print("Canceled.")
            return
        else:
            print("Let's edit the filters again.\n")

def interactive_edit_channel(channels_file):
    channels = load_channels(channels_file)
    if not channels:
        print("No channels to edit.")
        return

    print("\nCurrent Channels:")
    for idx, chan in enumerate(channels):
        print(f"[{idx}] {chan.get('url', 'UNKNOWN')}")

    try:
        selection = int(input("\nSelect channel to edit (by number): ").strip())
        channel = channels[selection]
    except (ValueError, IndexError):
        print("Invalid selection.")
        return

    url = channel.get('url')
    criteria = channel.get('criteria', {})
    playlist_end = channel.get('playlist_end', 25)
    current_regex = channel.get('url_regex')

    print(f"\nEditing: {url}")

    videos, discarded = preview_recent_videos(url, criteria, playlist_end, current_regex)

    confirm = input("Do you wish to edit these filters? (y to accept, anything else to cancel): ").strip().lower()
    if confirm != 'y':
        return

    while True:
        try:
            new_end = input(f"Current playlist_end={playlist_end}. Enter new value or leave blank to keep: ").strip()
            if new_end:
                channel['playlist_end'] = int(new_end)
                playlist_end = channel['playlist_end']
        except ValueError:
            print("Invalid number. Keeping old playlist_end.")

        fields = [
            ('title_include', list),
            ('title_exclude', list),
            ('description_include', list),
            ('description_exclude', list),
            ('min_length_seconds', int),
            ('max_length_seconds', int),
        ]

        for field, ftype in fields:
            current = criteria.get(field, [] if ftype is list else 0)
            print(f"\nCurrent {field}: {current}")
            action = input("Modify? (s=set, a=append, c=clear, n=none): ").strip().lower()

            if action == 's':
                if ftype is list:
                    entries = input("Enter comma-separated values: ").strip()
                    criteria[field] = [e.strip() for e in entries.split(",") if e.strip()]
                else:
                    try:
                        criteria[field] = int(input("Enter new value: ").strip())
                    except ValueError:
                        print("Invalid input. Skipping.")
            elif action == 'a' and ftype is list:
                entries = input("Enter comma-separated values to append: ").strip()
                criteria.setdefault(field, []).extend([e.strip() for e in entries.split(",") if e.strip()])
            elif action == 'c':
                criteria[field] = [] if ftype is list else 0
            elif action == 'n':
                pass
            else:
                print("Unknown action, skipping.")

        channel['criteria'] = criteria

        print(f"\nCurrent URL regex: {current_regex}")
        action = input("Modify URL regex? (s=set new, c=clear, n=none): ").strip().lower()

        if action == 's':
            while True:
                pattern = input("Enter new regex pattern: ").strip()
                replacement = input("Enter new replacement string: ").strip()
                new_url_regex = [pattern, replacement]

                if videos:
                    print("\nSample URL previews with your regex:")
                    for sample_video in videos:
                        original_url = sample_video.get('url', '')
                        modified_url = original_url
                        try:
                            modified_url = re.sub(pattern, replacement, original_url)
                        except Exception as e:
                            print(f"\033[91mRegex error:\033[0m {e}")
                        print(f"Original: {original_url}")
                        print(f"Modified: {modified_url}\n")

                confirm = input("Are you happy with this regex? (y to accept, n to re-enter): ").strip().lower()
                if confirm == 'y':
                    channel['url_regex'] = new_url_regex
                    break
                else:
                    print("Let's re-enter the regex.\n")
        elif action == 'c':
            channel['url_regex'] = None

        preview_recent_videos(url, criteria, playlist_end, current_regex)

        confirm = input("Are you happy with these filters? (y to save, e to edit again, n to abort): ").strip().lower()
        if confirm == 'y':
            channels[selection] = channel
            save_channels(channels_file, channels)
            print("Channel updated.")
            break
        elif confirm == 'n':
            print("Canceled changes.")
            break
        else:
            print("Let's edit again.\n")

def run_monitor(bot_token, chat_id, channels_file, cache_file, dry_run=False, suppress_skip_msgs=False):
    channels = load_channels(channels_file)
    seen_videos = load_cache(cache_file)

    for channel in channels:
        url = channel.get('url')
        criteria = channel.get('criteria', {})
        playlist_end = channel.get('playlist_end', 25)
        url_regex = channel.get('url_regex')

        if not url:
            continue

        print(f"\033[92mChecking channel:\033[0m {url}")
        videos, cname = get_latest_videos(url, playlist_end=playlist_end)
        channel_cache = set(seen_videos.get(url, []))

        for video in videos:
            video_id = video['id']
            if video_id in channel_cache:
                if not suppress_skip_msgs:
                    print("\033[90mAlready notified for:\033[0m", video_id)
                continue
            if matches_filters(video, criteria):
                video_url = video['url']
                if url_regex:
                    try:
                        pattern, repl = url_regex
                        video_url = re.sub(pattern, repl, video_url)
                    except Exception as e:
                        print(f"\033[91mFailed applying URL regex:\033[0m {e}")

                message = f"{cname} :: {video['title']}\n\n{video_url}"
                print("\033[92mNotified for:\033[0m", video['title'])
                send_telegram_message(bot_token, chat_id, message, dry_run=dry_run)
                channel_cache.add(video_id)
            else:
                if not suppress_skip_msgs:
                    print("\033[Not matched:\033[0m", video['title'])

        seen_videos[url] = list(channel_cache)
        time.sleep(random.randint(*HAMMER_DELAY_RANGE))

    save_cache(cache_file, seen_videos)

# === MAIN ===
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="yt-dlp channel monitor and Telegram notifier.")
    parser.add_argument("mode", nargs="?", choices=["run", "add", "edit", "dry-run", "config"], default="run", help="Operation mode.")
    parser.add_argument("--data-dir", type=str, default=".", help="Directory to store config, channels and cache files.")
    parser.add_argument("--interval-hours", type=float, default=0.0, help="Interval in hours to repeat run mode. Default off.")
    parser.add_argument("--suppress-skip-msgs", action="store_true", help="Suppress not matched/already-seen video messages.")
    args = parser.parse_args()

    data_dir = args.data_dir
    ensure_dir(data_dir)
    config_file = os.path.join(data_dir, "config.json")

    if not os.path.exists(config_file):
        second_dir = os.path.join(data_dir, 'data')
        second_file = os.path.join(second_dir, "config.json")
        if os.path.exists(second_file):
            data_dir = second_dir
            config_file = second_file

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

    if args.mode == "edit":
        interactive_edit_channel(channels_file)
        sys.exit(0)

    dry_run = args.mode == "dry-run"

    if args.mode in ("run", "dry-run"):
        while True:
            run_monitor(bot_token, chat_id, channels_file, cache_file, dry_run=dry_run, suppress_skip_msgs=args.suppress_skip_msgs)
            if args.interval_hours <= 0:
                break
            print(f"\033[94mSleeping for {args.interval_hours} hours before next scan...\033[0m")
            time.sleep(args.interval_hours * 3600)
