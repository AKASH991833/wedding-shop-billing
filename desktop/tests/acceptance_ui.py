"""UI acceptance drive: runs the real app offscreen, exercises the main flows through
the actual widgets, asserts outcomes, and saves a screenshot per flow.
Run: QT_QPA_PLATFORM=offscreen python3 tests/acceptance_ui.py /tmp/accept"""
import os, sys, datetime, shutil, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMP = tempfile.mkdtemp(prefix="wsb-accept-")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import db as DB
DB.APP_DIR = _TMP
DB.DB_PATH = os.path.join(_TMP, "shop.db")
DB.DEMO_PATH = os.path.join(_TMP, "shop-demo.db")

from PySide6.QtWidgets import QApplication, QMessageBox, QFileDialog, QDialog
from PySide6.QtPrintSupport import QPrinter
# dialogs auto-accept; message boxes no-op (headless drive)
QMessageBox.information = staticmethod(lambda *a, **k: None)
QMessageBox.warning = staticmethod(lambda *a, **k: None)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
QDialog.exec = lambda self: QDialog.DialogCode.Accepted
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (os.path.join(_TMP, "x.csv"), ""))

import main as M
OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/accept"
os.makedirs(OUT, exist_ok=True)
app = QApplication(sys.argv)
base = os.path.join(os.path.dirname(__file__), "..", "app")
with open(os.path.join(base, "style.qss")) as f: app.setStyleSheet(f.read())
sys.argv = ["accept", "--demo"]
w = M.Main(); w.resize(1120, 720)
DB.set_setting(w.con, "shop_name", "Demo Store")  # dummy name - real shop name stays local only
w.refresh_all(); w.show(); app.processEvents()
shot = lambda name: (app.processEvents(), w.grab().save(f"{OUT}/{name}.png"), print("shot", name))
TODAY = datetime.date.today().isoformat()

# 1) STOCK: add a catalog item with rates, verify it persists
w.go(4)
w.p_stock.nm.setText("Bandhgala - Navy"); w.p_stock.cat.setCurrentText("rental")
w.p_stock.qty.setValue(3); w.p_stock.rr.setValue(1200); w.p_stock.sp.setValue(0)
w.p_stock._add()
inv = {x["name"]: x for x in DB.list_inventory(w.con)}
assert "Bandhgala - Navy" in inv and inv["Bandhgala - Navy"]["rent_rate_day"] == 1200, inv.get("Bandhgala - Navy")
shot("accept-stock")

# 2) NEW BILL: pick the catalog item -> kind + rate autofill; plus a free-text sale row
w.go(2)
w.p_bill.name.setText("Accept Kumar"); w.p_bill.mobile.setText("90000 00099")
w.p_bill.refresh(w.con)  # catalog lists current
desc0 = w.p_bill.items.cellWidget(0, 0)
desc0.setCurrentText("Bandhgala - Navy"); w.p_bill._desc_done(0)
kind0 = w.p_bill.items.cellWidget(0, 1)
assert kind0.currentText() == "Rental", kind0.currentText()
assert w.p_bill.items.item(0, 4).text() == "1200", w.p_bill.items.item(0, 4).text()
w.p_bill.items.setItem(0, 2, M.QTableWidgetItem("2")); w.p_bill.items.setItem(0, 3, M.QTableWidgetItem("2"))
w.p_bill._add_row()
desc1 = w.p_bill.items.cellWidget(1, 0); desc1.setCurrentText("Safa (sold)")
w.p_bill._desc_done(1)
w.p_bill.items.cellWidget(1, 1).setCurrentText("Sale")
w.p_bill.items.setItem(1, 4, M.QTableWidgetItem("500"))
w.p_bill.adv.setValue(2000); w.p_bill.dep.setValue(3000); w.p_bill._recalc()
shot("accept-newbill")
w.p_bill._save()
bill = next(r for r in DB.list_bills(w.con) if r["customer"] == "Accept Kumar")
assert bill["charges"] == 5300 and bill["deposit"] == 3000 and bill["balance"] == 6300, dict(bill)
assert DB.display_type(bill) == "Mixed (Sale + Rental)", DB.display_type(bill)

# 3) RECORDS: new bill listed; record a payment against its balance through the dialog
w.go(1); app.processEvents()
idx = next(i for i, r in enumerate(w.p_rec.rows) if r["customer"] == "Accept Kumar")
w.p_rec.tbl.setCurrentCell(idx, 0)
w.p_rec._payment()  # dialog auto-accepts the full balance
bill = next(r for r in DB.list_bills(w.con) if r["customer"] == "Accept Kumar")
assert bill["balance"] == 0, bill["balance"]  # status stays Active until garments return
shot("accept-records")

# 4) RETURNS: mark the new mixed bill returned, then record the deposit refund via dialog
w.go(3); app.processEvents()
i = next(i for i, r in enumerate(w.p_ret.rows) if r["customer"] == "Accept Kumar")
w.p_ret.tbl.setCurrentCell(i, 0)
w.p_ret._mark()
b2 = next(r for r in DB.list_bills(w.con) if r["customer"] == "Accept Kumar")
assert b2["returned_at"], "return not recorded"
# refund needs the row re-selected; returned bills leave the active list, use another active rental
w.go(3); app.processEvents()
if w.p_ret.rows:
    j = 0
    w.p_ret.tbl.setCurrentCell(j, 0)
    held_before = w.p_ret.rows[j]["deposit"] - w.p_ret.rows[j]["deposit_refunded"]
    if held_before > 0:
        w.p_ret._refund()  # dialog defaults to full held amount, auto-accepts
        rr = next(r for r in DB.list_bills(w.con) if r["id"] == w.p_ret.rows[j]["id"])
        assert rr["deposit_refunded"] == rr["deposit"], dict(rr)
shot("accept-returns")

# 5) CUSTOMERS ledger
w.go(5); app.processEvents()
w.p_cust.pick.setCurrentText("Accept Kumar")
app.processEvents(); shot("accept-customers")

# 6) REPORTS
w.go(6); app.processEvents(); w.p_rep._run(); app.processEvents()
rep = DB.date_report(w.con, "2000-01-01", "2100-01-01")
assert rep["sales"] >= 500, rep
shot("accept-reports")

# 7) DASHBOARD (chart axis, recent ordering) + 8) SETTINGS (generic data label) + 9) INVOICE + PDF
w.go(0); app.processEvents(); shot("accept-dash")
w.go(8); app.processEvents()
assert "sandbox" not in w.p_set.path_lab.text() and _TMP not in w.p_set.path_lab.text(), w.p_set.path_lab.text()
shot("accept-settings")
w.go(7); app.processEvents(); shot("accept-invoice")
w.p_inv.render_pdf(f"{OUT}/accept-invoice.pdf")
assert os.path.getsize(f"{OUT}/accept-invoice.pdf") > 5000
print("PDF written", os.path.getsize(f"{OUT}/accept-invoice.pdf"), "bytes")
print("ACCEPTANCE OK")
