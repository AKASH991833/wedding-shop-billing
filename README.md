# wedding-shop-billing
Clothing sale + rental and wedding orders billing software - design samples with demo data

## Web design sample (GitHub Pages)
Live preview: https://akash991833.github.io/wedding-shop-billing/
`index.html` - mobile + desktop design preview. Demo data only; entries last for the browser session.

## Desktop app (prototype)
`desktop/` - Python + PySide6 + SQLite PC billing app (prototype, in development).
- Dashboard, records with CSV export, new bill (sale / rental with per-day pricing / wedding order), invoice preview with print-to-PDF, verified local backups
- SQLite data layer: customers, bills, payments, refundable deposits (separate from revenue), rental returns, inventory availability, customer ledger, date reports
- Run from source: `pip install -r desktop/requirements.txt && python desktop/app/main.py`
- Windows packaging (PyInstaller + Inno Setup) is planned but NOT built or tested yet - see `desktop/PACKAGING.md`
