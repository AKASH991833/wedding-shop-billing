# Packaging (planned, not yet verified)

- Run from source: `pip install -r requirements.txt && python app/main.py`
- Windows build: `pyinstaller --windowed --name ShopBilling app/main.py` (one-dir recommended; one-file is slower to start).
- Installer: Inno Setup over the one-dir output.
- Honest status: the app runs and is tested on Linux (headless + offscreen). A Windows
  build has NOT been produced or tested yet - PyInstaller/Inno output must be verified
  on a real Windows PC before any installer claim.
- Data: SQLite file at ~/.wedding_shop_billing/shop.db; Backup page copies timestamped
  backups; auto-backup on every exit. Restore replaces the DB file (user confirmed).
- Known next iteration: store bill dates as ISO internally (display format stays
  "31 Oct 2026") so date-range reports and rental availability work on any entry.
