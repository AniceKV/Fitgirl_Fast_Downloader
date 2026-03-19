#!/usr/bin/env python3
"""
Batch downloader for fuckingfast.co links.

Usage:
    python batch_download.py [--output-dir DIR] [--max-retries N] [--concurrent N]

Reads links from links.txt (one per line), visits each page to extract
the real download URL, and downloads the file. If a link redirects to
a fake/ad page (no DOWNLOAD button), it retries automatically.
"""

import os
import re
import sys
import time
import argparse
import signal
import json
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import unquote
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import requests
except ImportError:
    print("Installing requests...")
    os.system(f"{sys.executable} -m pip install requests -q")
    import requests

try:
    from tqdm import tqdm
except ImportError:
    print("Installing tqdm...")
    os.system(f"{sys.executable} -m pip install tqdm -q")
    from tqdm import tqdm


# ── Config ──────────────────────────────────────────────────────────────
PROGRESS_FILE = "download_progress.json"
REAL_DOMAIN = "fuckingfast.co"
DL_PATTERN = re.compile(r'window\.open\("(https://fuckingfast\.co/dl/[^"]+)"')
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# Graceful shutdown
shutdown = False


def signal_handler(sig, frame):
    global shutdown
    print("\n[!] Shutdown requested, finishing current downloads...")
    shutdown = True


signal.signal(signal.SIGINT, signal_handler)


def load_progress(output_dir: str) -> dict:
    """Load download progress from JSON file."""
    path = os.path.join(output_dir, PROGRESS_FILE)
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {}


def save_progress(output_dir: str, progress: dict):
    """Save download progress to JSON file."""
    path = os.path.join(output_dir, PROGRESS_FILE)
    with open(path, "w") as f:
        json.dump(progress, f, indent=2)


def extract_filename(url: str) -> str:
    """Extract filename from the fuckingfast.co URL fragment."""
    if "#" in url:
        return unquote(url.split("#", 1)[1])
    # Fallback: use the file ID
    parts = url.rstrip("/").split("/")
    return parts[-1]


def get_download_url(page_url: str, session: requests.Session, max_retries: int, retry_delay: float) -> Optional[str]:
    """
    Visit the fuckingfast.co page and extract the real download URL.

    Returns None if all retries fail (keeps hitting fake/ad pages).
    The real page has: window.open("https://fuckingfast.co/dl/...")
    The fake page either redirects away from fuckingfast.co or lacks that pattern.
    """
    for attempt in range(1, max_retries + 1):
        if shutdown:
            return None
        try:
            resp = session.get(page_url, timeout=30, allow_redirects=True)

            # Check 1: Were we redirected to a different domain? (fake page)
            if REAL_DOMAIN not in resp.url:
                print(f"  [Redirect] Attempt {attempt}/{max_retries} - "
                      f"Redirected to {resp.url[:60]}... retrying")
                time.sleep(retry_delay)
                continue

            # Check 2: Does the page have the real download button/URL?
            match = DL_PATTERN.search(resp.text)
            if match:
                return match.group(1)

            # No download URL found (might be a soft fake or error)
            print(f"  [No DL URL] Attempt {attempt}/{max_retries} - "
                  f"Page loaded but no download URL found, retrying")
            time.sleep(retry_delay)

        except requests.RequestException as e:
            print(f"  [Error] Attempt {attempt}/{max_retries} - {e}, retrying")
            time.sleep(retry_delay)

    return None


def download_file(dl_url: str, filepath: str, session: requests.Session) -> bool:
    """Download file from the direct dl/ URL with progress bar and resume support."""
    # Check existing file size for resume
    existing_size = 0
    if os.path.exists(filepath):
        existing_size = os.path.getsize(filepath)

    # Get total file size
    try:
        head = session.head(dl_url, timeout=30)
        total_size = int(head.headers.get("content-length", 0))
    except Exception:
        total_size = 0

    # Skip if already fully downloaded
    if total_size > 0 and existing_size >= total_size:
        return True

    # Set up resume headers
    headers = {}
    if existing_size > 0 and total_size > 0:
        headers["Range"] = f"bytes={existing_size}-"
        print(f"  Resuming from {existing_size / 1024 / 1024:.1f} MB")

    try:
        resp = session.get(dl_url, stream=True, timeout=60, headers=headers)

        # If server doesn't support range, start over
        if existing_size > 0 and resp.status_code != 206:
            existing_size = 0

        mode = "ab" if existing_size > 0 and resp.status_code == 206 else "wb"
        dl_size = int(resp.headers.get("content-length", 0))
        desc = os.path.basename(filepath)
        if len(desc) > 40:
            desc = desc[:37] + "..."

        with open(filepath, mode) as f:
            with tqdm(
                total=dl_size,
                initial=0,
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
                desc=desc,
                leave=True,
                ncols=80,
            ) as bar:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):  # 1MB chunks
                    if shutdown:
                        return False
                    if chunk:
                        f.write(chunk)
                        bar.update(len(chunk))

        return True

    except requests.RequestException as e:
        print(f"  [Download Error] {e}")
        return False


def process_link(
    idx: int,
    total: int,
    page_url: str,
    output_dir: str,
    session: requests.Session,
    max_retries: int,
    retry_delay: float,
    progress: dict,
) -> Tuple[str, bool]:
    """Process a single link: extract download URL and download the file."""
    filename = extract_filename(page_url)

    if shutdown:
        return filename, False

    # Skip if already downloaded
    if progress.get(page_url) == "done":
        filepath = os.path.join(output_dir, filename)
        if os.path.exists(filepath):
            print(f"[{idx}/{total}] SKIP (already done): {filename}")
            return filename, True

    print(f"\n[{idx}/{total}] Processing: {filename}")
    print(f"  Page: {page_url}")

    # Step 1: Get real download URL
    dl_url = get_download_url(page_url, session, max_retries, retry_delay)
    if not dl_url:
        print(f"  [FAILED] Could not get download URL after {max_retries} attempts")
        return filename, False

    print(f"  DL URL obtained: {dl_url[:70]}...")

    # Step 2: Download the file
    filepath = os.path.join(output_dir, filename)
    success = download_file(dl_url, filepath, session)

    if success:
        progress[page_url] = "done"
        print(f"  [OK] Downloaded: {filename}")
    else:
        print(f"  [FAILED] Download failed: {filename}")

    return filename, success


def main():
    parser = argparse.ArgumentParser(description="Batch download from fuckingfast.co links")
    parser.add_argument(
        "--links-file", default="links.txt",
        help="File containing links, one per line (default: links.txt)"
    )
    parser.add_argument(
        "--output-dir", default="downloads",
        help="Output directory for downloads (default: downloads)"
    )
    parser.add_argument(
        "--max-retries", type=int, default=5,
        help="Max retries when hitting fake/redirect pages (default: 5)"
    )
    parser.add_argument(
        "--retry-delay", type=float, default=3.0,
        help="Delay in seconds between retries (default: 3.0)"
    )
    parser.add_argument(
        "--delay", type=float, default=1.0,
        help="Delay between each link processing (default: 1.0)"
    )
    parser.add_argument(
        "--concurrent", type=int, default=5,
        help="Max parallel downloads (default: 5, set to 1 for sequential)"
    )
    parser.add_argument(
        "--start-from", type=int, default=1,
        help="Start from Nth link (1-based, default: 1)"
    )
    args = parser.parse_args()

    # Read links
    links_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.links_file)
    if not os.path.exists(links_path):
        print(f"Error: {links_path} not found. Create it with one URL per line.")
        sys.exit(1)

    with open(links_path) as f:
        links = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    print(f"Loaded {len(links)} links from {args.links_file}")

    # Create output dir
    os.makedirs(args.output_dir, exist_ok=True)

    # Load progress
    progress = load_progress(args.output_dir)
    already_done = sum(1 for url in links if progress.get(url) == "done")
    print(f"Already completed: {already_done}/{len(links)}")

    # Create session
    session = requests.Session()
    session.headers.update(HEADERS)

    # Process links
    succeeded = 0
    failed = 0
    failed_links = []

    start_idx = max(1, args.start_from)
    work_links = list(enumerate(links[start_idx - 1:], start=start_idx))
    max_workers = max(1, args.concurrent)

    import threading
    progress_lock = threading.Lock()

    def safe_process_link(idx, url):
        """Thread-safe wrapper around process_link."""
        filename, success = process_link(
            idx=idx,
            total=len(links),
            page_url=url,
            output_dir=args.output_dir,
            session=session,
            max_retries=args.max_retries,
            retry_delay=args.retry_delay,
            progress=progress,
        )
        if success:
            with progress_lock:
                save_progress(args.output_dir, progress)
        return idx, url, filename, success

    if max_workers == 1:
        # Sequential mode
        for i, url in work_links:
            if shutdown:
                print("\n[!] Shutting down gracefully...")
                break
            _, _, filename, success = safe_process_link(i, url)
            if success:
                succeeded += 1
            else:
                failed += 1
                failed_links.append((i, url, filename))
            if i < len(links) and not shutdown:
                time.sleep(args.delay)
    else:
        # Parallel mode
        print(f"Downloading with {max_workers} parallel workers")
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for i, url in work_links:
                if shutdown:
                    break
                future = executor.submit(safe_process_link, i, url)
                futures[future] = (i, url)

            for future in as_completed(futures):
                if shutdown:
                    break
                idx, url, filename, success = future.result()
                if success:
                    succeeded += 1
                else:
                    failed += 1
                    failed_links.append((idx, url, filename))

    # Summary
    print("\n" + "=" * 60)
    print(f"SUMMARY: {succeeded} succeeded, {failed} failed, {len(links) - succeeded - failed} skipped")
    if failed_links:
        print("\nFailed links:")
        for idx, url, fname in failed_links:
            print(f"  [{idx}] {fname}")
            print(f"       {url}")
        # Save failed links to file
        failed_file = os.path.join(args.output_dir, "failed_links.txt")
        with open(failed_file, "w") as f:
            for _, url, _ in failed_links:
                f.write(url + "\n")
        print(f"\nFailed links saved to: {failed_file}")
        print("Re-run the script to retry failed links (completed ones will be skipped)")
    print("=" * 60)


if __name__ == "__main__":
    main()
