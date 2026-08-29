# Shrink PDF Compressor

A fast, zero-dependency CLI tool to compress PDF files using [Ghostscript](https://ghostscript.com).

Supports single files, batch processing, multiple quality presets, dry-run previews, and in-place overwriting — all from a single Python script.

## Features

- **Four quality presets** — from `screen` (72 dpi) to `prepress` (300 dpi, color-preserving)
- **Batch processing** — compress hundreds of PDFs in one command with a `[1/N]` progress counter
- **Dry-run mode** — preview what would happen without writing any files
- **In-place overwrite** — safely replace originals with `--overwrite`
- **Atomic writes** — output is written to a temp file first, so a crash never corrupts your data
- **Colored output** — green/yellow/red status in the terminal, auto-disabled when piped
- **Cross-platform** — works on macOS, Linux, and Windows
- **Zero Python dependencies** — only the standard library + Ghostscript

## Requirements

| Requirement  | Version |
|-------------|---------|
| Python      | 3.8+    |
| Ghostscript | any     |

### Install Ghostscript

```bash
# macOS
brew install ghostscript

# Ubuntu / Debian
sudo apt install ghostscript

# Windows — download from:
# https://ghostscript.com/releases/gsdnld.html
```

## Installation

```bash
git clone https://github.com/<your-username>/pdf-compressor.git
cd pdf-compressor
pip install .
```

That's it — `compress` is now available as a command from anywhere.

## Usage

### Compress a single file

```bash
compress report.pdf
# → report_compressed.pdf
```

### Custom output path

```bash
compress report.pdf -o small_report.pdf
```

### Batch compress into a directory

```bash
compress *.pdf -d ./compressed
```

### Choose a quality preset

```bash
compress report.pdf -q screen    # smallest, 72 dpi
compress report.pdf -q printer   # high quality, 300 dpi
```

### Preview with dry-run

```bash
compress *.pdf -q screen --dry-run
```

### Overwrite the original file

```bash
compress report.pdf -o report.pdf --overwrite
```

### Custom filename suffix

```bash
compress report.pdf -s _small
# → report_small.pdf
```

## Quality Presets

| Preset     | DPI  | Description                          |
|-----------|------|--------------------------------------|
| `screen`   | ~72  | Smallest file, lowest quality        |
| `ebook`    | ~150 | Good balance **(default)**           |
| `printer`  | ~300 | High quality, larger file            |
| `prepress` | ~300 | Color-preserving, largest file       |

## CLI Reference

```
usage: compress [-h] [-o PATH] [-d DIR] [-s TEXT] [-f] [-q PRESET]
                [-n] [-v] [--quiet] [--version]
                FILE [FILE ...]

Compress PDF files using Ghostscript.

positional arguments:
  FILE                  PDF file(s) to compress (shell globs supported)

output options:
  -o, --output PATH     explicit output path (single-file mode only)
  -d, --output-dir DIR  write all compressed files into DIR
  -s, --suffix TEXT     suffix for auto-generated filenames (default: _compressed)
  -f, --overwrite       allow overwriting the original input file

compression:
  -q, --quality PRESET  compression preset: screen, ebook (default), printer, prepress

miscellaneous:
  -n, --dry-run         show what would be done without writing files
  -v, --verbose         enable debug logging
  --quiet               suppress all output except errors
  --version             show program's version number and exit
```

## License

[MIT](LICENSE)
