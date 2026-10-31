import sys, os, datetime
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QGridLayout, QLabel, QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem,
    QLineEdit, QComboBox, QDateEdit, QDoubleSpinBox, QFrame, QHeaderView, QTextBrowser,
    QFileDialog, QMessageBox, QAbstractItemView, QButtonGroup)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QTextDocument
from PySide6.QtPrintSupport import QPrinter
import db as DB

NAVY = "#16324f"; DUE = "#9c3c34"
def money(n): return "\u20b9" + f"{n:,.0f}"

class Card(QFrame):
    def __init__(self, title, due=False):
        super().__init__(); self.setObjectName("card")
        v = QVBoxLayout(self); v.setContentsMargins(14, 10, 14, 10)
        self.val = QLabel("\u20b90"); self.val.setObjectName("statv")
        if due: self.val.setProperty("class", "due"); self.val.setStyleSheet(f"color:{DUE};font-size:21px;font-weight:700;")
        lab = QLabel(title); lab.setObjectName("statl")
        v.addWidget(self.val); v.addWidget(lab)
    def set(self, text): self.val.setText(text)

def table(cols):
    t = QTableWidget(0, len(cols)); t.setHorizontalHeaderLabels(cols)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    t.verticalHeader().setVisible(False); t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection); t.setShowGrid(True)
    return t

class Dashboard(QWidget):
    def __init__(self, app): super().__init__(); self.app = app
        # stats
    def build(self):
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 14, 18, 14); lay.setSpacing(10)
        grid = QGridLayout(); grid.setSpacing(10)
        self.c_sales = Card("Today's Sales (sale bills)")
        self.c_rent = Card("Today's Rental & Order Charges")
        self.c_due = Card("Pending Balance", due=True)
        self.c_dep = Card("Deposits Held (refundable)")
        for i, c in enumerate([self.c_sales, self.c_rent, self.c_due, self.c_dep]): grid.addWidget(c, 0, i)
        lay.addLayout(grid)
        lay.addWidget(self._sect("QUICK ACTIONS"))
        qa = QGridLayout(); qa.setSpacing(10)
        for i, (label, fn) in enumerate([("New Sale Bill", lambda: self.app.new_bill("SALE")),
                ("New Rental", lambda: self.app.new_bill("RENTAL")),
                ("Wedding Order", lambda: self.app.new_bill("WEDDING")),
                ("All Records", lambda: self.app.go(1))]):
            b = QPushButton(label); b.setObjectName("card"); b.setStyleSheet(
                f"text-align:left;padding:18px 14px;font-size:15px;font-weight:700;color:{NAVY};background:#fff;border:1px solid #e6ecf3;border-radius:10px;")
            b.clicked.connect(fn); qa.addWidget(b, 0, i)
        lay.addLayout(qa)
        lay.addWidget(self._sect("RECENT ENTRIES"))
        self.tbl = table(["No.", "Date", "Customer", "Type", "Total", "Balance", "Status"])
        lay.addWidget(self.tbl)
        note = QLabel("Bill totals include refundable security deposits where applicable; deposits are never counted as sales.")
        note.setObjectName("statl"); lay.addWidget(note)
    def _sect(self, s):
        l = QLabel(s); l.setObjectName("sect"); return l
    def refresh(self, con):
        s = DB.stats_today(con, datetime.date.today().isoformat())
        self.c_sales.set(money(s["sales"])); self.c_rent.set(money(s["rent_order"]))
        self.c_due.set(money(s["pending"])); self.c_dep.set(money(s["deposits"]))
        rows = DB.list_bills(con)[:8]
        self.tbl.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, v in enumerate([r["bill_no"], DB.disp(r["bill_date"]), r["customer"], r["type"],
                                   money(r["grand"]), money(r["balance"]), r["status"]]):
                self.tbl.setItem(i, j, QTableWidgetItem(str(v)))

class Records(QWidget):
    def __init__(self, app):
        super().__init__(); self.app = app
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 14, 18, 14); lay.setSpacing(10)
        self.flt = QComboBox(); self.flt.addItems(["All", "SALE", "RENTAL", "WEDDING"])
        self.flt.currentTextChanged.connect(lambda _: self.refresh(self.app.con))
        lay.addWidget(self.flt)
        self.tbl = table(["No.", "Date", "Customer", "Mobile", "Type", "Total", "Advance", "Balance", "Return/Delivery", "Status"])
        lay.addWidget(self.tbl)
        b = QPushButton("Export records (CSV)"); b.setObjectName("ghost"); b.clicked.connect(self.export)
        lay.addWidget(b)
        note = QLabel("Excel (.xlsx) export with styled headers comes with the openpyxl extra.")
        note.setObjectName("statl"); lay.addWidget(note)
    def refresh(self, con):
        f = self.flt.currentText()
        rows = DB.list_bills(con, None if f == "All" else f)
        self.rows = rows
        self.tbl.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, v in enumerate([r["bill_no"], DB.disp(r["bill_date"]), r["customer"], r["mobile"] or "-", r["type"],
                                   money(r["grand"]), money(r["paid"]), money(r["balance"]),
                                   DB.disp(r["return_date"] or r["event_date"]), r["status"]]):
                self.tbl.setItem(i, j, QTableWidgetItem(str(v)))
    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export records", "records.csv", "CSV (*.csv)")
        if not path: return
        import csv
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["No", "Date", "Customer", "Mobile", "Type", "Total", "Advance", "Balance", "Return/Delivery", "Status"])
            for r in self.rows:
                w.writerow([r["bill_no"], DB.disp(r["bill_date"]), r["customer"], r["mobile"], r["type"],
                            r["grand"], r["paid"], r["balance"], DB.disp(r["return_date"] or r["event_date"]), r["status"]])
        QMessageBox.information(self, "Export", f"Saved to {path}")

class NewBill(QWidget):
    def __init__(self, app):
        super().__init__(); self.app = app
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 14, 18, 14); lay.setSpacing(10)
        warn = QLabel("Demo mode - these entries go to the demo database, not real shop records." if app.demo else "Entries are saved to shop.db on this PC. Keep regular backups.")
        warn.setObjectName("warnbox"); warn.setWordWrap(True); lay.addWidget(warn)
        row = QGridLayout(); row.setSpacing(8)
        self.name = QLineEdit(); self.name.setPlaceholderText("Customer name")
        self.mobile = QLineEdit(); self.mobile.setPlaceholderText("Mobile")
        self.type = QComboBox(); self.type.addItems(["SALE", "RENTAL", "WEDDING"])
        self.type.currentTextChanged.connect(self._type_changed)
        self.ret = QDateEdit(QDate.currentDate().addDays(3)); self.ret.setCalendarPopup(True); self.ret.setDisplayFormat("dd MMM yyyy")
        self.retL = QLabel("Return Date (Rental)")
        row.addWidget(QLabel("Customer"), 0, 0); row.addWidget(self.name, 0, 1)
        row.addWidget(QLabel("Mobile"), 0, 2); row.addWidget(self.mobile, 0, 3)
        row.addWidget(QLabel("Order Type"), 1, 0); row.addWidget(self.type, 1, 1)
        row.addWidget(self.retL, 1, 2); row.addWidget(self.ret, 1, 3)
        lay.addLayout(row)
        self.items = table(["Description", "Qty", "Days", "Rate", "Amount"])
        self.items.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
        self.items.cellChanged.connect(self._recalc)
        lay.addWidget(self.items)
        add = QPushButton("+ Add Item"); add.setObjectName("ghost"); add.clicked.connect(lambda: self._add_row())
        lay.addWidget(add)
        pay = QGridLayout(); pay.setSpacing(8)
        self.adv = QDoubleSpinBox(); self.adv.setMaximum(10**9); self.adv.setPrefix("\u20b9 ")
        self.dep = QDoubleSpinBox(); self.dep.setMaximum(10**9); self.dep.setPrefix("\u20b9 ")
        self.adv.valueChanged.connect(self._recalc); self.dep.valueChanged.connect(self._recalc)
        pay.addWidget(QLabel("Advance Paid"), 0, 0); pay.addWidget(self.adv, 0, 1)
        pay.addWidget(QLabel("Security Deposit (refundable)"), 0, 2); pay.addWidget(self.dep, 0, 3)
        lay.addLayout(pay)
        self.tots = QLabel(); self.tots.setStyleSheet(f"font-size:15px;font-weight:700;color:{NAVY};")
        lay.addWidget(self.tots)
        save = QPushButton("Save Bill"); save.setObjectName("primary"); save.clicked.connect(self._save)
        lay.addWidget(save)
        self._add_row(); self._type_changed(self.type.currentText())
    def preset(self, t):
        self.type.setCurrentText(t)
    def _type_changed(self, t):
        rent = t == "RENTAL"
        self.items.setColumnHidden(2, not rent)
        self.items.setHorizontalHeaderItem(3, QTableWidgetItem("Rate/Day" if rent else "Rate"))
        self.retL.setText("Return Date (Rental)" if rent else ("Delivery / Event Date" if t == "WEDDING" else "Return / Event Date"))
        self._recalc()
    def _add_row(self):
        r = self.items.rowCount(); self.items.insertRow(r)
        for c, v in enumerate(["", "1", "1", "", ""]): self.items.setItem(r, c, QTableWidgetItem(v))
    def _rows(self):
        out = []
        rent = self.type.currentText() == "RENTAL"
        for r in range(self.items.rowCount()):
            g = lambda c: (self.items.item(r, c).text() if self.items.item(r, c) else "").strip()
            try: q = float(g(1) or 0); d = float(g(2) or 1) if rent else 1.0; rate = float(g(3) or 0)
            except ValueError: q, d, rate = 0, 1, 0
            amt = q * d * rate
            out.append({"description": g(0), "kind": "RENTAL" if rent else "FLAT",
                        "qty": q, "days": d, "rate": rate, "amount": amt})
        return out
    def _recalc(self, *_):
        rows = self._rows()
        for i, it in enumerate(rows):
            self.items.blockSignals(True)
            self.items.setItem(i, 4, QTableWidgetItem(money(it["amount"])))
            self.items.blockSignals(False)
        items_total = sum(r["amount"] for r in rows)
        dep, adv = self.dep.value(), self.adv.value()
        grand = items_total + dep
        self.tots.setText(f"Items {money(items_total)}   + Deposit {money(dep)}   = Grand {money(grand)}   |   Advance {money(adv)}   |   Balance Due {money(max(grand-adv,0))}")
        self._grand, self._items_total = grand, items_total
    def _save(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "Missing", "Please enter a customer name"); return
        rows = [r for r in self._rows() if r["description"]]
        DB.add_bill(self.app.con, self.name.text().strip(), self.mobile.text().strip(),
                    self.type.currentText(), datetime.date.today().isoformat(), rows,
                    advance=self.adv.value(), deposit=self.dep.value(),
                    return_date=self.ret.date().toString("yyyy-MM-dd"))
        self.name.clear(); self.mobile.clear(); self.adv.setValue(0); self.dep.setValue(0)
        self.items.setRowCount(0); self._add_row()
        self.app.refresh_all(); self.app.go(0)

class Invoice(QWidget):
    def __init__(self, app):
        super().__init__(); self.app = app
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 14, 18, 14); lay.setSpacing(8)
        btns = QHBoxLayout()
        back = QPushButton("Back"); back.setObjectName("ghost"); back.clicked.connect(lambda: self.app.go(0))
        pr = QPushButton("Print / PDF"); pr.setObjectName("primary"); pr.clicked.connect(self.print_pdf)
        btns.addWidget(back); btns.addWidget(pr); btns.addStretch()
        lay.addLayout(btns)
        self.view = QTextBrowser(); lay.addWidget(self.view)
    def show_latest(self, con):
        rows = DB.list_bills(con)
        if not rows: return
        bill, items = DB.get_invoice(con, rows[-1]["id"])
        self.view.setHtml(self._html(bill, items))
    def _html(self, b, items):
        rent = [i for i in items if i["kind"] == "RENTAL"]; flat = [i for i in items if i["kind"] == "FLAT"]
        def cell(v, a="center", bold=False):
            w = "font-weight:700;" if bold else ""
            return f"<td align='{a}' style='padding:4px;{w}'>{v}</td>"
        def rows(rs, rental, start):
            h = ""
            for n, i in enumerate(rs, start):
                extra = cell(f"{i['days']:g}") + cell(f"{i['rate']:,.0f}", "right") if rental else cell(f"{i['rate']:,.0f}", "right")
                h += "<tr>" + cell(n) + cell(i["description"], "left") + cell(f"{i['qty']:g}") + extra + cell(f"{i['amount']:,.0f}", "right") + "</tr>"
            return h
        def head(rental):
            cols = ["S.No", "Description", "Qty"] + (["Days", "Rate/Day"] if rental else ["Rate"]) + ["Amount (&#8377;)"]
            aligns = ["center", "left", "center"] + (["center", "right"] if rental else ["right"]) + ["right"]
            return "<tr style='background:#eef2f7;color:#16324f;font-weight:700;'>" + "".join(
                f"<th align='{a}' style='padding:4px;'>{c}</th>" for c, a in zip(cols, aligns)) + "</tr>"
        def items_table(rental, rs, start):
            return ("<table width='100%' border='1' cellspacing='0' cellpadding='3' bordercolor='#d8e0ea'>"
                    + head(rental) + rows(rs, rental, start) + "</table>")
        return f"""
<div style='font-family:Segoe UI,Arial;'>
<h2 align='center' style='color:{NAVY};letter-spacing:2px;margin-bottom:2px;'>YOUR SHOP NAME</h2>
<p align='center' style='color:#5d6f82;font-size:11px;margin-top:0;'>Shop No. 12, Main Market, Your City &nbsp;|&nbsp; Mo: 98765 43210 &nbsp;|&nbsp; yourshop@email.com</p>
<hr color='{NAVY}'>
<table width='100%'><tr><td><span style='color:#5d6f82;font-size:11px;'>BILLED TO</span><br><b>{b['customer']}</b><br>
<span style='color:#5d6f82;'>Mo: {b['mobile']}</span></td>
<td align='right'><b>Invoice No. {b['bill_no']}</b><br>Date: {DB.disp(b['bill_date'])} &nbsp; Type: {b['type'].title()}<br>Event: {DB.disp(b['event_date'])} &nbsp; Return: {DB.disp(b['return_date'])}</td></tr></table>
<p style='color:#5d6f82;font-size:11px;margin-bottom:2px;'>RENTAL ITEMS</p>
{items_table(True, rent, 1)}
<p style='color:#5d6f82;font-size:11px;margin-bottom:2px;'>SALE &amp; ORDER ITEMS</p>
{items_table(False, flat, len(rent)+1)}
<br>
<table align='right' border='1' cellspacing='0' cellpadding='4' bordercolor='#d8e0ea'>
<tr><td style='padding:4px;'>Charges Total</td><td align='right' style='padding:4px;'>{b['charges']:,.0f}</td></tr>
<tr><td style='padding:4px;'>Security Deposit (refundable)</td><td align='right' style='padding:4px;'>{b['deposit']:,.0f}</td></tr>
<tr><td style='padding:4px;font-weight:700;color:{NAVY};'>Grand Total</td><td align='right' style='padding:4px;font-weight:700;color:{NAVY};'>&#8377;{b['grand']:,.0f}</td></tr>
<tr><td style='padding:4px;'>Advance Paid</td><td align='right' style='padding:4px;'>{b['paid']:,.0f}</td></tr>
<tr><td style='padding:4px;font-weight:700;color:{DUE};'>Balance Due</td><td align='right' style='padding:4px;font-weight:700;color:{DUE};'>&#8377;{b['balance']:,.0f}</td></tr></table>
<p style='color:#5d6f82;font-size:11px;'>Rental items are to be returned by {DB.disp(b['return_date']) if b['return_date'] else 'the agreed date'}. The security deposit is refunded on safe return of all items.</p>
<p align='center' style='color:{NAVY};'><b>Thank you for your business!</b></p></div>"""
    def print_pdf(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save invoice PDF", "invoice.pdf", "PDF (*.pdf)")
        if not path: return
        pr = QPrinter(QPrinter.PrinterMode.HighResolution); pr.setOutputFormat(QPrinter.OutputFormat.PdfFormat); pr.setOutputFileName(path)
        self.view.document().print_(pr)
        QMessageBox.information(self, "PDF", f"Saved to {path}")

class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Your Shop Name - Billing Software")
        self.resize(1120, 720)
        self.demo = "--demo" in sys.argv
        self.con = DB.connect(demo=self.demo)
        if self.demo: DB.seed_demo(self.con)
        central = QWidget(); outer = QVBoxLayout(central); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        bar = QLabel("DESIGN PREVIEW - demo data only, not a real shop  |  final build after your design feedback" if self.demo
                     else "Data is saved in the shop.db file on this PC. Use Backup regularly - keep a copy on another drive too.")
        bar.setObjectName("demobar"); bar.setAlignment(Qt.AlignCenter); outer.addWidget(bar)
        body = QHBoxLayout(); body.setContentsMargins(0, 0, 0, 0); body.setSpacing(0)
        side = QFrame(); side.setObjectName("sidebar"); side.setFixedWidth(215)
        sl = QVBoxLayout(side); sl.setContentsMargins(0, 0, 0, 0); sl.setSpacing(0)
        sl.addWidget(QLabel("Your Shop Name", objectName="brand"))
        sl.addWidget(QLabel("Sale \u2022 Rental \u2022 Wedding Orders", objectName="brandsub"))
        self.navg = QButtonGroup(self); self.nav = []
        for i, label in enumerate(["Home", "Records", "New Bill", "Invoice Preview", "Backup"]):
            b = QPushButton(label); b.setObjectName("nav"); b.setCheckable(True)
            b.clicked.connect(lambda _=False, i=i, l=label: self._nav(i, l))
            self.navg.addButton(b); sl.addWidget(b); self.nav.append(b)
        sl.addStretch()
        body.addWidget(side)
        self.stack = QStackedWidget()
        self.p_dash = Dashboard(self); self.p_dash.build()
        self.p_rec = Records(self); self.p_bill = NewBill(self); self.p_inv = Invoice(self)
        for p in [self.p_dash, self.p_rec, self.p_bill, self.p_inv]: self.stack.addWidget(p)
        body.addWidget(self.stack, 1); outer.addLayout(body)
        self.setCentralWidget(central)
        self.go(0)
    def _nav(self, i, label):
        if label == "Backup":
            r = DB.auto_backup(demo=self.demo)
            msg = f"Backup saved and verified (integrity check passed):\n{r['dest']}" if r["verified"] \
                  else f"Backup written but verification FAILED - do not rely on it:\n{r['dest']}"
            QMessageBox.information(self, "Backup", msg)
            self.go(0); return
        self.go(i)
    def go(self, i):
        self.stack.setCurrentIndex(i)
        for j, b in enumerate(self.nav[:4]): b.setChecked(j == i)
        if i == 3: self.p_inv.show_latest(self.con)
    def new_bill(self, t): self.p_bill.preset(t); self.go(2)
    def refresh_all(self): self.p_dash.refresh(self.con); self.p_rec.refresh(self.con)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    with open(os.path.join(os.path.dirname(__file__), "style.qss")) as f:
        app.setStyleSheet(f.read())
    w = Main()
    if "--shot" in sys.argv or "--demo-shot" in sys.argv:
        w.resize(1120, 720); w.show()
        w.refresh_all()
        out = sys.argv[sys.argv.index("--shot") + 1]
        app.processEvents()
        for i, name in [(0, "dash"), (2, "newbill")]:
            w.go(i); app.processEvents(); w.grab().save(f"{out}/desktop-{name}.png")
        w.p_bill.preset("RENTAL"); w.go(2); app.processEvents()
        w.grab().save(f"{out}/desktop-newbill-rental.png")
        w.go(3); app.processEvents(); w.grab().save(f"{out}/desktop-invoice.png")
        print("shots saved to", out)
        sys.exit(0)
    w.refresh_all(); w.show()
    sys.exit(app.exec())
