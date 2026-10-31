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
  kind TEXT NOT NULL DEFAULT 'SALE' CHECK(kind IN ('SALE','RENTAL','ORDER','FLAT')),
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
    name, mobile, address = (name or "").strip(), (mobile or "").strip(), (address or "").strip()
    if name and mobile:
        row = con.execute("SELECT id FROM customers WHERE name=? AND mobile=? ORDER BY id LIMIT 1",
                          (name, mobile)).fetchone()
        if row:
            if address:
                con.execute("UPDATE customers SET address=? WHERE id=?", (address, row["id"])); con.commit()
            return row["id"]
    cur = con.execute("INSERT INTO customers(name,mobile,address) VALUES(?,?,?)", (name, mobile, address))
    con.commit()
    return cur.lastrowid

def customer_label(row):
    """Display name; anonymous (blank-name) bills stay distinct walk-in records."""
    return row["customer"] if row["customer"] else f"Walk-in #{row['customer_id']}"

def add_bill(con, customer_name, mobile, btype, bill_date, items, advance=0.0,
             deposit=0.0, event_date=None, return_date=None, pay_mode="Cash", address=""):
    """items: list of dicts(description, kind, qty, days, rate). Dates are ISO strings.
    Customer name/mobile/address are all optional; blank customers stay separate records."""
    cid = add_customer(con, customer_name, mobile, address)
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
SELECT b.id, b.bill_no, b.type, b.bill_date, b.customer_id, b.event_date, b.return_date, b.returned_at,
       c.name AS customer, c.mobile, c.address AS customer_address,
       IFNULL((SELECT SUM(amount) FROM bill_items WHERE bill_id=b.id),0) AS charges,
       IFNULL((SELECT SUM(amount) FROM deposits WHERE bill_id=b.id),0) AS deposit,
       IFNULL((SELECT SUM(refunded_amount) FROM deposits WHERE bill_id=b.id),0) AS deposit_refunded,
       IFNULL((SELECT SUM(amount) FROM payments WHERE bill_id=b.id),0) AS paid,
       IFNULL((SELECT GROUP_CONCAT(DISTINCT kind) FROM bill_items WHERE bill_id=b.id),'') AS kinds
FROM bills b JOIN customers c ON c.id=b.customer_id
"""

def add_payment(con, bill_id, amount, mode="Cash"):
    """Record a later payment against a bill's balance (advance at booking is separate)."""
    if amount <= 0:
        raise ValueError("Payment amount must be positive")
    r = con.execute(BILL_Q + " WHERE b.id=?", (bill_id,)).fetchone()
    if not r:
        raise ValueError("Bill not found")
    grand, bal = bill_totals(r)
    if amount > bal + 1e-9:
        raise ValueError(f"Payment exceeds the remaining balance of {bal:,.0f}")
    con.execute("INSERT INTO payments(bill_id,amount,mode) VALUES(?,?,?)", (bill_id, amount, mode))
    con.commit()

def display_type(row, short=False):
    """Label from the actual line kinds: single-kind bills keep their stored label
    (covers WEDDING); mixed bills say exactly what they mix."""
    kinds = {k for k in (row.get("kinds") or "").split(",") if k}
    if len(kinds) <= 1:
        return (row.get("type") or "").title()
    if short:
        return "Mixed"
    parts = [p for p, k in [("Sale", "SALE"), ("Rental", "RENTAL"), ("Order", "ORDER")] if k in kinds]
    return "Mixed (" + " + ".join(parts) + ")"

def bill_totals(row):
    grand = row["charges"] + row["deposit"]
    return grand, grand - row["paid"]

def list_bills(con, type_filter=None):
    q = BILL_Q + (" WHERE b.type=?" if type_filter else "") + " ORDER BY b.bill_date DESC, b.bill_no DESC"
    rows = con.execute(q, (type_filter,) if type_filter else ()).fetchall()
    return [_with_status(r) for r in rows]

def _with_status(r):
    grand, bal = bill_totals(r)
    status = "Paid" if bal <= 0 else ("Advance" if r["paid"] > 0 else "Unpaid")
    if "RENTAL" in (r["kinds"] or "") and r["return_date"] and not r["returned_at"]:
        status = "Active"
    return dict(r) | {"grand": grand, "balance": bal, "status": status}

def _line_split(con, bill_ids):
    """Per-LINE split for mixed bills: FLAT lines are sales, RENTAL lines are rental/order charges."""
    if not bill_ids: return 0.0, 0.0
    ph = ",".join("?" * len(bill_ids))
    rows = con.execute(f"SELECT kind, SUM(amount) AS s FROM bill_items WHERE bill_id IN ({ph}) GROUP BY kind",
                       bill_ids).fetchall()
    m = {r["kind"]: (r["s"] or 0) for r in rows}
    sales = m.get("SALE", 0.0)
    rent_order = m.get("RENTAL", 0.0) + m.get("ORDER", 0.0) + m.get("FLAT", 0.0)  # FLAT legacy = ORDER
    return sales, rent_order

def stats_today(con, today_iso):
    rows = list_bills(con)
    td = [r for r in rows if r["bill_date"] == today_iso]
    sales, rent_order = _line_split(con, [r["id"] for r in td])
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
    rows = con.execute(BILL_Q + " WHERE b.customer_id=? ORDER BY b.bill_date, b.bill_no", (customer_id,)).fetchall()
    out, total_charges, total_paid = [], 0, 0
    for r in rows:
        r = _with_status(r)
        total_charges += r["grand"]; total_paid += r["paid"]
        out.append(r)
    return out, {"billed": total_charges, "paid": total_paid, "outstanding": total_charges - total_paid}

def date_report(con, date_from, date_to):
    """Sales vs rental/order charges vs deposits for [date_from, date_to] inclusive.
    Refundable deposits are never mixed into revenue."""
    rows = con.execute(BILL_Q + " WHERE date(b.bill_date) BETWEEN date(?) AND date(?)",
                       (date_from, date_to)).fetchall()
    sales, rent_order = _line_split(con, [r["id"] for r in rows])
    collected = con.execute("""SELECT IFNULL(SUM(amount),0) FROM payments p JOIN bills b ON b.id=p.bill_id
        WHERE date(b.bill_date) BETWEEN date(?) AND date(?)""", (date_from, date_to)).fetchone()[0]
    deposits_held = con.execute(
        "SELECT IFNULL(SUM(amount - refunded_amount - deduction),0) FROM deposits WHERE status != 'REFUNDED'").fetchone()[0]
    return {"sales": sales, "rental_order_charges": rent_order, "collected": collected,
            "deposits_held_refundable": deposits_held}

def list_inventory(con):
    return con.execute("SELECT * FROM inventory WHERE active=1 ORDER BY name").fetchall()

def add_inventory_item(con, name, category="", total_qty=0, sale_price=None, rent_rate_day=None):
    cur = con.execute("INSERT INTO inventory(name,category,total_qty,sale_price,rent_rate_day) VALUES(?,?,?,?,?)",
                      (name, category, total_qty, sale_price, rent_rate_day))
    con.commit()
    return cur.lastrowid

def list_customers(con):
    return con.execute("SELECT * FROM customers ORDER BY name").fetchall()

def get_setting(con, key, default=None):
    r = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default

def set_setting(con, key, value):
    con.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value))
    con.commit()

def shop_profile(con):
    return {"name": get_setting(con, "shop_name", "Your Shop Name"),
            "address": get_setting(con, "shop_address", ""),
            "phone": get_setting(con, "shop_phone", ""),
            "email": get_setting(con, "shop_email", "")}

def shop_logo(con):
    p = get_setting(con, "shop_logo", "")
    return p if p and os.path.exists(p) else ""

def apply_turnaround_policy(con):
    global SAME_DAY_TURNAROUND
    SAME_DAY_TURNAROUND = get_setting(con, "same_day_turnaround", "1") == "1"

# ---- local password auth (PBKDF2-HMAC-SHA256; only the hash is stored) ----
# Pure-Python PBKDF2 (hmac + hashlib.sha256) so the app needs no OpenSSL libraries.
import hashlib, hmac, secrets

_PBKDF2_ITERS = 200_000

def _pbkdf2(password, salt_hex, iters):
    """PBKDF2-HMAC-SHA256; stdlib C backend when available, else pure-Python (identical output)."""
    pw, salt = password.encode(), bytes.fromhex(salt_hex)
    try:
        return hashlib.pbkdf2_hmac("sha256", pw, salt, iters).hex()
    except Exception:
        pass
    u = hmac.new(pw, salt + (1).to_bytes(4, "big"), hashlib.sha256).digest()
    t = bytearray(u)
    for _ in range(iters - 1):
        u = hmac.new(pw, u, hashlib.sha256).digest()
        for i in range(len(t)):
            t[i] ^= u[i]
    return bytes(t).hex()

def has_password(con):
    return get_setting(con, "password_hash") is not None

def set_password(con, password):
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    salt = secrets.token_hex(16)
    h = _pbkdf2(password, salt, _PBKDF2_ITERS)
    set_setting(con, "password_hash", f"v2${salt}${_PBKDF2_ITERS}${h}")

def verify_password(con, password):
    stored = get_setting(con, "password_hash")
    if stored is None: return True
    parts = stored.split("$")
    if parts[0] == "v2":
        _, salt, iters, h = parts[0], parts[1], int(parts[2]), parts[3]
    else:  # legacy "salt$hash" at the original iteration count
        salt, iters, h = parts[0], _PBKDF2_ITERS, parts[1]
    cand = _pbkdf2(password, salt, iters)
    return secrets.compare_digest(cand, h)

def daily_series(con, days=14):
    """Real per-day charges split sale vs rental/order for the last N days (ISO dates)."""
    since = (datetime.date.today() - datetime.timedelta(days=days - 1)).isoformat()
    rows = con.execute("""
      SELECT b.bill_date AS d, i.kind, SUM(i.amount) AS s
      FROM bill_items i JOIN bills b ON b.id=i.bill_id
      WHERE date(b.bill_date) >= date(?) GROUP BY b.bill_date, i.kind
    """, (since,)).fetchall()
    out = {}
    for r in rows:
        e = out.setdefault(r["d"], {"sales": 0.0, "rent_order": 0.0})
        if r["kind"] == "SALE": e["sales"] += r["s"]
        else: e["rent_order"] += r["s"]
    return out

def top_outstanding(con, limit=5):
    agg = {}
    for r in list_bills(con):
        grand, bal = bill_totals(r)
        if bal <= 0: continue
        e = agg.setdefault(r["customer_id"], {"customer_id": r["customer_id"], "customer": r["customer"],
                                              "mobile": r["mobile"], "balance": 0.0})
        e["balance"] += bal
    return sorted(agg.values(), key=lambda x: -x["balance"])[:limit]

def upcoming_returns(con, days=7, today=None):
    today = today or datetime.date.today().isoformat()
    until = (datetime.date.fromisoformat(today) + datetime.timedelta(days=days)).isoformat()
    rows = con.execute("""
      SELECT b.id, b.bill_no, b.return_date, b.customer_id, c.name AS customer, c.mobile,
             (SELECT GROUP_CONCAT(description || ' x' || CAST(qty AS INT), ', ')
              FROM bill_items WHERE bill_id=b.id AND kind='RENTAL') AS items
      FROM bills b JOIN customers c ON c.id=b.customer_id
      WHERE b.returned_at IS NULL AND b.return_date IS NOT NULL
        AND EXISTS (SELECT 1 FROM bill_items WHERE bill_id=b.id AND kind='RENTAL')
        AND date(b.return_date) <= date(?)
      ORDER BY b.return_date
    """, (until,)).fetchall()
    t = datetime.date.fromisoformat(today)
    return [dict(r) | {"overdue": r["return_date"] < today,
                       "in_days": (datetime.date.fromisoformat(r["return_date"]) - t).days} for r in rows]

def seed_demo(con):
    if con.execute("SELECT COUNT(*) FROM bills").fetchone()[0]:
        return
    today = datetime.date.today().isoformat()
    add_bill(con, "Rahul Verma", "90000 00001", "RENTAL", today, [
        {"description": "Sherwani - Cream", "kind": "RENTAL", "qty": 1, "days": 3, "rate": 1000},
        {"description": "Indo-Western Suit", "kind": "RENTAL", "qty": 1, "days": 3, "rate": 800},
        {"description": "Safa / Pagdi", "kind": "RENTAL", "qty": 6, "days": 3, "rate": 50},
        {"description": "Firecracker Order - Wedding Pack", "kind": "ORDER", "qty": 1, "days": 1, "rate": 3500},
        {"description": "Stage Decoration Arrangement", "kind": "ORDER", "qty": 1, "days": 1, "rate": 2900},
    ], advance=5000, deposit=2000,
       event_date=(datetime.date.today() + datetime.timedelta(days=2)).isoformat(),
       return_date=(datetime.date.today() + datetime.timedelta(days=4)).isoformat())
    add_bill(con, "Priya Singh", "90000 00002", "SALE", today, [
        {"description": "Saree - Silk", "kind": "SALE", "qty": 1, "days": 1, "rate": 2400}], advance=2400)
    for days_ago, (nm, mob, tp, items, adv) in enumerate([]): pass
    history = [
        (9, "Karan Mehta", "SALE", [("Saree - Silk", "SALE", 1, 1, 2400)], 2400),
        (7, "Ritu Sharma", "RENTAL", [("Sherwani - Cream", "RENTAL", 1, 2, 1000)], 1000),
        (5, "Vikas Rao", "WEDDING", [("Stage Decoration Arrangement", "ORDER", 1, 1, 2900)], 1500),
        (3, "Anjali Patel", "RENTAL", [("Indo-Western Suit", "RENTAL", 1, 2, 800), ("Safa / Pagdi", "RENTAL", 4, 2, 50)], 1000),
        (1, "Rohit Jain", "SALE", [("Saree - Silk", "SALE", 2, 1, 2400)], 4800),
    ]
    for days_ago, nm, tp, items, adv in history:
        add_bill(con, nm, "90000 00020", tp, (datetime.date.today() - datetime.timedelta(days=days_ago)).isoformat(),
                 [{"description": d_, "kind": k, "qty": q, "days": dd, "rate": r} for d_, k, q, dd, r in items], advance=adv)
    if not con.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]:
        for row in [("Sherwani - Cream", "rental", 5, None, 1000), ("Indo-Western Suit", "rental", 3, None, 800),
                    ("Safa / Pagdi", "rental", 20, None, 50), ("Saree - Silk", "sale", 10, 2400, None)]:
            con.execute("INSERT INTO inventory(name,category,total_qty,sale_price,rent_rate_day) VALUES(?,?,?,?,?)", row)
        con.commit()
