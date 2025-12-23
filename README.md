# 📸 Snapchat Memories Downloader

Python script to download Snapchat Memories from the HTML export file, extract archives, and merge overlays (images and videos) into final media files.

## 🎬 ffmpeg requirement

Video overlays require `ffmpeg` (and `ffprobe`). Install it before running the script:

- macOS (Homebrew): `brew install ffmpeg`
- Ubuntu/Debian: `sudo apt install ffmpeg`
- Windows (Chocolatey): `choco install ffmpeg`

Verify it is available:
```bash
ffmpeg -version
ffprobe -version
```
The script exits early if either is missing.

## ✅ Prerequisites

- Python 3.9+
- pip
- `ffmpeg` (includes `ffprobe`) to apply overlays to videos

## 🧭 Full procedure

1. Request your memories data:
- browse to https://accounts.snapchat.com/v2/download-my-data
- select "Export your Memories" and the desired time frame
- click on "Request Only Memories"

2. Get your memories data:
- check email inbox for download link
- click on download link
- under "Your exports", click on "See exports"
- click on download button for requested export

3. Clone this project and copy the html folder from your Snapchat download at the root of this project

4. Python / venv installation (choose your OS):

macOS / Linux:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell):
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

5. Run the downloading script:
```bash
python3 ./download_memories.py --html ./html/memories_history.html
```

Useful examples:
```bash
# Test mode (2 videos + 2 images)
python3 ./download_memories.py --test

# Normal mode (all available memories)
python3 ./download_memories.py

# Faster mode with parallel workers
python3 ./download_memories.py --workers 3

# Parallel workers + custom retry count
python3 ./download_memories.py --workers 4 --retries 3
```

## ✨ Features

- ✅ Automatic extraction of all download links
- ✅ Overlay merge for images and videos (if `ffmpeg` is available)
- ✅ Stable naming for processed files
- ✅ Resume logic to avoid duplicates
- ✅ Progress stats and summary
- ✅ Robust error handling

## 📁 Output folders

- `snapchat_memories_processed`: final merged media files
- `snapchat_memories_raw`: extracted raw files

## 📊 File naming

- Files extracted from archives with overlay:
  - `<ID>-processed.mp4`
  - `<ID>-processed.jpg`

- Files downloaded outside archives:
  - `YYYYMMDD_HHMMSS_type.extension`

## ⚠️ Important notes

- Download links expire after a few days
- A 0.5s pause is applied between downloads
- Without `ffmpeg`, video overlays cannot be merged

## 🚀 Faster downloads with workers

You can enable parallel downloads using `--workers`. This speeds up downloads by running multiple requests at once.

Examples:
```bash
# 3 parallel downloads (recommended starting point)
python3 ./download_memories.py --workers 3

# 4 parallel downloads with retries
python3 ./download_memories.py --workers 4 --retries 3
```

Modes:
- Sequential mode (`--workers 1`): downloads one file at a time with a 0.5s pause between files. This is the safest option and the default.
- Parallel mode (`--workers > 1`): downloads multiple files at once. This is faster but can trigger rate limits. If the script detects blocking (HTTP 403/429), it automatically falls back to sequential mode for the remaining files.

## 🆘 Troubleshooting

**"Module not found" error**:
```bash
pip install -r requirements.txt
```

**ffmpeg/ffprobe not found**:
- Install `ffmpeg` via your package manager (brew/apt/choco)

**Expired links**:
- Re-download your data from Snapchat

**Corrupted files**:
- Delete corrupted files and re-run the script

## 📄 License

Free to use for your own Snapchat data.
