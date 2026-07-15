"""
Bulk async orchestrator for FRAM FITS uploads.

Mirrors the shape of the DELPHI template (bulk_async.py): discovers work
items, applies resume logic against an existing stats file, then runs
uploads concurrently under a bounded semaphore.

Differences from the DELPHI case:
  - Work items are FITS files discovered by recursively walking an input
    directory (one record per file; no recid exists before upload).
  - Resume/dedup key is the file's path relative to the input root (e.g.
    "auger2/20260408105436-044-RA.fits"), not an integer recid.
  - No zip / per-record-folder logic; every file is independent.
  - Adds: environment selection (local/test1/production) with a production
    confirmation guard, a circuit breaker that stops starting new uploads
    after too many consecutive failures, graceful shutdown on SIGINT/
    SIGTERM, periodic progress logging, a --dry-run mode (which skips
    repository client setup entirely -- no network/token needed), and a
    startup warning listing any files "interrupted" by a previous crashed
    run (see fram_async_upload.upload_fits_async's docstring for what that
    means and its limits).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import os
import signal
import time
from pathlib import Path

import fram_async_upload

logger = logging.getLogger(__name__)

FITS_EXTENSIONS = (".fits", ".fit", ".fts")
TERMINAL_STATUSES = {"ok", "failed", "skipped_invalid", "dryrun"}


# ============================================================
# DISCOVERY
# ============================================================


def _discover_fits_files(root: Path, sort: bool = True) -> list[Path]:
    """Recursively walk root, returning all FITS files found."""
    files: list[Path] = []
    log_every = 50_000
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if os.path.splitext(name)[1].lower() in FITS_EXTENSIONS:
                files.append(Path(dirpath) / name)
                if len(files) % log_every == 0:
                    logger.info("Discovery in progress: %s FITS files found so far...", len(files))
    if sort:
        files.sort()
    return files


def _relative_key(fits_path: Path, root: Path) -> str:
    """Return the file path relative to the upload root, or after 'Data to upload'."""
    if "Data to upload" in fits_path.parts:
        idx = fits_path.parts.index("Data to upload")
        return Path(*fits_path.parts[idx + 1:]).as_posix()
    return fits_path.relative_to(root).as_posix()


# ============================================================
# RESUME / INTERRUPTED-RUN DETECTION
# ============================================================


def _scan_stats(stats_path: Path) -> tuple[set[str], set[str]]:
    """Return (uploaded_keys, interrupted_keys).

    uploaded_keys: keys with a terminal status == 'ok' -- safe to skip on
    resume.
    interrupted_keys: keys with a 'started' row but no terminal row at all.
    These may have created an orphaned draft record in the repository if
    the previous run crashed between record creation and the final stats
    write. They are re-attempted on resume (this script does not
    deduplicate against the repository itself), but are surfaced as a
    startup warning so they can be checked manually if duplicates are a
    concern.
    """
    if not stats_path.exists():
        return set(), set()

    started: set[str] = set()
    terminal: set[str] = set()
    uploaded: set[str] = set()

    try:
        with stats_path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                key = row.get("key")
                status = str(row.get("status", "")).strip().lower()
                if not key:
                    continue
                if status == "started":
                    started.add(key)
                elif status in TERMINAL_STATUSES:
                    terminal.add(key)
                    if status == "ok":
                        uploaded.add(key)
    except Exception as exc:
        logger.warning("Failed to parse stats file %s: %s", stats_path, exc)
        return set(), set()

    interrupted = started - terminal
    return uploaded, interrupted


# ============================================================
# CIRCUIT BREAKER
# ============================================================


class CircuitBreaker:
    """Stops new uploads from starting after too many consecutive failures.
    Does not cancel work already in flight."""

    def __init__(self, max_consecutive_failures: int):
        self.max_consecutive_failures = max_consecutive_failures
        self._consecutive_failures = 0
        self.tripped = False

    def record_success(self) -> None:
        self._consecutive_failures = 0

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.max_consecutive_failures and not self.tripped:
            self.tripped = True
            logger.error(
                "Circuit breaker tripped after %s consecutive failures -- no new "
                "uploads will be started. Investigate connectivity/auth/schema "
                "before rerunning.",
                self._consecutive_failures,
            )


# ============================================================
# PROGRESS TRACKING
# ============================================================


def _format_eta(seconds: float) -> str:
    if seconds != seconds or seconds == float("inf"):  # NaN or inf
        return "unknown"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m{s:02d}s"


class ProgressTracker:
    def __init__(self, total: int, interval: float):
        self.total = total
        self.interval = interval
        self.done = 0
        self.ok = 0
        self.failed = 0
        self.skipped = 0
        self._last_log = time.monotonic()
        self._start = time.monotonic()

    def record(self, kind: str) -> None:
        self.done += 1
        if kind == "ok":
            self.ok += 1
        elif kind == "failed":
            self.failed += 1
        else:
            self.skipped += 1

        now = time.monotonic()
        if now - self._last_log >= self.interval or self.done == self.total:
            elapsed = now - self._start
            rate = self.done / elapsed if elapsed > 0 else 0.0
            remaining = self.total - self.done
            eta_s = remaining / rate if rate > 0 else float("inf")
            logger.info(
                "Progress: %s/%s done (ok=%s failed=%s skipped=%s) | %.2f files/s | ETA %s",
                self.done, self.total, self.ok, self.failed, self.skipped, rate, _format_eta(eta_s),
            )
            self._last_log = now


# ============================================================
# GRACEFUL SHUTDOWN
# ============================================================


def _request_shutdown(stop_event: asyncio.Event, sig) -> None:
    if not stop_event.is_set():
        logger.warning(
            "Received signal %s -- will not start new uploads; waiting for "
            "in-flight uploads to finish. This may take a while under high "
            "concurrency; use a process manager to force-kill if needed.",
            getattr(sig, "name", sig),
        )
        stop_event.set()


# ============================================================
# PER-FILE RETRY WRAPPER
# ============================================================


async def _upload_with_retries(
    client,
    fits_path: Path,
    relative_key: str,
    stats_path: Path,
    stats_format: str,
    schema_url: str,
    dry_run: bool,
    validate: bool,
    stop_event: asyncio.Event,
    retries: int = 3,
    delay: int = 2,
):
    retries = max(1, retries)
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        if stop_event.is_set():
            logger.info("[%s] Shutdown requested, aborting before attempt %s", relative_key, attempt)
            return None
        try:
            return await fram_async_upload.upload_fits_async(
                client=client,
                fits_path=fits_path,
                relative_key=relative_key,
                stats_path=stats_path,
                stats_format=stats_format,
                dry_run=dry_run,
                validate=validate,
                schema_url=schema_url,
            )
        except Exception as exc:
            last_exc = exc
            logger.warning("[%s] Upload failed (attempt %s/%s): %s", relative_key, attempt, retries, exc)
            if attempt == retries:
                raise
            await asyncio.sleep(delay * attempt)
    raise last_exc  # pragma: no cover -- loop always returns or raises above


# ============================================================
# MAIN
# ============================================================


async def main_async(args: argparse.Namespace) -> None:
    fram_async_upload.setup_logging(log_file=Path(args.log_file) if args.log_file else None)

    if args.token:
        logger.warning(
            "Using --token from the command line; prefer the %s environment "
            "variable to avoid leaking credentials via process listings or "
            "shell history.",
            fram_async_upload.TOKEN_ENV_VAR,
        )

    input_dir = Path(args.input_dir)
    stats_path = Path(args.stats_path)

    if not input_dir.exists():
        logger.error("Input directory does not exist: %s", input_dir)
        return

    # Preflight: validate we can build a client / have a token *before*
    # doing any (potentially very slow) directory discovery. Skipped
    # entirely for --dry-run, which never touches the repository.
    client = None
    if not args.dry_run:
        try:
            client = await fram_async_upload.create_client_for_environment(
                args.environment, token=args.token, confirm_production=not args.yes,
            )
        except Exception as exc:
            logger.error("Preflight failed -- could not create repository client: %s", exc)
            return
    else:
        logger.info("Dry-run mode: no records will be created, uploaded, or published. Skipping repository client setup.")

    all_files = _discover_fits_files(input_dir, sort=not args.no_sort)
    logger.info("FITS files found under %s: %s", input_dir, len(all_files))
    if not all_files:
        logger.info("Nothing to do.")
        return

    keyed = [(f, _relative_key(f, input_dir)) for f in all_files]

    uploaded_keys, interrupted_keys = _scan_stats(stats_path)
    if uploaded_keys:
        before = len(keyed)
        keyed = [(f, k) for f, k in keyed if k not in uploaded_keys]
        logger.info("Resume: skipped %s already uploaded files from %s", before - len(keyed), stats_path)

    if interrupted_keys:
        sample = ", ".join(list(interrupted_keys)[:20])
        logger.warning(
            "%s file(s) have a 'started' stats row from a previous run with no "
            "terminal status -- these may have created orphaned draft records "
            "in the repository if that run crashed mid-upload. They will be "
            "re-attempted now; check the repository for duplicates if this is "
            "a concern. Examples: %s%s",
            len(interrupted_keys), sample, " ..." if len(interrupted_keys) > 20 else "",
        )

    logger.info(
        "Files to upload: %s (environment=%s, max_concurrency=%s, dry_run=%s)",
        len(keyed), args.environment, args.max_concurrency, args.dry_run,
    )

    sem = asyncio.Semaphore(args.max_concurrency)
    breaker = CircuitBreaker(args.max_consecutive_failures)
    progress = ProgressTracker(total=len(keyed), interval=args.progress_interval)
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_shutdown, stop_event, sig)
        except NotImplementedError:
            # add_signal_handler is not available on some platforms
            pass

    start = time.perf_counter()

    async def _run_one(fits_path: Path, relative_key: str):
        async with sem:
            if stop_event.is_set() or breaker.tripped:
                logger.info("[%s] Skipping (shutdown requested or circuit breaker tripped)", relative_key)
                progress.record("skipped")
                return None
            try:
                result = await _upload_with_retries(
                    client=client,
                    fits_path=fits_path,
                    relative_key=relative_key,
                    stats_path=stats_path,
                    stats_format="csv",
                    schema_url=args.schema_url,
                    dry_run=args.dry_run,
                    validate=not args.no_validate,
                    stop_event=stop_event,
                    retries=args.max_retries,
                    delay=args.retry_delay,
                )
                breaker.record_success()
                progress.record("ok" if result is not None else "skipped")
                return result
            except Exception as exc:
                breaker.record_failure()
                progress.record("failed")
                return exc

    tasks = [asyncio.create_task(_run_one(f, k)) for f, k in keyed]
    await asyncio.gather(*tasks, return_exceptions=True)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.remove_signal_handler(sig)
        except NotImplementedError:
            pass

    logger.info(
        "%s finished in %.2fs. total=%s ok=%s failed=%s skipped=%s (see %s for full per-file status)",
        "Dry run" if args.dry_run else "Bulk upload",
        time.perf_counter() - start,
        progress.done, progress.ok, progress.failed, progress.skipped,
        stats_path,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bulk async upload of FRAM FITS files from a directory.")
    parser.add_argument("--input-dir", required=True, help="Root directory to recursively scan for FITS files")
    parser.add_argument(
        "--stats-path",
        default="../stats/upload_stats.csv",
        help="Path to the stats CSV (also used for resume)",
    )
    parser.add_argument("--max-concurrency", type=int, default=4, help="Maximum concurrent uploads")
    parser.add_argument(
        "--environment", choices=sorted(fram_async_upload.ENVIRONMENTS), default="local",
        help="Which repository to upload to (local / test1 / production)",
    )
    parser.add_argument(
        "--schema-url", default=fram_async_upload.DEFAULT_SCHEMA_URL,
        help="Invenio $schema value; confirmed only for local so far -- verify before using with test1/production",
    )
    parser.add_argument(
        "--token", default=None,
        help=f"API token; prefer the {fram_async_upload.TOKEN_ENV_VAR} environment variable over this flag",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Skip the interactive confirmation prompt required for --environment production",
    )
    parser.add_argument("--dry-run", action="store_true", help="Extract & validate metadata but do not create/upload/publish any records")
    parser.add_argument("--no-sort", action="store_true", help="Skip sorting the discovered file list (faster discovery on very large trees)")
    parser.add_argument("--no-validate", action="store_true", help="Disable the minimal required-field check before upload")
    parser.add_argument("--max-consecutive-failures", type=int, default=15, help="Stop starting new uploads after this many consecutive failures")
    parser.add_argument("--max-retries", type=int, default=3, help="Retry attempts per file")
    parser.add_argument("--retry-delay", type=int, default=2, help="Base delay (seconds) between retries; scales with attempt number")
    parser.add_argument("--log-file", default=None, help="Optional rotating log file path, in addition to console output")
    parser.add_argument("--progress-interval", type=float, default=30.0, help="Seconds between progress log lines")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()


### cd FRAM/Scripts/upload

#### python3 fram_bulk_async.py --input-dir "/home/erutherford/Python WSL/FRAM/Upload/Data to upload/cta-n/2021/20210409/03185"

### dry-run test against test1, no repository client touched at all locally
# python3 fram_bulk_async.py \
#   --input-dir "/home/erutherford/Python WSL/FRAM/Upload/Data to upload" \
#   --stats-path "upload_stats.csv" \
#   --environment test1 \
#   --dry-run

### production run (prompts for typed "PRODUCTION" confirmation unless --yes is passed):
# python3 fram_bulk_async.py \
#   --input-dir "/home/erutherford/Python WSL/FRAM/Upload/Data to upload" \
#   --stats-path "upload_stats.csv" \
#   --environment production \
#   --max-concurrency 4



###
