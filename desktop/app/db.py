"""SQLite data layer for Wedding Shop Billing. Single portable shop.db file.
All dates stored as ISO 'YYYY-MM-DD'; display formatting happens in the UI layer."""
import os, sqlite3, shutil, datetime

def _default_dir():
    if os.environ.get("WSB_DATA_DIR"):
        return os.environ["WSB_DATA_DIR"]
    appdata = os.environ.get("APPDATA")  # writable per-user on installed Windows
    if appdata:
        return os.path.join(appdata, "WeddingShopBilling")
    return os.path.join(os.path.expanduser("~"), ".wedding_shop_billing")

APP_DIR = _default_dir()
DB_PATH = os.path.join(APP_DIR, "shop.db")
DEMO_PATH = os.path.join(APP_DIR, "shop-demo.db")

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS customers(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, mobile TEXT, address TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS bills(
  id INTEGER PRIMARY KEY, bill_no TEXT UNIQUE NOT NULL,
  customer_id INTEGER REFERENCES customers(id),
  type TEXT NOT NULL CHECK(type IN ('SALE','RENTAL','WEDDING')),
  bill_date TEXT NOT NULL, event_date TEXT, return_date TEXT, returned_at TEXT, notes TEXT,
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS bill_items(
  id INTEGER PRIMARY KEY, bill_id INTEGER NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
  description TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'FLAT' CHECK(kind IN ('FLAT','RENTAL')),
  qty REAL NOT NULL DEFAULT 1, days REAL NOT NULL DEFAULT 1,
  rate REAL NOT NULL DEFAULT 0, amount REAL NOT NULL);
CREATE TABLE IF NOT EXISTS payments(
  id INTEGER PRIMARY KEY, bill_id INTEGER NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
  paid_at TEXT DEFAULT (datetime('now','localtime')),
  amount REAL NOT NULL, mode TEXT DEFAULT 'Cash', note TEXT);
CREATE TABLE IF NOT EXISTS deposits(
  id INTEGER PRIMARY KEY, bill_id INTEGER NOT NULL REFERENCES bills(id) ON DELETE CASCADE,
  amount REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'HELD' CHECK(status IN ('HELD','REFUNDED','PARTIALLY_REFUNDED')),
  refunded_amount REAL NOT NULL DEFAULT 0,
  deduction REAL NOT NULL DEFAULT 0, deduction_note TEXT,
  refunded_at TEXT);
CREATE TABLE IF NOT EXISTS inventory(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT,
  total_qty REAL NOT NULL DEFAULT 0,
  sale_price REAL, rent_rate_day REAL,
  active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
"""

def disp(iso):
    """ISO '2026-10-31' -> '31 Oct 2026' for display. Passes through empty/None."""
    if not iso: return "-"
    try: return datetime.date.fromisoformat(iso).strftime("%d %b %Y")
    except ValueError: return iso

def connect(demo=False):
    os.makedirs(APP_DIR, exist_ok=True)
    con = sqlite3.connect(DEMO_PATH if demo else DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con

def db_path(demo=False):
    return DEMO_PATH if demo else DB_PATH

def next_bill_no(con):
    n = con.execute("SELECT COUNT(*) FROM bills").fetchone()[0] + 1
    return f"{n:03d}"

def add_customer(con, name, mobile="", address=""):
    cur = con.execute("INSERT INTO customers(name,mobile,address) VALUES(?,?,?)", (name, mobile, address))
    return cur.lastrowid

def add_bill(con, customer_name, mobile, btype, bill_date, items, advance=0.0,
             deposit=0.0, event_date=None, return_date=None, pay_mode="Cash"):
    """items: list of dicts(description, kind, qty, days, rate). Dates are ISO strings."""
    cid = add_customer(con, customer_name, mobile)
    cur = con.execute(
        "INSERT INTO bills(bill_no,customer_id,type,bill_date,event_date,return_date) VALUES(?,?,?,?,?,?)",
        (next_bill_no(con), cid, btype, bill_date, event_date, return_date))
    bid = cur.lastrowid
    for it in items:
        amt = it["qty"] * it["days"] * it["rate"] if it["kind"] == "RENTAL" else it["qty"] * it["rate"]
        con.execute("INSERT INTO bill_items(bill_id,description,kind,qty,days,rate,amount) VALUES(?,?,?,?,?,?,?)",
                    (bid, it["description"], it["kind"], it["qty"], it["days"], it["rate"], amt))
    if advance > 0:
        con.execute("INSERT INTO payments(bill_id,amount,mode) VALUES(?,?,?)", (bid, advance, pay_mode))
    if deposit > 0:
        con.execute("INSERT INTO deposits(bill_id,amount) VALUES(?,?)", (bid, deposit))
    con.commit()
    return bid

BILL_Q = """
SELECT b.id, b.bill_no, b.type, b.bill_date, b.event_date, b.return_date, b.returned_at,
       c.name AS customer, c.mobile,
       IFNULL((SELECT SUM(amount) FROM bill_items WHERE bill_id=b.id),0) AS charges,
       IFNULL((SELECT SUM(amount) FROM deposits WHERE bill_id=b.id),0) AS deposit,
       IFNULL((SELECT SUM(refunded_amount) FROM deposits WHERE bill_id=b.id),0) AS deposit_refunded,
       IFNULL((SELECT SUM(amount) FROM payments WHERE bill_id=b.id),0) AS paid
FROM bills b JOIN customers c ON c.id=b.customer_id
"""

def bill_totals(row):
    grand = row["charges"] + row["deposit"]
    return grand, grand - row["paid"]

def list_bills(con, type_filter=None):
    q = BILL_Q + (" WHERE b.type=?" if type_filter else "") + " ORDER BY b.id DESC"
    rows = con.execute(q, (type_filter,) if type_filter else ()).fetchall()
    out = []
    for r in rows:
        grand, bal = bill_totals(r)
        status = "Paid" if bal <= 0 else ("Advance" if r["paid"] > 0 else "Unpaid")
        if r["type"] == "RENTAL" and r["return_date"] and not r["returned_at"]:
            status = "Active"
        out.append(dict(r) | {"grand": grand, "balance": bal, "status": status})
    return out

def stats_today(con, today_iso):
    rows = list_bills(con)
    td = [r for r in rows if r["bill_date"] == today_iso]
    sales = sum(r["charges"] for r in td if r["type"] == "SALE")
    rent_order = sum(r["charges"] for r in td if r["type"] != "SALE")
    pending = sum(r["balance"] for r in rows)
    deposits_held = con.execute(
        "SELECT IFNULL(SUM(amount - refunded_amount - deduction),0) FROM deposits WHERE status != 'REFUNDED'").fetchone()[0]
    return {"sales": sales, "rent_order": rent_order, "pending": pending, "deposits": deposits_held}

def get_invoice(con, bill_id):
    r = con.execute(BILL_Q + " WHERE b.id=?", (bill_id,)).fetchone()
    items = con.execute("SELECT * FROM bill_items WHERE bill_id=? ORDER BY id", (bill_id,)).fetchall()
    grand, bal = bill_totals(r)
    return dict(r) | {"grand": grand, "balance": bal}, items

# ---- backup / restore (verified roundtrip) ----

def integrity_ok(path):
    try:
        con = sqlite3.connect(path)
        try:
            return con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            con.close()
    except sqlite3.DatabaseError:
        return False

def table_counts(path):
    con = sqlite3.connect(path)
    try:
        return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("customers", "bills", "bill_items", "payments", "deposits")}
    finally:
        con.close()

def backup_db(dest_path, src_path=None):
    src = src_path or DB_PATH
    shutil.copyfile(src, dest_path)
    ok = integrity_ok(dest_path) and table_counts(dest_path) == table_counts(src)
    return {"dest": dest_path, "verified": ok, "counts": table_counts(dest_path)}

def auto_backup(demo=False):
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = os.path.join(APP_DIR, "backups", f"shop-{stamp}.db")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    return backup_db(dest, db_path(demo))

def restore_db(src_path, demo=False):
    """Restore a backup over the live DB, then verify the restored file."""
    if not integrity_ok(src_path):
        raise ValueError("Backup file failed integrity check - not restoring")
    dest = db_path(demo)
    shutil.copyfile(src_path, dest)
    ok = integrity_ok(dest) and table_counts(dest) == table_counts(src_path)
    return {"restored": dest, "verified": ok, "counts": table_counts(dest)}

# ---- rental returns, availability, refunds ----

# Business policy (explicit, adjustable): with SAME_DAY_TURNAROUND=True an item is
# available for a new booking ON its scheduled return date; with False it is occupied
# through the return date and free the next day. Applies to SCHEDULING only - overdue
# unreturned stock is never released by the calendar alone (see rental_out_qty).
SAME_DAY_TURNAROUND = True

def _open_rentals(con, item_name):
    return con.execute("""
      SELECT i.qty, b.id AS bill_id, b.bill_no, b.bill_date, b.return_date, b.returned_at, c.name AS customer
      FROM bill_items i
      JOIN bills b ON b.id=i.bill_id
      JOIN customers c ON c.id=b.customer_id
      WHERE i.kind='RENTAL' AND i.description=? AND b.returned_at IS NULL
    """, (item_name,)).fetchall()

def rental_out_qty(con, item_name, date_from, date_to, today=None):
    """Qty unavailable for a PROPOSED reservation window [date_from, date_to).
    Counts unreturned bookings whose schedule overlaps the window, PLUS any overdue
    unreturned booking - a booking whose return_date has passed without an actual
    return stays out of stock until someone records the physical return."""
    today = today or datetime.date.today().isoformat()
    out = 0
    for r in _open_rentals(con, item_name):
        if r["bill_date"] >= date_to:
            continue  # starts after the queried window
        scheduled_end = r["return_date"] or r["bill_date"]
        overlaps = scheduled_end > date_from if SAME_DAY_TURNAROUND else scheduled_end >= date_from
        overdue = r["return_date"] is not None and r["return_date"] < today
        if overlaps or overdue:
            out += r["qty"]
    return out

def rental_availability(con, item_id, date_from, date_to):
    it = con.execute("SELECT name,total_qty FROM inventory WHERE id=?", (item_id,)).fetchone()
    if not it: return None
    return it["total_qty"] - rental_out_qty(con, it["name"], date_from, date_to)

def physical_on_hand(con, item_id, today=None):
    """Actual stock in the shop right now: total minus qty out on unreturned bookings
    that have already started. Overdue items count as out until physically returned."""
    today = today or datetime.date.today().isoformat()
    it = con.execute("SELECT name,total_qty FROM inventory WHERE id=?", (item_id,)).fetchone()
    if not it: return None
    out_qty = sum(r["qty"] for r in _open_rentals(con, it["name"]) if r["bill_date"] <= today)
    return it["total_qty"] - out_qty

def overdue_rentals(con, today=None):
    """Unreturned rental lines past their return date. These must be chased and must
    block/conflict new reservations for the same items."""
    today = today or datetime.date.today().isoformat()
    rows = con.execute("""
      SELECT b.id AS bill_id, b.bill_no, c.name AS customer, c.mobile,
             i.description, i.qty, b.return_date
      FROM bills b JOIN customers c ON c.id=b.customer_id
      JOIN bill_items i ON i.bill_id=b.id
      WHERE i.kind='RENTAL' AND b.returned_at IS NULL
        AND b.return_date IS NOT NULL AND date(b.return_date) < date(?)
      ORDER BY b.return_date
    """, (today,)).fetchall()
    t = datetime.date.fromisoformat(today)
    return [dict(r) | {"days_overdue": (t - datetime.date.fromisoformat(r["return_date"])).days}
            for r in rows]

def check_reservation(con, item_id, date_from, date_to):
    """Availability for a proposed booking, with overdue conflicts flagged separately
    so the shop can chase the physical return before promising the item."""
    it = con.execute("SELECT name,total_qty FROM inventory WHERE id=?", (item_id,)).fetchone()
    if not it: return None
    avail = it["total_qty"] - rental_out_qty(con, it["name"], date_from, date_to)
    conflicts = [r for r in overdue_rentals(con) if r["description"] == it["name"]]
    return {"item": it["name"], "total": it["total_qty"], "available": avail,
            "overdue_conflicts": conflicts}

def mark_returned(con, bill_id, returned_at):
    """Marks garments physically back. Does NOT touch the deposit - the refund
    is a separate money event recorded via record_deposit_refund."""
    con.execute("UPDATE bills SET returned_at=? WHERE id=?", (returned_at, bill_id))
    con.commit()

def record_deposit_refund(con, bill_id, refund_amount, deduction=0.0, deduction_note="", refunded_at=None):
    """Records actual cash returned to the customer. Any deduction (damage/late fee)
    stays with the shop. refund + deduction must not exceed the held deposit."""
    dep = con.execute("SELECT * FROM deposits WHERE bill_id=?", (bill_id,)).fetchone()
    if not dep:
        raise ValueError("No deposit on this bill")
    if dep["status"] != "HELD":
        raise ValueError(f"Deposit already settled ({dep['status']}) - no second refund")
    if refund_amount < 0 or deduction < 0 or refund_amount + deduction > dep["amount"] + 1e-9:
        raise ValueError(f"Refund {refund_amount} + deduction {deduction} exceeds held deposit {dep['amount']}")
    status = "REFUNDED" if deduction == 0 else "PARTIALLY_REFUNDED"
    con.execute("""UPDATE deposits SET status=?, refunded_amount=?, deduction=?, deduction_note=?, refunded_at=?
                   WHERE id=?""",
                (status, refund_amount, deduction, deduction_note,
                 refunded_at or datetime.date.today().isoformat(), dep["id"]))
    con.commit()
    return status

def customer_ledger(con, customer_id):
    rows = con.execute(BILL_Q + " WHERE b.customer_id=? ORDER BY b.id", (customer_id,)).fetchall()
    out, total_charges, total_paid = [], 0, 0
    for r in rows:
        grand, bal = bill_totals(r)
        total_charges += grand; total_paid += r["paid"]
        out.append(dict(r) | {"grand": grand, "balance": bal})
    return out, {"billed": total_charges, "paid": total_paid, "outstanding": total_charges - total_paid}

def date_report(con, date_from, date_to):
    """Sales vs rental/order charges vs deposits for [date_from, date_to] inclusive.
    Refundable deposits are never mixed into revenue."""
    rows = con.execute(BILL_Q + " WHERE date(b.bill_date) BETWEEN date(?) AND date(?)",
                       (date_from, date_to)).fetchall()
    sales = sum(r["charges"] for r in rows if r["type"] == "SALE")
    rent_order = sum(r["charges"] for r in rows if r["type"] != "SALE")
    collected = con.execute("""SELECT IFNULL(SUM(amount),0) FROM payments p JOIN bills b ON b.id=p.bill_id
        WHERE date(b.bill_date) BETWEEN date(?) AND date(?)""", (date_from, date_to)).fetchone()[0]
    deposits_held = con.execute(
        "SELECT IFNULL(SUM(amount - refunded_amount - deduction),0) FROM deposits WHERE status != 'REFUNDED'").fetchone()[0]
    return {"sales": sales, "rental_order_charges": rent_order, "collected": collected,
            "deposits_held_refundable": deposits_held}

def seed_demo(con):
    if con.execute("SELECT COUNT(*) FROM bills").fetchone()[0]:
        return
    today = datetime.date.today().isoformat()
    add_bill(con, "Rahul Verma", "90000 00001", "RENTAL", today, [
        {"description": "Sherwani - Cream", "kind": "RENTAL", "qty": 1, "days": 3, "rate": 1000},
        {"description": "Indo-Western Suit", "kind": "RENTAL", "qty": 1, "days": 3, "rate": 800},
        {"description": "Safa / Pagdi", "kind": "RENTAL", "qty": 6, "days": 3, "rate": 50},
        {"description": "Firecracker Order - Wedding Pack", "kind": "FLAT", "qty": 1, "days": 1, "rate": 3500},
        {"description": "Stage Decoration Arrangement", "kind": "FLAT", "qty": 1, "days": 1, "rate": 2900},
    ], advance=5000, deposit=2000,
       event_date=(datetime.date.today() + datetime.timedelta(days=2)).isoformat(),
       return_date=(datetime.date.today() + datetime.timedelta(days=4)).isoformat())
    add_bill(con, "Priya Singh", "90000 00002", "SALE", today, [
        {"description": "Saree - Silk", "kind": "FLAT", "qty": 1, "days": 1, "rate": 2400}], advance=2400)
