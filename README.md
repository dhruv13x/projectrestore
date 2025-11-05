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

Restore the latest backup made by projectclone:

projectrestore

Restore to a specific directory:

projectrestore --backup-dir ~/project_backups --extract-dir ./restored_project

Dry-run (validate only):

projectrestore --dry-run

Verify SHA-256 before restore:

projectrestore --checksum checksums.txt

Limit archive extraction:

projectrestore --max-files 50000 --max-bytes 2G

Debug logs:

projectrestore --debug


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

🤝 Ecosystem

Tool	Purpose

projectclone	Create stateful reproducible project snapshots
projectrestore	Securely apply snapshots with verification & rollback


These tools form a reproducible project state suite.


---

📦 Future Roadmap

Interactive restore preview (file diff, size, changeset)

Restore-to-new-path mode

Encrypted backup support

Signature verification (public key)

macOS hardened extractor extension



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
