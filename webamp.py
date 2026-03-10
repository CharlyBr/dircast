#!/usr/bin/env python3
"""Generate a Webamp player page from MP3 files in a directory."""

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import quote

from mutagen.id3 import ID3
from mutagen.mp3 import MP3


def get_title(filepath: Path) -> str:
    """Extract title from ID3 tags, falling back to filename stem."""
    try:
        tags = ID3(str(filepath))
        if tags.get("TIT2"):
            return str(tags["TIT2"])
    except Exception:
        pass
    return filepath.stem


def build_tracks(directory: Path, base_url: str) -> list[dict]:
    """Build track list from MP3 files in the directory."""
    mp3_files = sorted(directory.glob("*.mp3"))
    tracks = []
    for mp3_path in mp3_files:
        tracks.append({
            "title": get_title(mp3_path),
            "url": base_url.rstrip("/") + "/" + quote(mp3_path.name),
            "filename": mp3_path.name,
        })
    return tracks


INDEX_HTML = """\
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    body {{
      margin: 0;
      background: #000;
      display: flex;
      justify-content: center;
      align-items: flex-start;
      min-height: 100vh;
      padding-top: 10vh;
    }}
    #app {{ position: relative; }}
    .error {{ color: #f44; font-family: monospace; text-align: center; padding: 2em; }}
  </style>
</head>
<body>
  <div id="app"></div>
  <script src="https://unpkg.com/webamp@1.5.0/built/webamp.bundle.min.js"></script>
  <script>
    async function boot() {{
      if (!window.Webamp) {{
        document.getElementById("app").innerHTML =
          '<p class="error">Webamp failed to load.</p>';
        return;
      }}

      try {{
        const response = await fetch("tracks.json");
        if (!response.ok) throw new Error("Failed to load tracks.json");
        const tracks = await response.json();

        if (tracks.length === 0) {{
          document.getElementById("app").innerHTML =
            '<p class="error">No tracks found.</p>';
          return;
        }}

        const webamp = new window.Webamp({{
          initialTracks: tracks.map(t => ({{
            metaData: {{ title: t.title }},
            url: t.url,
            defaultName: t.filename,
          }})),
          enableDoubleSizeMode: false,
          enableHotkeys: true,
        }});

        webamp.store.dispatch({{
          type: "WINDOW_SIZE_CHANGED",
          windowId: "playlist",
          size: [0, 10],
        }});

        await webamp.renderWhenReady(document.getElementById("app"));
      }} catch (error) {{
        console.error(error);
        document.getElementById("app").innerHTML =
          '<p class="error">' + error.message + '</p>';
      }}
    }}

    boot();
  </script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Generate a Webamp player page from MP3 files.")
    parser.add_argument("directory", type=Path, help="Directory containing MP3 files")
    parser.add_argument("--base-url", default=".",
                        help="Base URL where MP3 files are served (default: .)")
    parser.add_argument("--title", default="Webamp", help="Page title")
    parser.add_argument("-o", "--output-dir", type=Path, default=None,
                        help="Output directory for index.html and tracks.json (default: same as input directory)")

    args = parser.parse_args()

    if not args.directory.is_dir():
        print(f"Error: {args.directory} is not a directory.", file=sys.stderr)
        sys.exit(1)

    output_dir = args.output_dir or args.directory
    output_dir.mkdir(parents=True, exist_ok=True)

    tracks = build_tracks(args.directory, args.base_url)
    if not tracks:
        print("No MP3 files found.", file=sys.stderr)
        sys.exit(1)

    tracks_path = output_dir / "tracks.json"
    tracks_path.write_text(json.dumps(tracks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Written {tracks_path} ({len(tracks)} tracks)", file=sys.stderr)

    index_path = output_dir / "index.html"
    index_path.write_text(INDEX_HTML.format(title=args.title), encoding="utf-8")
    print(f"Written {index_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
