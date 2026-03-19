# Batch Downloader - Technical Sharing

A concurrent batch downloader that handles file hosting pages with ad/redirect protection, resume support, and progress tracking.

## Architecture Overview

```
links.txt                batch_download.py                  downloads/
+-----------+     +-----------------------------+     +------------------+
| URL 1     | --> | main()                      | --> | file_1.zip       |
| URL 2     |     |  +-- parse args             |     | file_2.rar       |
| URL 3     |     |  +-- load progress          |     | file_3.iso       |
| ...       |     |  +-- ThreadPoolExecutor     |     | ...              |
+-----------+     |       |                     |     | progress.json    |
                  |       +-- process_link()    |     | failed_links.txt |
                  |       |    +-- get_download_url()  +------------------+
                  |       |    +-- download_file()
                  |       +-- process_link()
                  |       +-- ...
                  +-----------------------------+
```

## Execution Flow

```
main()
  |
  +-- Parse CLI arguments (argparse)
  +-- Read links.txt
  +-- Load progress from download_progress.json
  +-- Create requests.Session with browser User-Agent
  |
  +-- [concurrent == 1] Sequential Mode
  |     for each link:
  |       safe_process_link(idx, url)
  |
  +-- [concurrent > 1] Parallel Mode
  |     ThreadPoolExecutor(max_workers)
  |       submit safe_process_link(idx, url) for each link
  |       collect results as_completed()
  |
  +-- Print summary
  +-- Save failed_links.txt (if any)
```

## Function Breakdown

### `signal_handler(sig, frame)`

**Line:** 56 | **Purpose:** Graceful shutdown on Ctrl+C

```python
signal.signal(signal.SIGINT, signal_handler)
```

Sets a global `shutdown = True` flag instead of killing the process immediately. All loops and download chunks check this flag, allowing in-progress downloads to finish writing their current chunk before stopping. This prevents file corruption.

---

### `load_progress(output_dir) -> dict`

**Line:** 65 | **Purpose:** Load saved state from disk

Reads `download_progress.json` from the output directory. Returns a dict mapping `page_url -> "done"`. If the file doesn't exist (first run), returns an empty dict.

**Example progress file:**
```json
{
  "https://fuckingfast.co/file/abc123#game_part1.zip": "done",
  "https://fuckingfast.co/file/def456#game_part2.zip": "done"
}
```

---

### `save_progress(output_dir, progress)`

**Line:** 74 | **Purpose:** Persist download state to disk

Writes the progress dict to JSON. Called after each successful download (thread-safe via `progress_lock`). This enables resume across script restarts.

---

### `extract_filename(url) -> str`

**Line:** 81 | **Purpose:** Get the human-readable filename from a URL

The hosting service encodes the filename in the URL fragment (`#`):

```
https://fuckingfast.co/file/abc123#My_Game_Part1.zip
                                   ^^^^^^^^^^^^^^^^^
                                   extracted filename
```

URL-decodes the fragment (`%20` -> space, etc). Falls back to the last path segment if no fragment exists.

---

### `get_download_url(page_url, session, max_retries, retry_delay) -> Optional[str]`

**Line:** 90 | **Purpose:** Navigate ad pages to find the real download link

This is the core anti-ad logic. The hosting service randomly serves:
- **Real page:** Contains `window.open("https://fuckingfast.co/dl/...")` in the HTML
- **Fake page:** Redirects to an ad domain or serves a page without the download button

**Flow:**
```
for attempt in 1..max_retries:
    GET page_url (follow redirects)
    |
    +-- [redirected to different domain?]
    |     -> Ad/fake page. Retry after delay.
    |
    +-- [page has window.open("...fuckingfast.co/dl/...") ?]
    |     -> Real page found! Return the dl/ URL.
    |
    +-- [page loaded but no dl/ URL?]
          -> Soft fake page. Retry after delay.
```

Uses regex pattern matching on the HTML response:
```python
DL_PATTERN = re.compile(r'window\.open\("(https://fuckingfast\.co/dl/[^"]+)"')
```

Returns `None` after exhausting all retries.

---

### `download_file(dl_url, filepath, session) -> bool`

**Line:** 128 | **Purpose:** Download with progress bar and resume support

**Resume logic:**
```
1. Check if file already exists on disk
2. HEAD request to get total file size from server
3. If existing_size >= total_size -> already complete, skip
4. If partial file exists -> send Range header: "bytes={existing_size}-"
5. If server returns 206 (Partial Content) -> append mode ("ab")
6. If server returns 200 (no range support) -> overwrite mode ("wb")
```

**Download loop:**
```
stream response in 1MB chunks:
    for each chunk:
        if shutdown flag set -> return False (graceful stop)
        write chunk to file
        update tqdm progress bar
```

Uses `tqdm` for a terminal progress bar showing speed, ETA, and percentage.

---

### `process_link(idx, total, page_url, ...) -> Tuple[str, bool]`

**Line:** 190 | **Purpose:** Orchestrate the two-step download process for one link

```
1. extract_filename(page_url) -> get the target filename
2. Check progress dict -> skip if already marked "done"
3. get_download_url() -> navigate ad pages to find real URL
4. download_file() -> download with resume support
5. Mark as "done" in progress dict on success
6. Return (filename, success)
```

---

### `main()`

**Line:** 237 | **Purpose:** Entry point - parse args, orchestrate everything

**Step-by-step:**

1. **Parse CLI arguments** - links file, output dir, retry settings, concurrency
2. **Read links.txt** - strips whitespace, skips `#` comments and blank lines
3. **Load progress** - resume from last run
4. **Create session** - `requests.Session()` with persistent browser User-Agent headers
5. **Dispatch work** - sequential or parallel depending on `--concurrent`:

**Sequential mode** (`--concurrent 1`):
```python
for i, url in work_links:
    safe_process_link(i, url)
    time.sleep(args.delay)  # courtesy delay between links
```

**Parallel mode** (`--concurrent N`):
```python
with ThreadPoolExecutor(max_workers=N) as executor:
    # Submit all links as futures
    futures = {executor.submit(safe_process_link, i, url): (i, url) for i, url in work_links}
    # Collect results as they complete
    for future in as_completed(futures):
        idx, url, filename, success = future.result()
```

6. **Print summary** - succeeded/failed/skipped counts
7. **Save failed links** - writes `failed_links.txt` for easy retry

### `safe_process_link(idx, url)` (nested in main)

**Line:** 304 | **Purpose:** Thread-safe wrapper

Calls `process_link()` and uses a `threading.Lock` to safely write progress to disk. Without the lock, concurrent threads writing to `download_progress.json` simultaneously could corrupt the file.

---

## Key Design Patterns

### 1. Retry with Discrimination

Not all failures are equal. The script distinguishes between:
- **Redirect to ad domain** - retry (the real page exists, we just got unlucky)
- **Page loaded but no download URL** - retry (soft fake page)
- **Network error** - retry (transient failure)
- **All retries exhausted** - fail and record

### 2. Progress Persistence

The JSON progress file acts as a simple checkpoint system:
- Each successful download is recorded immediately
- Re-running the script skips completed downloads
- No database needed - just a flat JSON file

### 3. Graceful Shutdown

```
Ctrl+C
  -> signal_handler sets shutdown = True
  -> download loops check flag per chunk (1MB granularity)
  -> current chunk finishes writing (no corruption)
  -> progress is saved for completed files
  -> script exits with summary
```

### 4. HTTP Resume

Uses the standard HTTP `Range` header mechanism:
```
Client: GET /file  Range: bytes=5242880-
Server: 206 Partial Content  Content-Range: bytes 5242880-10485759/10485760
```

Falls back to full re-download if the server doesn't support range requests.

## CLI Usage

```bash
# Basic usage
python batch_download.py

# Custom settings
python batch_download.py --concurrent 3 --max-retries 10 --output-dir ./my_files

# Sequential download starting from link #50
python batch_download.py --concurrent 1 --start-from 50
```

## Dependencies

| Package | Purpose |
|---------|---------|
| `requests` | HTTP client for page fetching and file downloads |
| `tqdm` | Terminal progress bars |

Install: `pip install -r requirements.txt`
