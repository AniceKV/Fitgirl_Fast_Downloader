# Fitgirl_Fast_Downloader

Batch downloader for fuckingfast.co file hosting links with concurrent downloads, resume support, and ad-page bypass.

## Features

- Concurrent downloads (configurable, default: 5 workers)
- Auto-retry on ad/redirect pages
- Resume interrupted downloads (HTTP Range)
- Progress tracking across restarts (JSON checkpoint)
- Graceful shutdown (Ctrl+C finishes current downloads)

## Setup

```bash
pip install -r requirements.txt
```

## Usage

1. Create a `links.txt` file with one URL per line
2. Run:

```bash
python batch_download.py
```

### Options

```
--links-file FILE     Input file (default: links.txt)
--output-dir DIR      Download directory (default: downloads)
--concurrent N        Parallel downloads (default: 5)
--max-retries N       Retry attempts per link (default: 5)
--retry-delay SECS    Delay between retries (default: 3.0)
--delay SECS          Delay between links (default: 1.0)
--start-from N        Start from Nth link (default: 1)
```

### Examples

```bash
# Download with 3 workers
python batch_download.py --concurrent 3

# Sequential download, start from link #50
python batch_download.py --concurrent 1 --start-from 50

# Custom output directory
python batch_download.py --output-dir ./my_files
```

## How It Works

See [TECHNICAL_SHARING.md](TECHNICAL_SHARING.md) for a detailed technical breakdown.
