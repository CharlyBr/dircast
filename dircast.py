#!/usr/bin/env python3
"""Generate a podcast RSS feed from MP3 files in a directory."""

import argparse
import datetime
import mimetypes
import os
import sys
from email.utils import formatdate
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom.minidom import parseString

from mutagen.id3 import ID3
from mutagen.mp3 import MP3


def get_mp3_metadata(filepath: Path) -> dict:
    """Extract metadata from an MP3 file using ID3 tags."""
    audio = MP3(str(filepath))
    duration_secs = int(audio.info.length)

    meta = {
        "title": filepath.stem,
        "artist": "",
        "album": "",
        "date": None,
        "duration": duration_secs,
        "size": filepath.stat().st_size,
    }

    try:
        tags = ID3(str(filepath))
    except Exception:
        tags = None

    if tags:
        if tags.get("TIT2"):
            meta["title"] = str(tags["TIT2"])
        if tags.get("TPE1"):
            meta["artist"] = str(tags["TPE1"])
        if tags.get("TALB"):
            meta["album"] = str(tags["TALB"])

        # Try to get a date from TDRC (recording date) or TDRL (release date) or TDAT
        for tag_key in ("TDRC", "TDRL", "TDAT", "TYER"):
            tag = tags.get(tag_key)
            if tag:
                try:
                    text = str(tag).strip()
                    # TDRC/TDRL can be full timestamp like "2023-05-12"
                    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y"):
                        try:
                            meta["date"] = datetime.datetime.strptime(text, fmt)
                            break
                        except ValueError:
                            continue
                    if meta["date"]:
                        break
                except Exception:
                    continue

    # If mutagen couldn't parse the date (e.g. non-standard TDAT with full date),
    # try reading raw ID3v2 frames directly
    if not meta["date"]:
        meta["date"] = _parse_raw_id3_date(filepath)

    return meta


def _parse_raw_id3_date(filepath: Path):
    """Read raw ID3v2 frames to extract dates that mutagen may reject as non-standard."""
    try:
        with open(filepath, "rb") as f:
            header = f.read(10)
            if header[:3] != b"ID3":
                return None
            tag_size = (header[6] << 21) | (header[7] << 14) | (header[8] << 7) | header[9]
            tag_data = f.read(tag_size)

        date_texts = {}
        pos = 0
        while pos < len(tag_data) - 10:
            frame_id = tag_data[pos:pos + 4]
            if frame_id[0:1] == b"\x00":
                break
            frame_size = int.from_bytes(tag_data[pos + 4:pos + 8], "big")
            frame_data = tag_data[pos + 10:pos + 10 + frame_size]
            frame_name = frame_id.decode("latin-1", errors="replace")
            if frame_name in ("TDAT", "TDRC", "TDRL", "TYER"):
                # Text frames: first byte is encoding, rest is text
                encoding = frame_data[0]
                if encoding == 0:
                    text = frame_data[1:].decode("latin-1", errors="replace").strip("\x00")
                elif encoding == 1:
                    text = frame_data[1:].decode("utf-16", errors="replace").strip("\x00")
                elif encoding == 3:
                    text = frame_data[1:].decode("utf-8", errors="replace").strip("\x00")
                else:
                    text = frame_data[1:].decode("latin-1", errors="replace").strip("\x00")
                date_texts[frame_name] = text.strip()
            pos += 10 + frame_size

        # Try each date frame in priority order
        for key in ("TDRC", "TDRL", "TDAT", "TYER"):
            text = date_texts.get(key)
            if not text:
                continue
            for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y"):
                try:
                    return datetime.datetime.strptime(text, fmt)
                except ValueError:
                    continue
    except Exception:
        pass
    return None


def format_duration(seconds: int) -> str:
    """Format duration as HH:MM:SS."""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_feed(directory: Path, base_url: str, title: str, description: str) -> str:
    """Build a podcast RSS XML feed from MP3 files in the directory."""
    mp3_files = sorted(directory.glob("*.mp3"))
    if not mp3_files:
        print("No MP3 files found in the directory.", file=sys.stderr)
        sys.exit(1)

    # Namespaces
    itunes_ns = "http://www.itunes.com/dtds/podcast-1.0.dtd"
    nsmap = {"itunes": itunes_ns}

    rss = Element("rss", version="2.0")
    rss.set("xmlns:itunes", itunes_ns)
    channel = SubElement(rss, "channel")

    SubElement(channel, "title").text = title
    SubElement(channel, "description").text = description
    SubElement(channel, "language").text = "fr"
    SubElement(channel, "generator").text = "dircast"

    # Collect items with metadata
    items = []
    for mp3_path in mp3_files:
        meta = get_mp3_metadata(mp3_path)
        items.append((mp3_path, meta))

    # Sort by date if available, then by filename
    def sort_key(item):
        _, meta = item
        if meta["date"]:
            return meta["date"]
        # Fallback: file modification time
        return datetime.datetime.fromtimestamp(item[0].stat().st_mtime)

    items.sort(key=sort_key, reverse=True)

    # Set channel pub date from most recent item
    if items:
        most_recent_date = sort_key(items[0])
        SubElement(channel, "pubDate").text = formatdate(most_recent_date.timestamp(), usegmt=True)

    for mp3_path, meta in items:
        item = SubElement(channel, "item")
        SubElement(item, "title").text = meta["title"]

        if meta["artist"]:
            SubElement(item, f"{{{itunes_ns}}}author").text = meta["artist"]

        if meta["album"]:
            SubElement(item, "description").text = meta["album"]

        # Publication date
        if meta["date"]:
            pub_date = meta["date"]
        else:
            pub_date = datetime.datetime.fromtimestamp(mp3_path.stat().st_mtime)
        SubElement(item, "pubDate").text = formatdate(pub_date.timestamp(), usegmt=True)

        # Enclosure
        file_url = base_url.rstrip("/") + "/" + mp3_path.name
        enclosure = SubElement(item, "enclosure")
        enclosure.set("url", file_url)
        enclosure.set("length", str(meta["size"]))
        enclosure.set("type", "audio/mpeg")

        # Duration
        SubElement(item, f"{{{itunes_ns}}}duration").text = format_duration(meta["duration"])

        # GUID
        SubElement(item, "guid").text = file_url

    raw_xml = tostring(rss, encoding="unicode", xml_declaration=False)
    pretty = parseString(f'<?xml version="1.0" encoding="UTF-8"?>{raw_xml}').toprettyxml(indent="  ")
    # Remove extra xml declaration from toprettyxml
    lines = pretty.split("\n")
    return "\n".join(lines[1:]) if lines[0].startswith("<?xml") else pretty


def main():
    parser = argparse.ArgumentParser(description="Generate a podcast RSS feed from MP3 files.")
    parser.add_argument("directory", type=Path, help="Directory containing MP3 files")
    parser.add_argument("--base-url", default="http://localhost/podcasts",
                        help="Base URL where MP3 files are served (default: http://localhost/podcasts)")
    parser.add_argument("--title", default="Podcast", help="Podcast title")
    parser.add_argument("--description", default="Podcast generated from MP3 files", help="Podcast description")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="Output file (default: stdout)")

    args = parser.parse_args()

    if not args.directory.is_dir():
        print(f"Error: {args.directory} is not a directory.", file=sys.stderr)
        sys.exit(1)

    xml = f'<?xml version="1.0" encoding="UTF-8"?>\n{build_feed(args.directory, args.base_url, args.title, args.description)}'

    if args.output:
        args.output.write_text(xml, encoding="utf-8")
        print(f"Feed written to {args.output}", file=sys.stderr)
    else:
        print(xml)


if __name__ == "__main__":
    main()
