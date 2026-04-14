import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path("research/youtube-transcripts")


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def extract_video_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc in {"youtu.be", "www.youtu.be"}:
        return parsed.path.strip("/")
    query = parse_qs(parsed.query)
    return query.get("v", ["video"])[0]


def parse_videos(content: str):
    parts = re.split(r"\n## Video \d+\n", content)
    if len(parts) < 2:
        return None, []

    channel_name = parts[0].strip().removeprefix("#").strip()
    videos = []
    for block in parts[1:]:
        title_match = re.search(r"^Title:\s*(.+)$", block, flags=re.MULTILINE)
        link_match = re.search(r"^Link:\s*(https?://\S+)$", block, flags=re.MULTILINE)
        transcript_match = re.search(r"### Transcript Excerpt\n(.+)", block, flags=re.DOTALL)
        if not title_match or not link_match or not transcript_match:
            continue
        title = title_match.group(1).strip()
        link = link_match.group(1).strip()
        transcript = transcript_match.group(1).strip()
        videos.append({"title": title, "link": link, "transcript": transcript})
    return channel_name, videos


def write_video_file(folder: Path, channel_name: str, video: dict):
    video_id = extract_video_id(video["link"])
    filename = f"{slugify(video['title'])}-{video_id}.md"
    path = folder / filename
    content = "\n".join(
        [
            f"# {channel_name}",
            "",
            f"## {video['title']}",
            f"Link: {video['link']}",
            "",
            "### Transcript Excerpt",
            video["transcript"],
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")
    return path


def main():
    creator_files = list(ROOT.glob("**/*.md"))
    created_count = 0

    for creator_file in creator_files:
        text = creator_file.read_text(encoding="utf-8")
        channel_name, videos = parse_videos(text)
        if not videos:
            continue

        creator_folder = creator_file.parent
        for video in videos:
            write_video_file(creator_folder, channel_name, video)
            created_count += 1

    print(f"Created {created_count} per-video transcript files.")


if __name__ == "__main__":
    main()
