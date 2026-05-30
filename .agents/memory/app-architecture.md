---
name: App architecture
description: Key facts about this project's runtime environment and deployment model
---

This is a **Windows 11 desktop app** (PySide6/Qt + SQLite). It is developed in Replit but exported and run locally on Windows.

**Why:** The user runs it on their own machine. It was imported to Replit only for development.

**How to apply:**
- Do not add web server components or web-facing features
- File paths and folder creation use the local filesystem (currently defaults to ~/mission_data; on Windows it will use the MISSIONS_ROOT env var or the OneDrive path)
- winotify (Windows notifications) was removed from requirements — do not re-add for Linux; it's fine to add back conditionally for Windows export
- In Replit VNC workflow the command must be `DISPLAY=:1 python main.py` — the app renders on display :1 (VNC), not :0 (default shell display)
