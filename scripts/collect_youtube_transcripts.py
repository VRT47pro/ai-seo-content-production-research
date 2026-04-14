import argparse
import json
import subprocess
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound


DEFAULT_CREATORS = [
    {"name": "Nathan Gotch", "handle": "nathangotch", "output_file": "nathan-gotch.md"},
    {"name": "Jesper Nissen", "handle": "JesperNissenSEO", "output_file": "jesper-nissen.md"},
    {"name": "Matt Diggity", "handle": "mattdiggityseo", "output_file": "matt-diggity.md"},
    {"name": "Kasra Dash", "handle": "KasraDash", "output_file": "kasra-dash.md"},
    {"name": "Simson Scrapes", "handle": "simonscrapes", "output_file": "simson-scrapes.md"},
]


def fetch_url_text(url: str) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        },
    )
    with urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def get_recent_video_ids(handle: str, limit: int) -> List[str]:
    html = fetch_url_text(f"https://www.youtube.com/@{handle}/videos")
    # The videos page includes duplicated IDs in several JSON blobs.
    ids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)
    seen = set()
    unique_ids = []
    for video_id in ids:
        if video_id in seen:
            continue
        seen.add(video_id)
        unique_ids.append(video_id)
        if len(unique_ids) >= limit:
            break
    return unique_ids


def search_video_ids(query: str, limit: int) -> List[str]:
    html = fetch_url_text(
        f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
    )
    ids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)
    seen = set()
    unique_ids = []
    for video_id in ids:
        if video_id in seen:
            continue
        seen.add(video_id)
        unique_ids.append(video_id)
        if len(unique_ids) >= limit:
            break
    return unique_ids


def get_recent_video_ids_from_channel_feed(channel_id: str, limit: int) -> List[str]:
    xml_text = fetch_url_text(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
    root = ET.fromstring(xml_text)
    ns = {
        "a": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
    }
    entries = root.findall("a:entry", ns)
    ids = []
    for entry in entries[:limit]:
        node = entry.find("yt:videoId", ns)
        if node is not None and node.text:
            ids.append(node.text.strip())
    return ids


def resolve_channel_id_by_handle(handle: str) -> Optional[str]:
    payload = fetch_url_text(f"https://www.youtube.com/@{handle}")
    match = re.search(r'"channelId":"(UC[a-zA-Z0-9_-]{22})"', payload)
    if match:
        return match.group(1)
    return None


def get_recent_video_ids_via_ytdlp(creator_name: str, limit: int) -> List[str]:
    command = [
        "python",
        "-m",
        "yt_dlp",
        "--flat-playlist",
        "--dump-single-json",
        f"ytsearchdate{max(limit * 10, 20)}:{creator_name}",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return []

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    entries = payload.get("entries", [])
    tokens = {token for token in re.findall(r"[a-z0-9]+", creator_name.lower()) if len(token) >= 3}
    ids = []
    for entry in entries:
        uploader = str(entry.get("uploader") or "").lower()
        channel = str(entry.get("channel") or "").lower()
        text = f"{uploader} {channel}"
        token_matches = sum(1 for token in tokens if token in text)
        if token_matches < max(1, min(2, len(tokens))):
            continue

        video_id = entry.get("id")
        if not video_id or video_id in ids:
            continue
        ids.append(video_id)
        if len(ids) >= limit:
            break

    return ids


def get_video_title(video_id: str) -> str:
    html = fetch_url_text(f"https://www.youtube.com/watch?v={video_id}")
    match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not match:
        return f"Video {video_id}"
    title = match.group(1).replace(" - YouTube", "").strip()
    return re.sub(r"\s+", " ", title)


def get_transcript_text(video_id: str) -> Optional[str]:
    try:
        transcript = YouTubeTranscriptApi().fetch(video_id)
    except (TranscriptsDisabled, NoTranscriptFound):
        return None
    except Exception:
        return None

    parts = []
    for entry in transcript:
        text = (entry.text or "").strip()
        if text:
            parts.append(text.replace("\n", " "))
    return " ".join(parts).strip() or None


def write_creator_markdown(
    output_file: Path,
    creator_name: str,
    creator_handle: str,
    videos: List[Dict[str, str]],
) -> None:
    lines = [
        f"# {creator_name}",
        f"- Handle: @{creator_handle}",
        f"- Updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]

    if not videos:
        lines.extend(
            [
                "No transcript data found for recent videos.",
                "",
            ]
        )
    else:
        for index, video in enumerate(videos, start=1):
            transcript_excerpt = video["transcript"].strip() or "Transcript unavailable in current environment."
            lines.extend(
                [
                    f"## Video {index}",
                    f"Title: {video['title']}",
                    f"Link: https://www.youtube.com/watch?v={video['video_id']}",
                    "",
                    "### Transcript Excerpt",
                    transcript_excerpt[:3500] + ("..." if len(transcript_excerpt) > 3500 else ""),
                    "",
                ]
            )

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text("\n".join(lines), encoding="utf-8")


def load_creators(path: Optional[Path]) -> List[Dict[str, str]]:
    if path is None:
        return DEFAULT_CREATORS

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Creators JSON must be a list")

    creators = []
    for row in payload:
        if not isinstance(row, dict) or "name" not in row or "handle" not in row:
            raise ValueError("Each creator must include 'name' and 'handle'")
        creator = {"name": str(row["name"]), "handle": str(row["handle"])}
        if "output_file" in row:
            creator["output_file"] = str(row["output_file"])
        creators.append(creator)
    return creators


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect recent YouTube transcripts for creators."
    )
    parser.add_argument(
        "--creators-json",
        type=Path,
        default=None,
        help="Optional path to creators JSON file: [{name, handle}, ...]",
    )
    parser.add_argument(
        "--max-videos",
        type=int,
        default=3,
        help="How many recent videos to process per creator.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("research/youtube-transcripts"),
        help="Directory where markdown files are written.",
    )
    args = parser.parse_args()

    creators = load_creators(args.creators_json)

    for creator in creators:
        name = creator["name"]
        handle = creator["handle"]
        output_file_name = creator.get("output_file")
        if output_file_name:
            output_file = args.output_dir / output_file_name
        else:
            slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            output_file = args.output_dir / f"{slug}.md"
        print(f"[INFO] Collecting @{handle} -> {output_file}")

        try:
            channel_id = resolve_channel_id_by_handle(handle)
            if channel_id:
                video_ids = get_recent_video_ids_from_channel_feed(channel_id, args.max_videos)
            else:
                video_ids = get_recent_video_ids(handle, args.max_videos)
        except (HTTPError, URLError, TimeoutError) as exc:
            print(f"[WARN] Could not load channel @{handle}: {exc}")
            print(f"[INFO] Falling back to yt-dlp channel-matched search for '{name}'")
            video_ids = get_recent_video_ids_via_ytdlp(name, args.max_videos)
            if not video_ids:
                print(f"[INFO] Falling back to generic YouTube search for '{name}'")
                video_ids = search_video_ids(name, args.max_videos)

        if not video_ids:
            print(f"[WARN] No recent videos found for {name}")
            write_creator_markdown(output_file, name, handle, [])
            continue

        videos = []
        for video_id in video_ids:
            title = get_video_title(video_id)
            transcript = get_transcript_text(video_id)
            if not transcript:
                print(f"[WARN] Transcript unavailable: {video_id}")
                transcript = "Transcript unavailable in current environment."

            videos.append(
                {
                    "video_id": video_id,
                    "title": title,
                    "transcript": transcript,
                }
            )
            print(f"[OK] Transcript captured: {video_id}")

        write_creator_markdown(output_file, name, handle, videos)

    print("[DONE] Transcript collection finished.")


if __name__ == "__main__":
    main()
