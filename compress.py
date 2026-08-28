#!/usr/bin/env python3
"""
compress.py — Compress PDF files using Ghostscript.

A zero-dependency CLI tool that reduces PDF file sizes through
Ghostscript's built-in optimization presets. Supports single files,
batch processing via globs, and multiple output strategies.

Requirements:
    - Python 3.8+
    - Ghostscript (gs / gswin64c / gswin32c) installed and on PATH

Usage:
    python compress.py report.pdf
    python compress.py *.pdf -q screen -d ./compressed
    python compress.py large.pdf -o small.pdf --overwrite
"""

from __future__ import annotations

__version__ = "1.0.0"
__author__ = "Souhail"

import argparse
import glob
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

QUALITY_PRESETS: dict[str, tuple[str, str]] = {
    "screen":   ("/screen",   "72 dpi  — smallest file, lowest quality"),
    "ebook":    ("/ebook",    "150 dpi — good balance (default)"),
    "printer":  ("/printer",  "300 dpi — high quality, larger file"),
    "prepress": ("/prepress", "300 dpi — color-preserving, largest file"),
}

logger = logging.getLogger("compress")

# ---------------------------------------------------------------------------
# Terminal colors (auto-disabled when output is piped)
# ---------------------------------------------------------------------------

_COLOR_SUPPORTED = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


class _Style:
    """ANSI escape helpers with automatic fallback for non-TTY streams."""

    RESET  = "\033[0m"  if _COLOR_SUPPORTED else ""
    BOLD   = "\033[1m"  if _COLOR_SUPPORTED else ""
    DIM    = "\033[2m"  if _COLOR_SUPPORTED else ""
    GREEN  = "\033[32m" if _COLOR_SUPPORTED else ""
    YELLOW = "\033[33m" if _COLOR_SUPPORTED else ""
    RED    = "\033[31m" if _COLOR_SUPPORTED else ""
    CYAN   = "\033[36m" if _COLOR_SUPPORTED else ""

    @classmethod
    def success(cls, text: str) -> str:
        return f"{cls.GREEN}{text}{cls.RESET}"

    @classmethod
    def warning(cls, text: str) -> str:
        return f"{cls.YELLOW}{text}{cls.RESET}"

    @classmethod
    def error(cls, text: str) -> str:
        return f"{cls.RED}{cls.BOLD}{text}{cls.RESET}"

    @classmethod
    def info(cls, text: str) -> str:
        return f"{cls.CYAN}{text}{cls.RESET}"

    @classmethod
    def dim(cls, text: str) -> str:
        return f"{cls.DIM}{text}{cls.RESET}"


class _Spinner:
    """
    A lightweight terminal spinner that runs in a background thread.

    Usage:
        with _Spinner("Compressing report.pdf"):
            do_work()

    Shows an animated braille spinner with elapsed time on TTY,
    or a single static line when piped.
    """

    _FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    _INTERVAL = 0.08  # seconds between frames

    def __init__(self, message: str) -> None:
        self._message = message
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._start_time = 0.0

    def _spin(self) -> None:
        """Background thread: animate the spinner until stopped."""
        idx = 0
        while not self._stop_event.is_set():
            elapsed = time.monotonic() - self._start_time
            frame = self._FRAMES[idx % len(self._FRAMES)]
            line = f"\r  {_Style.CYAN}{frame}{_Style.RESET} {self._message} {_Style.dim(f'{elapsed:.1f}s')}"
            sys.stdout.write(line)
            sys.stdout.flush()
            idx += 1
            self._stop_event.wait(self._INTERVAL)

    def __enter__(self) -> "_Spinner":
        self._start_time = time.monotonic()
        if _COLOR_SUPPORTED:
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
        else:
            # Non-TTY: print a static line
            sys.stdout.write(f"  Compressing... {self._message}\n")
            sys.stdout.flush()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join()
        # Clear the spinner line
        if _COLOR_SUPPORTED:
            sys.stdout.write("\r" + " " * 80 + "\r")
            sys.stdout.flush()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._start_time


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def find_ghostscript() -> str:
    """Locate a Ghostscript binary on PATH, or exit with install guidance."""
    for exe in ("gs", "gswin64c", "gswin32c"):
        path = shutil.which(exe)
        if path:
            logger.debug("Found Ghostscript: %s", path)
            return path

    sys.exit(
        _Style.error("Error: Ghostscript not found.") + "\n"
        "Install it for your platform:\n"
        "  macOS   → brew install ghostscript\n"
        "  Ubuntu  → sudo apt install ghostscript\n"
        "  Windows → https://ghostscript.com/releases/gsdnld.html"
    )


def human_size(num_bytes: int) -> str:
    """Format a byte count into a human-readable string (e.g. 2.4 MB)."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def compress_pdf(
    input_path: Path,
    output_path: Path,
    quality: str,
    gs_bin: str,
    *,
    quiet: bool = False,
) -> float:
    """
    Compress a single PDF via Ghostscript.

    Writes to a temporary file first, then atomically moves to the
    final destination so a crash never leaves a corrupt output.

    Returns the elapsed wall-clock time in seconds.
    """
    setting = QUALITY_PRESETS[quality][0]

    # Write to a temp file in the same directory (ensures same filesystem
    # for an atomic os.replace later).
    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(suffix=".pdf", dir=output_dir)
    os.close(fd)

    try:
        cmd = [
            gs_bin,
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.4",
            f"-dPDFSETTINGS={setting}",
            "-dNOPAUSE",
            "-dQUIET",
            "-dBATCH",
            "-dSAFER",
            f"-sOutputFile={tmp_path}",
            str(input_path),
        ]
        logger.debug("Running: %s", " ".join(cmd))

        spinner_msg = f"Compressing {_Style.BOLD}{input_path.name}{_Style.RESET}"
        if quiet:
            # No spinner, just run
            result = subprocess.run(cmd, capture_output=True, text=True)
            elapsed = 0.0
        else:
            with _Spinner(spinner_msg) as spinner:
                result = subprocess.run(cmd, capture_output=True, text=True)
                elapsed = spinner.elapsed

        if result.returncode != 0:
            raise RuntimeError(
                f"Ghostscript exited with code {result.returncode}:\n"
                f"{result.stderr.strip()}"
            )

        # Atomic move → final destination
        os.replace(tmp_path, output_path)
        return elapsed

    except Exception:
        # Clean up the temp file on any failure
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


# ---------------------------------------------------------------------------
# Output path resolution
# ---------------------------------------------------------------------------

def resolve_output_path(
    input_path: Path,
    *,
    output: Path | None,
    output_dir: Path | None,
    suffix: str,
    overwrite: bool,
) -> Path:
    """Determine the output path for a given input file."""
    if output:
        out = output
    elif output_dir:
        out = output_dir / input_path.name
    else:
        out = input_path.with_stem(f"{input_path.stem}{suffix}")

    # Safety: refuse to silently clobber the input unless --overwrite is set
    if out.resolve() == input_path.resolve() and not overwrite:
        sys.exit(
            _Style.error(f"Error: output would overwrite '{input_path}'.") + "\n"
            "Use --overwrite / -f to allow in-place compression."
        )

    return out


# ---------------------------------------------------------------------------
# CLI definition
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser with polished help text."""
    # Build the quality choices description for the epilog
    preset_lines = "\n".join(
        f"    {name:<10} {desc}" for name, (_, desc) in QUALITY_PRESETS.items()
    )

    parser = argparse.ArgumentParser(
        prog="compress",
        description="Compress PDF files using Ghostscript.",
        epilog=f"Quality presets:\n{preset_lines}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "files",
        nargs="+",
        metavar="FILE",
        help="PDF file(s) to compress (shell globs supported)",
    )

    output_group = parser.add_argument_group("output options")
    output_group.add_argument(
        "-o", "--output",
        metavar="PATH",
        help="explicit output path (single-file mode only)",
    )
    output_group.add_argument(
        "-d", "--output-dir",
        metavar="DIR",
        help="write all compressed files into DIR",
    )
    output_group.add_argument(
        "-s", "--suffix",
        default="_compressed",
        metavar="TEXT",
        help="suffix for auto-generated filenames (default: _compressed)",
    )
    output_group.add_argument(
        "-f", "--overwrite",
        action="store_true",
        help="allow overwriting the original input file",
    )

    compress_group = parser.add_argument_group("compression")
    compress_group.add_argument(
        "-q", "--quality",
        choices=QUALITY_PRESETS.keys(),
        default="ebook",
        metavar="PRESET",
        help="compression preset: screen, ebook (default), printer, prepress",
    )

    misc_group = parser.add_argument_group("miscellaneous")
    misc_group.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="show what would be done without writing files",
    )
    misc_group.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="enable debug logging",
    )
    misc_group.add_argument(
        "--quiet",
        action="store_true",
        help="suppress all output except errors",
    )
    misc_group.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    return parser


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    args = build_parser().parse_args()

    # Configure logging
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")
    elif not args.quiet:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
    else:
        logging.basicConfig(level=logging.ERROR, format="%(message)s")

    # Locate Ghostscript
    gs_bin = find_ghostscript()

    # Expand globs (needed on Windows; harmless on Unix)
    files: list[Path] = []
    for pattern in args.files:
        matches = glob.glob(pattern)
        if matches:
            files.extend(Path(m) for m in matches)
        else:
            files.append(Path(pattern))

    if not files:
        sys.exit(_Style.error("No matching PDF files found."))

    # --output is single-file only
    if args.output and len(files) > 1:
        sys.exit(_Style.error("Error: --output can only be used with a single input file."))

    output_path_arg = Path(args.output) if args.output else None
    output_dir_arg = Path(args.output_dir) if args.output_dir else None

    # ── Processing loop ───────────────────────────────────────────────
    start_time = time.monotonic()
    total_before = 0
    total_after = 0
    processed = 0
    skipped = 0
    total = len(files)

    for idx, input_path in enumerate(files, start=1):
        prefix = f"[{idx}/{total}]" if total > 1 else "•"

        if not input_path.is_file():
            print(f"{prefix} {_Style.warning('skip')} {input_path}  (not found)")
            skipped += 1
            continue

        if not input_path.suffix.lower() == ".pdf":
            print(f"{prefix} {_Style.warning('skip')} {input_path}  (not a PDF)")
            skipped += 1
            continue

        before = input_path.stat().st_size

        output = resolve_output_path(
            input_path,
            output=output_path_arg,
            output_dir=output_dir_arg,
            suffix=args.suffix,
            overwrite=args.overwrite,
        )

        if args.dry_run:
            print(
                f"{prefix} {_Style.info('dry-run')} "
                f"{input_path} {_Style.dim(f'({human_size(before)})')} → {output}  "
                f"{_Style.dim(f'[{args.quality}]')}"
            )
            continue

        # Show what we're about to compress
        if not args.quiet:
            print(
                f"{prefix} {_Style.info('┌')} "
                f"{_Style.BOLD}{input_path.name}{_Style.RESET}  "
                f"{_Style.dim(f'{human_size(before)} · {args.quality} preset')}"
            )

        try:
            elapsed = compress_pdf(
                input_path, output, args.quality, gs_bin, quiet=args.quiet,
            )
        except RuntimeError as exc:
            print(f"{prefix} {_Style.error('└ ✗ fail')} {input_path}")
            logger.error("  %s", exc)
            skipped += 1
            continue
        except PermissionError:
            print(f"{prefix} {_Style.error('└ ✗ fail')} {input_path}  (permission denied)")
            skipped += 1
            continue

        after = output.stat().st_size
        ratio = (1 - after / before) * 100 if before else 0.0

        total_before += before
        total_after += after
        processed += 1

        # Color the ratio: green if smaller, yellow if larger
        ratio_str = f"{ratio:+.1f}%"
        if ratio > 0:
            ratio_colored = _Style.success(ratio_str)
        else:
            ratio_colored = _Style.warning(ratio_str)

        if not args.quiet:
            print(
                f"{prefix} {_Style.success('└ ✓ done')} "
                f"{human_size(before)} → {human_size(after)}  "
                f"{ratio_colored}  "
                f"{_Style.dim(f'{elapsed:.1f}s · {output}')}"
            )

    # ── Summary ───────────────────────────────────────────────────────
    elapsed = time.monotonic() - start_time

    if args.dry_run:
        print(f"\n{_Style.info('Dry run complete.')} No files were modified.")
        return

    if processed == 0:
        return

    if total > 1 and not args.quiet:
        total_ratio = (1 - total_after / total_before) * 100 if total_before else 0.0
        parts = [
            f"\n{'─' * 50}",
            f"  {_Style.BOLD}Processed:{_Style.RESET} {processed} file{'s' if processed != 1 else ''}",
        ]
        if skipped:
            parts.append(f"  {_Style.warning('Skipped:')}   {skipped}")
        parts.extend([
            f"  {_Style.BOLD}Saved:{_Style.RESET}     {human_size(total_before)} → {human_size(total_after)}  ({total_ratio:+.1f}%)",
            f"  {_Style.BOLD}Time:{_Style.RESET}      {elapsed:.1f}s",
        ])
        print("\n".join(parts))


if __name__ == "__main__":
    main()