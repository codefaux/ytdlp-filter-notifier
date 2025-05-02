#!/usr/bin/env python3

import subprocess
import json
import requests
import os
import sys
import time
import signal
import random
import argparse
from collections import defaultdict
from datetime import datetime
import prettytable
import re

# === CONFIGURATION ===
HAMMER_DELAY_RANGE = (2, 4)  # Seconds between requests
cache_file = ""
regex_file = ""
channels_file = ""
netrc_file = ""
using_netrc = False

# ANSI color codes
ANSI_BLUE = '\033[94m'
ANSI_YELLOW = '\033[93m'
ANSI_GREEN = '\033[92m'
ANSI_RED = '\033[91m'
ANSI_GREY = '\033[90m'
ANSI_RESET = '\033[0m'

# === GLOBALS ===
message_queue = []

# === FUNCTIONS ===

def handle_signal(signum, frame):
    print(f"Received signal {signum}, exiting.")
    sys.exit(0)

signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)

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
        channel_url
    ]

    if playlist_end:
        cmd[5:5] = ["--playlist-end", str(playlist_end)]
    if using_netrc:
        cmd[1:1] = ["--netrc", "--netrc-location", netrc_file]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"{ANSI_RED}yt-dlp error:{ANSI_RESET}", result.stderr)
        return [], None
    try:
        data = json.loads(result.stdout)
        return data.get('entries', [])[::-1], data.get('channel') or data.get('title') or data.get('uploader')
    except json.JSONDecodeError:
        print(f"{ANSI_RED}Failed to parse yt-dlp output.{ANSI_RESET}")
        if not using_netrc:
            print(f"{ANSI_YELLOW}Tip: Create a netrc file at {netrc_file} if the video requires login.{ANSI_RESET}")
        return [], None

def get_video_upload_date(video_url):
    """Return upload_date in yyyymmdd format from a video URL using yt-dlp."""
    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--no-check-certificate",
        "--print", "%(timestamp)s,%(upload_date)s",
        video_url
    ]

    if using_netrc:
        cmd[1:1] = ["--netrc", "--netrc-location", netrc_file]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"{ANSI_RED}yt-dlp error while fetching metadata:{ANSI_RESET} {result.stderr.strip()}")
        if not using_netrc:
            print(f"{ANSI_YELLOW}Tip: Create a netrc file at {netrc_file} if the video requires login.{ANSI_RESET}")
        return None

    output = result.stdout.strip()
    if ',' not in output:
        print(f"{ANSI_RED}Unexpected output format from yt-dlp:{ANSI_RESET} {output}")
        return None

    timestamp_str, upload_date_str = output.split(',', 1)

    if upload_date_str and re.fullmatch(r"\d{8}", upload_date_str):
        return upload_date_str

    try:
        timestamp = int(timestamp_str)
        dt = datetime.utcfromtimestamp(timestamp)
        return dt.strftime("%Y%m%d")
    except ValueError:
        print(f"{ANSI_RED}Invalid timestamp:{ANSI_RESET} {timestamp_str}")
        return None

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

def process_message_queue():
    # Group messages by datecode
    grouped_messages = defaultdict(list)
    for datecode, text, dry_run in message_queue:
        grouped_messages[datecode].append((text, dry_run))
    
    # Process messages sorted by datecode
    for datecode in sorted(grouped_messages):
        for text, dry_run in grouped_messages[datecode]:
            send_telegram_message(text, dry_run=dry_run)
    
    message_queue.clear()

def send_telegram_message(text, dry_run=False):
    config = load_config(config_file)
    bot_token = config['telegram_bot_token']
    chat_id = config['telegram_chat_id']

    if dry_run:
        print(f"\n\t{ANSI_BLUE}[Dry-Run] Notification: {ANSI_RESET}\n{text}\n\t{ANSI_BLUE}[End]{ANSI_RESET}\n")
        return
    else:
        print(f"{ANSI_GREEN}Sending Notifiation: {ANSI_RESET} {text}")

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
                    print(f"{ANSI_RED}Rate limit encountered, but retry_after missing. Exiting.{ANSI_RESET}")
                    sys.exit(1)
                print(f"{ANSI_YELLOW}Rate limited by Telegram. Retrying after {retry_after} seconds...{ANSI_RESET}")
                time.sleep(retry_after + 3)
                retries += 1
            except (ValueError, KeyError, json.JSONDecodeError):
                print(f"{ANSI_RED}Rate limit encountered, but failed to parse retry_after. Exiting.{ANSI_RESET}")
                sys.exit(1)
        else:
            print(f"{ANSI_RED}Failed to send Telegram message (HTTP {response.status_code}):{ANSI_RESET} {response.text}")
            sys.exit(1)

    if retries > max_retries:
        print(f"{ANSI_RED}Exceeded maximum retries. Exiting.{ANSI_RESET}")
        sys.exit(1)

    time.sleep(1)

def print_channel_settings(channel):
    url = channel.get('url', 'N/A')
    playlist_end = channel.get('playlist_end', 'N/A')
    criteria = channel.get('criteria', {})
    url_regex = channel.get('url_regex')

    print(f"\n{ANSI_GREEN}Channel URL:{ANSI_RESET} {url}")
    print(f"{ANSI_GREEN}Playlist End:{ANSI_RESET} {playlist_end}")

    if criteria:
        print(f"{ANSI_GREEN}Filter Criteria:{ANSI_RESET}")
        for key, value in criteria.items():
            print(f"  {key}: {value}")
    else:
        print(f"{ANSI_GREEN}Filter Criteria:{ANSI_RESET} None")

    if url_regex:
        pattern, replacement = url_regex
        print(f"{ANSI_GREEN}URL Regex Pattern:{ANSI_RESET} {pattern}")
        print(f"{ANSI_GREEN}URL Regex Replacement:{ANSI_RESET} {replacement}")
    else:
        print(f"{ANSI_GREEN}URL Regex:{ANSI_RESET} None")

def preview_recent_videos(url, criteria, playlist_end, url_regex=None, skip_result=False):
    print("\nFetching recent videos to preview matches...")
    videos, cname = get_latest_videos(url, playlist_end=playlist_end)
    if not videos:
        print("No videos found or error fetching.")
        return None, None

    table = prettytable.PrettyTable()

    if skip_result:
        table.field_names = ["Title", "Duration", "URL"]
    else:
        table.field_names = ["Title", "Duration", "Result", "URL"]

    table.max_width["URL"] =  60
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

        if reason == "Matched" and not skip_result:
            colored_title_lines = [f"{ANSI_GREEN}{line}{ANSI_RESET}" for line in title_lines]
            colored_duration = f"{ANSI_GREEN}{duration_str}{ANSI_RESET}"
        else:
            if "title" in reason.lower() and not skip_result:
                colored_title_lines = [f"{ANSI_RED}{line}{ANSI_RESET}" for line in title_lines]
            else:
                colored_title_lines = title_lines

            if ("short" in reason.lower() or "long" in reason.lower()) and not skip_result:
                colored_duration = f"{ANSI_RED}{duration_str}{ANSI_RESET}"
            else:
                colored_duration = duration_str

        color_title = "\n".join(colored_title_lines)
            

        if url_regex:
            url_display = f"{ANSI_RED}IN:{ANSI_RESET}{video_url}\n{ANSI_GREEN}OUT:{ANSI_RESET}{modified_url}"
        else:
            url_display = f"{video_url}"

        if skip_result:
            table.add_row([color_title, colored_duration, url_display])
        else:
            table.add_row([color_title, colored_duration, reason, url_display])

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

def load_regex_presets(presets_file):
    return load_json(presets_file, {})

def save_regex_presets(presets_file, presets):
    save_json(presets_file, presets)

def interactive_edit_regex_presets(presets_file):
    presets = load_regex_presets(presets_file)

    while True:
        print("\nCurrent Presets:")
        for idx, (name, (pattern, replacement)) in enumerate(presets.items()):
            print(f"[{idx}] {name} =>\n\tpattern: {pattern},\n\treplacement: {replacement}")

        action = input("\nSelect action: (a=add new, e=edit existing, d=delete, q=quit): ").strip().lower()

        if action == 'a':
            name = input("Enter new preset name: ").strip()
            if name in presets:
                print(f"{ANSI_RED}Preset already exists.{ANSI_RESET}")
                continue
            pattern = input("Enter regex pattern: ").strip()
            replacement = input("Enter replacement string: ").strip()
            presets[name] = [pattern, replacement]
            save_regex_presets(presets_file, presets)
            print(f"{ANSI_GREEN}Preset '{name}' added.{ANSI_RESET}")

        elif action == 'e':
            try:
                idx = int(input("Enter preset number to edit: ").strip())
                name = list(presets.keys())[idx]
                print(f"Editing preset: {name}")
                pattern = input(f"Enter new regex pattern (leave blank to keep '{presets[name][0]}'): ").strip()
                replacement = input(f"Enter new replacement string (leave blank to keep '{presets[name][1]}'): ").strip()
                if pattern:
                    presets[name][0] = pattern
                if replacement:
                    presets[name][1] = replacement
                save_regex_presets(presets_file, presets)
                print(f"{ANSI_GREEN}Preset '{name}' updated.{ANSI_RESET}")
            except (ValueError, IndexError):
                print(f"{ANSI_RED}Invalid selection.{ANSI_RESET}")

        elif action == 'd':
            try:
                idx = int(input("Enter preset number to delete: ").strip())
                name = list(presets.keys())[idx]
                confirm = input(f"Are you sure you want to delete preset '{name}'? (y/n): ").strip().lower()
                if confirm == 'y':
                    del presets[name]
                    save_regex_presets(presets_file, presets)
                    print(f"{ANSI_GREEN}Preset '{name}' deleted.{ANSI_RESET}")
            except (ValueError, IndexError):
                print(f"{ANSI_RED}Invalid selection.{ANSI_RESET}")

        elif action == 'q':
            print("Exiting regex preset editor.")
            break

        else:
            print(f"{ANSI_RED}Unknown action.{ANSI_RESET}")

def choose_url_regex():
    presets = load_regex_presets(regex_file)
    channels = load_channels(channels_file, skip_add=True)

    while True:
        print("\nChoose URL regex option:")
        print("[1] Pick from presets")
        print("[2] Enter manually")
        print("[3] Edit presets")
        print("[4] Import from existing channel")
        print("[5] Cancel / None")

        choice = input("Select option (1-5): ").strip()

        if choice == '1':
            if not presets:
                print(f"{ANSI_RED}No presets available.{ANSI_RESET}")
                continue
            print("\nAvailable Presets:")
            for idx, (name, (pattern, replacement)) in enumerate(presets.items()):
                print(f"[{idx}] {name} =>\n\tpattern: {pattern},\n\treplacement: {replacement}")
            try:
                idx = int(input("Select preset number: ").strip())
                name = list(presets.keys())[idx]
                pattern, replacement = presets[name]
                return [pattern, replacement]
            except (ValueError, IndexError):
                print(f"{ANSI_RED}Invalid selection.{ANSI_RESET}")
                continue

        elif choice == '2':
            pattern = input("Enter regex pattern to match in URL: ").strip()
            replacement = input("Enter replacement string: ").strip()
            return [pattern, replacement]

        elif choice == '3':
            interactive_edit_regex_presets(regex_file)
            presets = load_regex_presets(regex_file)  # Reload after editing

        elif choice == '4':
            if not channels:
                print(f"{ANSI_RED}No saved channels found.{ANSI_RESET}")
                continue

            print("\nSaved Channels:")
            for idx, chan in enumerate(channels):
                print(f"[{idx}] {chan.get('url', 'UNKNOWN')}")

            try:
                idx = int(input("Select channel number to import from: ").strip())
                selected = channels[idx]
                if selected.get('url_regex'):
                    print(f"{ANSI_GREEN}Imported regex from channel:{ANSI_RESET} {selected.get('url')}")
                    return selected['url_regex']
                else:
                    print(f"{ANSI_RED}Selected channel has no URL regex configured.{ANSI_RESET}")
            except (ValueError, IndexError):
                print(f"{ANSI_RED}Invalid selection.{ANSI_RESET}")

        elif choice == '5':
            return None

        else:
            print(f"{ANSI_RED}Unknown option.{ANSI_RESET}")

def interactive_add_channel(channels_file):
    criteria = {}
    playlist_end = 25
    url_regex = None

    while True:
        url = input("Enter the channel URL: ").strip()
        videos, discarded = preview_recent_videos(url, criteria, playlist_end, url_regex, skip_result=True)

        if videos:
            break
        else:
            if input("Error downloading videos. Enter a different URL? (y/n): ").strip().lower() != 'y':
                sys.exit(0)

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
            url_regex = choose_url_regex()

        videos, discarded = preview_recent_videos(url, criteria, playlist_end, url_regex, skip_result=False)
        print_channel_settings(channel)

        confirm = input("Are you happy with these filters? (y to accept, n to edit again, q to cancel): ").strip().lower()
        if confirm == 'y':
            channel = {"url": url, "criteria": criteria, "playlist_end": playlist_end, "url_regex": url_regex}
            channels = load_channels(channels_file, skip_add=True)
            channels.append(channel)
            save_channels(channels_file, channels)
            print("Channel added.")
            if input("Would you like to run notifications for this channel? (y/n): ").strip().lower() == 'y':
                run_channel(channel, dry_run=False, suppress_skip_msgs=False, seen_during_dry_run=False)
                process_message_queue()
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
    print_channel_settings(channel)
    
    confirm = input("Do you wish to edit these filters? (y to edit, anything else to cancel): ").strip().lower()
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
                pattern, replacement = choose_url_regex()

                if videos:
                    print("\nSample URL previews with your regex:")
                    for sample_video in videos:
                        original_url = sample_video.get('url', '')
                        modified_url = original_url
                        try:
                            modified_url = re.sub(pattern, replacement, original_url)
                        except Exception as e:
                            print(f"{ANSI_RED}Regex error:{ANSI_RESET} {e}")
                        print(f"Original: {original_url}")
                        print(f"Modified: {modified_url}\n")

                confirm = input("Are you happy with this regex? (y to accept, n to re-enter): ").strip().lower()
                if confirm == 'y':
                    channel['url_regex'] = [pattern, replacement]
                    break
                else:
                    print("Let's re-enter the regex.\n")
        elif action == 'c':
            channel['url_regex'] = None

        preview_recent_videos(url, criteria, playlist_end, current_regex)
        print_channel_settings(channel)

        confirm = input("Are you happy with these filters? (y to save, e to edit again, n to abort): ").strip().lower()
        if confirm == 'y':
            channels[selection] = channel
            save_channels(channels_file, channels)
            print("Channel updated.")
            if input("Would you like to run notifications for this channel? (y/n): ").strip().lower() == 'y':
                run_channel(channel, dry_run=False, suppress_skip_msgs=False, seen_during_dry_run=False)
                process_message_queue()
            break
        elif confirm == 'n':
            print("Canceled changes.")
            break
        else:
            print("Let's edit again.\n")

def run_all_channels(channels_file, dry_run=False, suppress_skip_msgs=False, seen_during_dry_run=False):
    channels = load_channels(channels_file)

    for channel in channels:
        run_channel(channel, dry_run, suppress_skip_msgs, seen_during_dry_run)
        time.sleep(random.randint(*HAMMER_DELAY_RANGE))



def run_channel(channel, dry_run=False, suppress_skip_msgs=False, seen_during_dry_run=False):
    url = channel.get('url')
    criteria = channel.get('criteria', {})
    playlist_end = channel.get('playlist_end', 25)
    url_regex = channel.get('url_regex')
    seen_videos = load_cache(cache_file)

    if not url:
        return

    print(f"{ANSI_GREEN}Checking channel:{ANSI_RESET} {url}")
    videos, cname = get_latest_videos(url, playlist_end=playlist_end)
    channel_cache = set(seen_videos.get(url, []))

    for video in videos:
        video_id = video['id']
        if video_id in channel_cache:
            if not suppress_skip_msgs:
                print(f"{ANSI_GREY}Already seen:{ANSI_RESET} {video_id} -- {video['title']}")
            continue
        if matches_filters(video, criteria):
            video_url = video['url']
            if url_regex:
                try:
                    pattern, repl = url_regex
                    video_url = re.sub(pattern, repl, video_url)
                except Exception as e:
                    print(f"{ANSI_RED}Failed applying URL regex:{ANSI_RESET} {e}")

            upload_date = video.get('upload_date')
            if not upload_date:
                upload_date = get_video_upload_date(video_url) or "unknown"

            message = f"{cname} :: {upload_date} :: {video['title']}\n\n{video_url}"
            message_queue.append((upload_date, message, dry_run))
            print(f"{ANSI_BLUE}Queued for:{ANSI_RESET} {video_id}")
            if seen_during_dry_run or not dry_run:
                channel_cache.add(video_id)
        else:
            if not suppress_skip_msgs:
                print(f"{ANSI_YELLOW}Not matched:{ANSI_RESET} {video_id} -- {video['title']}")

    seen_videos[url] = list(channel_cache)
    save_cache(cache_file, seen_videos)
    return

def chunked_sleep(total_seconds, check_interval=3):
    slept = 0
    while slept < total_seconds:
        time.sleep(min(check_interval, total_seconds - slept))
        slept += check_interval

# === MAIN ===
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="yt-dlp channel monitor and Telegram notifier.")
    parser.add_argument("mode", nargs="?", choices=["run", "add", "edit", "regex", "dry-run", "config"], default="dry-run", help="Operation mode.")
    parser.add_argument("--data-dir", type=str, default=".", help="Directory to store config, channels and cache files.")
    parser.add_argument("--interval-hours", type=float, default=0.0, help="Interval in hours to repeat run mode. Default off.")
    parser.add_argument("--suppress-skip-msgs", action="store_true", help="Suppress not matched/already-seen video messages.")
    parser.add_argument("--seen-during-dry-run", action="store_true", help="Mark videos as seen during dry-run.")
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
    regex_file = os.path.join(data_dir, "regex_presets.json")
    netrc_file = os.path.join(data_dir, "netrc")

    if args.mode == "config":
        edit_config(config_file)
        sys.exit(0)

    config = load_config(config_file)
    using_netrc = os.path.exists(netrc_file)
    if not using_netrc:
        print(f"{ANSI_YELLOW}Tip: Create a netrc file at {netrc_file} if a platform (eg. nebula) requires login.{ANSI_RESET}")

    if args.mode == "add":
        interactive_add_channel(channels_file)
        sys.exit(0)

    if args.mode == "edit":
        interactive_edit_channel(channels_file)
        sys.exit(0)

    if args.mode == "regex":
        interactive_edit_regex_presets(regex_file)
        sys.exit(0)

    dry_run = args.mode == "dry-run"

    if args.mode in ("run", "dry-run"):
        while True:
            run_all_channels(channels_file, dry_run=dry_run, suppress_skip_msgs=args.suppress_skip_msgs, seen_during_dry_run=args.seen_during_dry_run)
            process_message_queue()
            if args.interval_hours <= 0:
                break
            print(f"{ANSI_BLUE}Sleeping for {args.interval_hours} hours before next scan...{ANSI_RESET}")
            chunked_sleep(args.interval_hours * 3600)
