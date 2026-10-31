"""Data-layer test suite for Wedding Shop Billing. No external deps: run `python desktop/tests/test_db.py`."""
import os, sys, tempfile, datetime, shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
_TMP = tempfile.mkdtemp(prefix="wsb-test-")
import db as DB
DB.APP_DIR = _TMP
DB.DB_PATH = os.path.join(_TMP, "shop.db")
DB.DEMO_PATH = os.path.join(_TMP, "shop-demo.db")

d = datetime.date.today()
iso = lambda n: (d + datetime.timedelta(n)).isoformat()
TODAY = iso(0)

def fresh():
    for p in (DB.DB_PATH, DB.DEMO_PATH):
        if os.path.exists(p): os.remove(p)
    return DB.connect(demo=True)

def test_stats_and_report():
    con = fresh(); DB.seed_demo(con)
    s = DB.stats_today(con, TODAY)
    assert s == {"sales": 2400.0, "rent_order": 12700.0, "pending": 9700.0, "deposits": 2000.0}, s
    rep = DB.date_report(con, iso(-30), iso(30))
    assert rep["sales"] == 2400 and rep["rental_order_charges"] == 12700, rep
    assert rep["deposits_held_refundable"] == 2000, rep
    con.close()

def test_bill_numbering_and_pricing():
    con = fresh(); DB.seed_demo(con)
    bid = DB.add_bill(con, "Test Kumar", "90000 00009", "RENTAL", TODAY,
        [{"description": "Sherwani - Cream", "kind": "RENTAL", "qty": 1, "days": 3, "rate": 1000}],
        advance=500, deposit=1000)
    b = DB.list_bills(con)[0]
    assert b["bill_no"] == "003", b["bill_no"]
    bill, items = DB.get_invoice(con, bid)
    assert bill["charges"] == 3000 and bill["grand"] == 4000 and bill["balance"] == 3500
    con.close()

def test_availability_boundaries():
    con = fresh()
    con.execute("INSERT INTO inventory(name,category,total_qty,rent_rate_day) VALUES('Sherwani - Cream','rental',2,1000)")
    DB.add_bill(con, "Rahul Verma", "1", "RENTAL", TODAY,
        [{"description": "Sherwani - Cream", "kind": "RENTAL", "qty": 1, "days": 4, "rate": 1000}], return_date=iso(4))
    assert DB.rental_availability(con, 1, iso(1), iso(3)) == 1      # inside booking
    assert DB.rental_availability(con, 1, iso(-2), iso(0)) == 2     # ends as booking starts
    assert DB.rental_availability(con, 1, iso(4), iso(6)) == 2      # same-day turnaround
    DB.SAME_DAY_TURNAROUND = False
    assert DB.rental_availability(con, 1, iso(4), iso(6)) == 1      # occupied through return date
    DB.SAME_DAY_TURNAROUND = True
    con.close()

def test_overdue_never_auto_releases():
    con = fresh()
    con.execute("INSERT INTO inventory(name,category,total_qty,rent_rate_day) VALUES('Indo-Western Suit','rental',1,800)")
    DB.add_bill(con, "Amit Shah", "90000 00005", "RENTAL", iso(-5),
        [{"description": "Indo-Western Suit", "kind": "RENTAL", "qty": 1, "days": 3, "rate": 800}], return_date=iso(-2))
    r = DB.check_reservation(con, 1, iso(5), iso(8))
    assert r["available"] == 0, r                                    # overdue still blocks future windows
    assert len(r["overdue_conflicts"]) == 1 and r["overdue_conflicts"][0]["days_overdue"] == 2
    assert DB.physical_on_hand(con, 1) == 0
    ov = DB.overdue_rentals(con)
    assert len(ov) == 1 and ov[0]["customer"] == "Amit Shah"
    DB.mark_returned(con, 1, TODAY)                                  # actual physical return
    assert DB.rental_availability(con, 1, iso(5), iso(8)) == 1
    assert DB.overdue_rentals(con) == []
    assert DB.physical_on_hand(con, 1) == 1
    con.close()

def test_deposit_refund_rules():
    con = fresh(); DB.seed_demo(con)
    DB.mark_returned(con, 1, iso(4))
    dep = con.execute("SELECT * FROM deposits WHERE bill_id=1").fetchone()
    assert dep["status"] == "HELD" and dep["refunded_amount"] == 0   # return alone refunds nothing
    assert DB.record_deposit_refund(con, 1, 2000) == "REFUNDED"
    bid = DB.add_bill(con, "Suresh Raina", "90000 00003", "RENTAL", TODAY,
        [{"description": "Indo-Western Suit", "kind": "RENTAL", "qty": 1, "days": 2, "rate": 800}],
        advance=500, deposit=1500, return_date=iso(2))
    assert DB.record_deposit_refund(con, bid, 1200, deduction=300, deduction_note="late + damage") == "PARTIALLY_REFUNDED"
    for bad_call in (lambda: DB.record_deposit_refund(con, bid, 100),
                     lambda: DB.record_deposit_refund(con, 1, 100)):
        try: bad_call(); assert False, "second settlement allowed"
        except ValueError: pass
    bid2 = DB.add_bill(con, "X Y", "9", "RENTAL", TODAY,
        [{"description": "Safa / Pagdi", "kind": "RENTAL", "qty": 1, "days": 1, "rate": 50}], deposit=1000)
    try: DB.record_deposit_refund(con, bid2, 900, deduction=200); assert False, "over-settlement allowed"
    except ValueError: pass
    s = DB.stats_today(con, TODAY)
    assert s["deposits"] == 1000.0, s                                # only the unsettled deposit remains
    con.close()

def test_customer_ledger():
    con = fresh(); DB.seed_demo(con)
    ledger, summ = DB.customer_ledger(con, 1)
    assert summ == {"billed": 14700.0, "paid": 5000.0, "outstanding": 9700.0}, summ
    con.close()

def test_backup_restore_roundtrip():
    con = fresh(); DB.seed_demo(con)
    bkp = DB.auto_backup(demo=True)
    assert bkp["verified"], bkp
    con.close()
    con = DB.connect(demo=True)
    con.execute("DELETE FROM bill_items"); con.commit(); con.close()
    rst = DB.restore_db(bkp["dest"], demo=True)
    assert rst["verified"], rst
    con = DB.connect(demo=True)
    assert con.execute("SELECT COUNT(*) FROM bill_items").fetchone()[0] == bkp["counts"]["bill_items"]
    con.close()
    corrupt = os.path.join(_TMP, "corrupt.db")
    open(corrupt, "wb").write(b"not a sqlite db at all")
    try: DB.restore_db(corrupt, demo=True); assert False, "corrupt backup restored"
    except ValueError: pass

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t(); print(f"PASS {t.__name__}")
    shutil.rmtree(_TMP, ignore_errors=True)
    print(f"ALL {len(tests)} TESTS PASS")
