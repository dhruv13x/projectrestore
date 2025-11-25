<div align="center">
  <img src="https://raw.githubusercontent.com/dhruv13x/projectrestore/main/projectrestore_logo.png" alt="projectrestore logo" width="200"/>
</div>

<div align="center">

<!-- Package Info -->
[![PyPI version](https://img.shields.io/pypi/v/projectrestore.svg)](https://pypi.org/project/projectrestore/)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
![Wheel](https://img.shields.io/pypi/wheel/projectrestore.svg)
[![Release](https://img.shields.io/badge/release-PyPI-blue)](https://pypi.org/project/projectrestore/)

<!-- Build & Quality -->
[![Build status](https://github.com/dhruv13x/projectrestore/actions/workflows/publish.yml/badge.svg)](https://github.com/dhruv13x/projectrestore/actions/workflows/publish.yml)
[![Codecov](https://codecov.io/gh/dhruv13x/projectrestore/graph/badge.svg)](https://codecov.io/gh/dhruv13x/projectrestore)
[![Test Coverage](https://img.shields.io/badge/coverage-90%25%2B-brightgreen.svg)](https://github.com/dhruv13x/projectrestore/actions/workflows/test.yml)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Ruff](https://img.shields.io/badge/linting-ruff-yellow.svg)](https://github.com/astral-sh/ruff)
![Security](https://img.shields.io/badge/security-CodeQL-blue.svg)

<!-- Usage -->
![Downloads](https://img.shields.io/pypi/dm/projectrestore.svg)
![OS](https://img.shields.io/badge/os-Linux%20%7C%20macOS%20%7C%20Windows-blue.svg)
[![Python Versions](https://img.shields.io/pypi/pyversions/projectrestore.svg)](https://pypi.org/project/projectrestore/)

<!-- License -->
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

<!-- Docs -->
[![Docs](https://img.shields.io/badge/docs-latest-brightgreen.svg)](https://your-docs-link)

</div>


# 🛠️ projectrestore — Secure, Atomic, Verified Project Restore

**projectrestore** is the companion tool to  
[`projectclone`](https://github.com/dhruv13x/projectclone).

It safely restores project backups created via `projectclone` — with **strict safety guarantees**, atomic replacement, rollback, checksum verification, PID locking, and tar-bomb protection.

> **Mission:** Restore project environments safely, predictably, and without trust assumptions — even across systems.

---

## ✅ Key Features

| Capability | Description |
|----------|-------------|
🔐 **Atomic restore** | Extracts to temp dir → atomic swap → rollback if failed  
🛡️ **Zero-trust archive validation** | Rejects suspicious tar entries (symlink, device, traversal)  
📦 **Tarbomb protection** | Max-files & max-bytes enforcement  
🧾 **SHA-256 integrity check** | Optional digest validation before restore  
🚫 **Privilege-safe** | Strip `setuid/setgid`, block device nodes  
🔄 **Dry-run validation** | Verify archives without touching disk  
🔒 **PID locking** | Prevent concurrent restores  
🧯 **Crash-safe** | Best-effort rollback & cleanup  
📁 **Cross-platform** | Works on Linux, Termux/Android, VPS, containers  
⚡ **No dependencies** | Pure Python — clean install, small footprint

---

## 🧩 Installation

```sh
pip install projectrestore

Or editable dev install:

git clone https://github.com/dhruv13x/projectrestore
cd projectrestore
pip install -e .


---
🚀 Quick Start

### 1. Restore the Latest Backup
Finds the newest `.tar.gz` in the default directory and restores it.
```sh
projectrestore
```

### 2. Restore to a Specific Directory
```sh
projectrestore --backup-dir ~/project_backups --extract-dir ./my_restored_project
```

### 3. Dry-Run Validation
Verify an archive's integrity without writing any files.
```sh
projectrestore --dry-run
```

### 4. Restore with SHA-256 Verification
Ensure the backup hasn't been corrupted or tampered with.
```sh
projectrestore --checksum checksums.txt
```

### 5. Tarbomb-Protected Restore
Set limits to prevent malicious archives from filling up your disk.
```sh
projectrestore --max-files 10000 --max-bytes 1G
```

### 6. Debug Mode
For verbose output during troubleshooting.
```sh
projectrestore --debug
```

---

## ⚙️ Configuration & Advanced Usage

Customize behavior with these command-line arguments.

| Argument | Short | Default | Description |
|---|---|---|---|
| `--backup-dir` | `-b` | `/sdcard/project_backups` | Directory containing backups. |
| `--extract-dir`| `-e` | `BACKUP_DIR/tmp_extract` | Extraction target directory. |
| `--pattern` | `-p` | `*-bot_platform-*.tar.gz` | Glob pattern to match backups. |
| `--lockfile` | `-l` | `/tmp/extract_backup.pid` | PID file for locking. |
| `--checksum` | `-c` | `None` | Optional SHA-256 checksum file. |
| `--stale-seconds`| | `3600` | Seconds before a lock is stale. |
| `--debug` | | `False` | Enable debug logging. |
| `--max-files` | | `None` | Max files to extract (tarbomb protection). |
| `--max-bytes` | | `None` | Max bytes to extract (tarbomb protection). |
| `--allow-pax` | | `False` | Allow pax/global headers (skipped by default). |
| `--allow-sparse`| | `False` | Allow GNU sparse members (disabled by default). |
| `--dry-run` | | `False` | Validate archive without writing files. |
| `--version` | | | Show version and exit. |


---

🔍 How It Works (Safety Model)

1. Validate backup archive structure & metadata


2. Create PID lock → single-instance safety


3. Extract to isolated temporary directory


4. Apply strict checks:

No absolute paths

No ../ traversal

No symlinks / hardlinks

No device nodes / FIFO

No setuid/setgid preserved



5. Optionally verify SHA-256


6. Atomic swap:

Move old dir → backup

Move new dir → destination



7. Cleanup old state (or rollback on error)




---

⚠️ Design Philosophy

> Separation of responsibilities
projectclone = capture
projectrestore = apply safely



This tool intentionally does not share codebase or execution surface with projectclone to ensure:

Security isolation

Clear trust boundary

Maintenance clarity

Lower blast radius

Independent versioning & release trains



---

🧪 Exit Codes

Code	Meaning

0	Success
1	Error
2	Interrupted / signal
3	Another instance running (PID lock)



---

📂 Compatibility

System	Supported

Linux	✅
WSL	✅
Termux / Android	✅
Docker	✅
macOS	⚠️ tar behavior varies — full support in v1.0



---

🏗️ Architecture

```
src/projectrestore/
├── cli.py          # Main entry point, CLI argument parsing
├── banner.py       # ASCII art
└── modules/
    ├── __init__.py
    ├── checksum.py   # SHA-256 verification logic
    ├── extraction.py # Core extraction and safety checks
    ├── locking.py    # PID-based locking
    ├── signals.py    # Graceful shutdown handling
    └── utils.py      # Helper functions
```

The tool is organized into a `cli.py` entrypoint that handles user input and a `modules` directory containing specialized components for each core function, promoting separation of concerns.

---

🤝 Ecosystem

Tool	Purpose

projectclone	Create stateful reproducible project snapshots
projectrestore	Securely apply snapshots with verification & rollback


These tools form a reproducible project state suite.


---

🗺️ Roadmap

For a detailed view of our future plans, please see our official [ROADMAP.md](ROADMAP.md).



---

✅ Requirements

Python 3.8+

Tar archives built by projectclone



---

📜 License

MIT — free, open, audit-friendly, production-safe.


---

👨‍💻 Author

Dhruv — dhruv13x@gmail.com
Designed for reproducibility, disaster-recovery, and zero-trust restore paths.


---

> ⭐️ If this project saves your work or your sanity, consider starring the repo!
Issues & PRs welcome — security mindset first.



---
