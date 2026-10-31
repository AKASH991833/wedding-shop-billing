import sys, os, datetime
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QGridLayout, QLabel, QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem,
    QLineEdit, QComboBox, QDateEdit, QDoubleSpinBox, QFrame, QHeaderView, QTextBrowser,
    QFileDialog, QMessageBox, QAbstractItemView, QButtonGroup, QDialog, QSplashScreen)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QTextDocument, QPixmap
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

ACCENT = "#2f6db3"

class BarChart(QWidget):
    """Simple stacked daily bar chart drawn with QPainter (QtCharts is not in PySide6-Essentials).
    Data: list of (day_label, sales, rent_order). Empty data -> honest empty state text."""
    def __init__(self):
        super().__init__(); self.series = []; self.setMinimumHeight(220)
    def set_data(self, series):
        self.series = series; self.update()
    def paintEvent(self, ev):
        from PySide6.QtGui import QPainter, QColor, QPen, QFont
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        p.fillRect(0, 0, W, H, QColor("#ffffff"))
        if not self.series:
            p.setPen(QColor("#5d6f82")); p.setFont(QFont("Segoe UI", 11))
            r = self.rect(); r.adjust(20, 0, -20, 0)
            p.drawText(r, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, "No entries in this period yet - the chart appears once bills are saved.")
            p.end(); return
        raw_max = max((s + r) for _, s, r in self.series) or 1
        # gridlines land on clean INR steps (1/2/2.5/5 x 10^k), so labels read as round figures
        mag = 10 ** max(0, len(str(int(raw_max))) - 1)
        step = next(b * mag for b in (1, 2, 2.5, 5, 10) if raw_max <= b * mag * 4) / 1
        maxv = step * 4
        left, bottom, topm = 56, 22, 26
        plot_h, plot_w = H - bottom - topm, W - left - 8
        n = len(self.series); slot = plot_w / n; bw = min(26.0, slot * 0.55)
        def inr(v):
            return f"\u20b9{v/1000:g}k" if v >= 1000 else f"\u20b9{int(v)}"
        p.setFont(QFont("Segoe UI", 8))
        for i in range(5):
            gv = step * i
            gy = topm + plot_h - plot_h * i / 4
            p.setPen(QPen(QColor("#e8edf3"), 1)); p.drawLine(left, int(gy), W - 8, int(gy))
            p.setPen(QColor("#5d6f82"))
            p.drawText(0, int(gy) - 7, left - 6, 14, Qt.AlignmentFlag.AlignRight, inr(gv))
        p.setFont(QFont("Segoe UI", 9))
        for i, (lab, s, r) in enumerate(self.series):
            x = left + i * slot + (slot - bw) / 2
            hs = plot_h * s / maxv; hr = plot_h * r / maxv
            y = topm + plot_h
            p.fillRect(int(x), int(y - hr), int(bw), int(hr), QColor(ACCENT))
            p.fillRect(int(x), int(y - hr - hs), int(bw), int(hs), QColor(NAVY))
            p.setPen(QColor("#5d6f82"))
            p.drawText(int(x - slot / 4), int(topm + plot_h + 6), int(slot * 1.5), 14,
                       Qt.AlignmentFlag.AlignHCenter, lab)
        p.setPen(QPen(QColor("#b9c6d4"), 1)); p.drawLine(left, topm + plot_h, W - 8, topm + plot_h)
        # legend
        lx = W - 210
        p.fillRect(lx, 4, 10, 10, QColor(NAVY)); p.setPen(QColor("#1b2836")); p.drawText(lx + 14, 13, "Sales")
        p.fillRect(lx + 70, 4, 10, 10, QColor(ACCENT)); p.drawText(lx + 84, 13, "Rental \u0026 Orders")
        p.end()

class Dashboard(QWidget):
    def __init__(self, app): super().__init__(); self.app = app
    def build(self):
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 14, 18, 14); lay.setSpacing(10)
        grid = QGridLayout(); grid.setSpacing(10)
        self.c_sales = Card("Today's Sales (items sold)")
        self.c_rent = Card("Today's Rental & Order Charges")
        self.c_due = Card("Pending Balance", due=True)
        self.c_dep = Card("Deposits Held (refundable)")
        for i, c in enumerate([self.c_sales, self.c_rent, self.c_due, self.c_dep]): grid.addWidget(c, 0, i)
        lay.addLayout(grid)
        mid = QHBoxLayout(); mid.setSpacing(10)
        left = QFrame(); left.setObjectName("card"); ll = QVBoxLayout(left)
        ll.addWidget(self._sect("LAST 14 DAYS - SALES VS RENTAL & ORDERS"))
        self.chart = BarChart(); ll.addWidget(self.chart)
        mid.addWidget(left, 3)
        right = QFrame(); right.setObjectName("card"); rl = QVBoxLayout(right)
        rl.addWidget(self._sect("RETURNS DUE (7 DAYS)"))
        self.ret_list = QLabel(); self.ret_list.setWordWrap(True)
        self.ret_list.setAlignment(Qt.AlignmentFlag.AlignTop); rl.addWidget(self.ret_list, 1)
        rl.addWidget(self._sect("TOP PENDING BALANCES"))
        self.out_list = QLabel(); self.out_list.setWordWrap(True)
        self.out_list.setAlignment(Qt.AlignmentFlag.AlignTop); rl.addWidget(self.out_list, 1)
        mid.addWidget(right, 2)
        lay.addLayout(mid, 1)
        lay.addWidget(self._sect("RECENT ENTRIES"))
        self.tbl = table(["No.", "Date", "Customer", "Type", "Total", "Balance", "Status"])
        lay.addWidget(self.tbl, 1)
    def _sect(self, s):
        l = QLabel(s); l.setObjectName("sect"); return l
    def refresh(self, con):
        s = DB.stats_today(con, datetime.date.today().isoformat())
        self.c_sales.set(money(s["sales"])); self.c_rent.set(money(s["rent_order"]))
        self.c_due.set(money(s["pending"])); self.c_dep.set(money(s["deposits"]))
        ser = DB.daily_series(con, 14)
        days = []
        for i in range(13, -1, -1):
            dt = datetime.date.today() - datetime.timedelta(days=i)
            e = ser.get(dt.isoformat())
            if e: days.append((dt.strftime("%d %b"), e["sales"], e["rent_order"]))
        self.chart.set_data(days)
        ups = DB.upcoming_returns(con, 7)
        if ups:
            self.ret_list.setText("\n".join(
                f"{'OVERDUE - ' if u['overdue'] else DB.disp(u['return_date']) + ' - '}{DB.customer_label(u)}{(' (' + u['mobile'] + ')') if u['mobile'] else ''}: {u['items'] or '-'}"
                for u in ups))
        else:
            self.ret_list.setText("No rental returns due in the next 7 days.")
        outs = DB.top_outstanding(con, 5)
        if outs:
            self.out_list.setText("\n".join(f"{DB.customer_label(o)} - {money(o['balance'])}" for o in outs))
        else:
            self.out_list.setText("No pending balances.")
        rows = DB.list_bills(con)[:6]
        self.tbl.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, v in enumerate([r["bill_no"], DB.disp(r["bill_date"]), DB.customer_label(r), DB.display_type(r, short=True),
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
        from PySide6.QtWidgets import QHeaderView
        hh = self.tbl.horizontalHeader()
        for c in range(self.tbl.columnCount()): hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tbl.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        lay.addWidget(self.tbl)
        brow = QHBoxLayout()
        pay = QPushButton("Record Payment..."); pay.setObjectName("primary"); pay.clicked.connect(self._payment)
        brow.addWidget(pay)
        b = QPushButton("Export records (CSV)"); b.setObjectName("ghost"); b.clicked.connect(self.export)
        brow.addWidget(b); brow.addStretch()
        lay.addLayout(brow)
        note = QLabel("Excel (.xlsx) export with styled headers comes with the openpyxl extra.")
        note.setObjectName("statl"); lay.addWidget(note)
    def refresh(self, con):
        f = self.flt.currentText()
        rows = DB.list_bills(con, None if f == "All" else f)
        self.rows = rows
        self.tbl.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, v in enumerate([r["bill_no"], DB.disp(r["bill_date"]), DB.customer_label(r), r["mobile"] or "-", DB.display_type(r, short=True),
                                   money(r["grand"]), money(r["paid"]), money(r["balance"]),
                                   DB.disp(r["return_date"] or r["event_date"]), r["status"]]):
                self.tbl.setItem(i, j, QTableWidgetItem(str(v)))
    def _payment(self):
        i = self.tbl.currentRow()
        if i < 0 or i >= len(self.rows):
            QMessageBox.information(self, "Select", "Select a bill row first"); return
        r = self.rows[i]
        if r["balance"] <= 0:
            QMessageBox.information(self, "Settled", f"Bill {r['bill_no']} has no balance due."); return
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout
        dlg = QDialog(self); dlg.setWindowTitle(f"Record payment - Bill {r['bill_no']} ({r['customer']})")
        fl = QFormLayout(dlg)
        amt = QDoubleSpinBox(); amt.setMaximum(10**9); amt.setPrefix("\u20b9 "); amt.setValue(r["balance"])
        mode = QComboBox(); mode.addItems(["Cash", "UPI", "Card", "Bank Transfer"])
        fl.addRow("Balance due", QLabel(money(r["balance"])))
        fl.addRow("Amount received", amt); fl.addRow("Mode", mode)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject); fl.addRow(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        try: DB.add_payment(self.app.con, r["id"], amt.value(), mode.currentText())
        except ValueError as e:
            QMessageBox.warning(self, "Not saved", str(e)); return
        self.app.refresh_all()
        QMessageBox.information(self, "Saved", f"Payment of {money(amt.value())} recorded for bill {r['bill_no']}.")
    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export records", "records.csv", "CSV (*.csv)")
        if not path: return
        import csv
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["No", "Date", "Customer", "Mobile", "Type", "Total", "Advance", "Balance", "Return/Delivery", "Status"])
            for r in self.rows:
                w.writerow([r["bill_no"], DB.disp(r["bill_date"]), r["customer"], r["mobile"], DB.display_type(r),
                            r["grand"], r["paid"], r["balance"], DB.disp(r["return_date"] or r["event_date"]), r["status"]])
        QMessageBox.information(self, "Export", f"Saved to {path}")

class NewBill(QWidget):
    def __init__(self, app):
        super().__init__(); self.app = app
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 14, 18, 14); lay.setSpacing(10)
        warn = QLabel("Demo mode - these entries go to the demo database, not real shop records." if app.demo else "Entries are saved to shop.db on this PC. Keep regular backups.")
        warn.setObjectName("warnbox"); warn.setWordWrap(True); lay.addWidget(warn)
        row = QGridLayout(); row.setSpacing(8)
        self.name = QLineEdit(); self.name.setPlaceholderText("Customer name (optional)")
        self.mobile = QLineEdit(); self.mobile.setPlaceholderText("Mobile (optional)")
        self.addr = QLineEdit(); self.addr.setPlaceholderText("Address (optional)")
        self.type = QComboBox(); self.type.addItems(["SALE", "RENTAL", "WEDDING"])
        self.type.currentTextChanged.connect(self._type_changed)
        self.ret = QDateEdit(QDate.currentDate().addDays(3)); self.ret.setCalendarPopup(True); self.ret.setDisplayFormat("dd MMM yyyy")
        self.retL = QLabel("Return Date (Rental)")
        row.addWidget(QLabel("Customer"), 0, 0); row.addWidget(self.name, 0, 1)
        row.addWidget(QLabel("Mobile"), 0, 2); row.addWidget(self.mobile, 0, 3)
        row.addWidget(QLabel("Address"), 1, 0); row.addWidget(self.addr, 1, 1)
        row.addWidget(QLabel("Order Type"), 1, 2); row.addWidget(self.type, 1, 3)
        row.addWidget(self.retL, 2, 2); row.addWidget(self.ret, 2, 3)
        lay.addLayout(row)
        self.items = table(["Description", "Type", "Qty", "Days", "Rate", "Amount"])
        self.items.horizontalHeader().setSectionResizeMode(0, self.items.horizontalHeader().ResizeMode.Stretch)
        self.items.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
        self.items.verticalHeader().setDefaultSectionSize(38)
        self.items.cellChanged.connect(self._cell)
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
    def refresh(self, con):
        for r in range(self.items.rowCount()):
            d = self.items.cellWidget(r, 0)
            if d: self._fill_catalog(d)
    KINDS = {"Sale": "SALE", "Rental": "RENTAL", "Order": "ORDER"}
    def _type_changed(self, t):
        self.retL.setText("Return Date (Rental)" if t == "RENTAL" else ("Delivery / Event Date" if t == "WEDDING" else "Return / Event Date"))
        self._recalc()
    def _add_row(self):
        r = self.items.rowCount(); self.items.insertRow(r)
        for c, v in enumerate(["", "", "1", "1", "", ""]):
            if c not in (0, 1): self.items.setItem(r, c, QTableWidgetItem(v))
        desc = QComboBox(); desc.setEditable(True)
        desc.lineEdit().setPlaceholderText("Type or pick a catalog item")
        self._fill_catalog(desc)
        desc.lineEdit().editingFinished.connect(lambda r=r: self._desc_done(r))
        desc.activated.connect(lambda _i, r=r: self._desc_done(r))
        self.items.setCellWidget(r, 0, desc)
        kind = QComboBox(); kind.addItems(["Sale", "Rental", "Order"])
        kind.currentTextChanged.connect(self._recalc)
        self.items.setCellWidget(r, 1, kind)
    def _fill_catalog(self, combo):
        combo.blockSignals(True); cur = combo.currentText(); combo.clear()
        combo.addItem("")
        for x in DB.list_inventory(self.app.con): combo.addItem(x["name"])
        combo.setCurrentText(cur); combo.blockSignals(False)
    def _desc_done(self, row):
        combo = self.items.cellWidget(row, 0)
        name = combo.currentText().strip() if combo else ""
        match = next((x for x in DB.list_inventory(self.app.con) if x["name"] == name), None)
        if match:
            kindc = self.items.cellWidget(row, 1)
            kindc.blockSignals(True)
            kindc.setCurrentText("Rental" if match["rent_rate_day"] else "Sale")
            kindc.blockSignals(False)
            self.items.blockSignals(True)
            self.items.setItem(row, 4, QTableWidgetItem(f"{(match['rent_rate_day'] or match['sale_price'] or 0):g}"))
            self.items.blockSignals(False)
        self._recalc()
    def _cell(self, row, col):
        if col == 0:
            name = (self.items.item(row, col).text() if self.items.item(row, col) else "").strip()
            match = next((x for x in DB.list_inventory(self.app.con) if x["name"] == name), None)
            if match:
                combo = self.items.cellWidget(row, 1)
                combo.blockSignals(True)
                combo.setCurrentText("Rental" if match["rent_rate_day"] else "Sale")
                combo.blockSignals(False)
                self.items.blockSignals(True)
                self.items.setItem(row, 4, QTableWidgetItem(f"{(match['rent_rate_day'] or match['sale_price'] or 0):g}"))
                self.items.blockSignals(False)
        self._recalc()
    def _rows(self):
        out = []
        for r in range(self.items.rowCount()):
            g = lambda c: (self.items.item(r, c).text() if self.items.item(r, c) else "").strip()
            dcombo = self.items.cellWidget(r, 0)
            desc = dcombo.currentText().strip() if dcombo else g(0)
            combo = self.items.cellWidget(r, 1)
            kind_label = combo.currentText() if combo else "Sale"
            try: q = float(g(2) or 0); d = float(g(3) or 1); rate = float(g(4) or 0)
            except ValueError: q, d, rate = 0, 1, 0
            if kind_label != "Rental": d = 1.0
            amt = q * d * rate
            out.append({"description": desc, "kind": self.KINDS[kind_label],
                        "qty": q, "days": d, "rate": rate, "amount": amt})
        return out
    def _recalc(self, *_):
        rows = self._rows()
        for i, it in enumerate(rows):
            self.items.blockSignals(True)
            self.items.setItem(i, 5, QTableWidgetItem(money(it["amount"])))
            self.items.blockSignals(False)
        items_total = sum(r["amount"] for r in rows)
        dep, adv = self.dep.value(), self.adv.value()
        grand = items_total + dep
        self.tots.setText(f"Items {money(items_total)}   + Deposit {money(dep)}   = Grand {money(grand)}   |   Advance {money(adv)}   |   Balance Due {money(max(grand-adv,0))}")
        self._grand, self._items_total = grand, items_total
    def _save(self):
        rows = [r for r in self._rows() if r["description"]]
        if not rows:
            QMessageBox.warning(self, "Missing", "Add at least one item before saving."); return
        DB.add_bill(self.app.con, self.name.text().strip(), self.mobile.text().strip(),
                    self.type.currentText(), datetime.date.today().isoformat(), rows,
                    advance=self.adv.value(), deposit=self.dep.value(),
                    return_date=self.ret.date().toString("yyyy-MM-dd") if any(r["kind"] == "RENTAL" for r in rows) else None,
                    address=self.addr.text().strip())
        self.name.clear(); self.mobile.clear(); self.addr.clear(); self.adv.setValue(0); self.dep.setValue(0)
        while self.items.rowCount(): self.items.removeRow(0)
        self._add_row(); self._recalc()
        self.app.refresh_all()
        QMessageBox.information(self, "Saved", "Bill saved.")
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
        bill, items = DB.get_invoice(con, rows[0]["id"])
        self.view.setHtml(self._html(bill, items))
    def _html(self, b, items):
        rent = [i for i in items if i["kind"] == "RENTAL"]; flat = [i for i in items if i["kind"] != "RENTAL"]
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
        prof = DB.shop_profile(self.app.con)
        prof_parts = ([prof["address"]] if prof["address"] else []) + \
                     ([f"Mo: {prof['phone']}"] if prof["phone"] else []) + \
                     ([prof["email"]] if prof["email"] else [])
        logo = DB.shop_logo(self.app.con)
        logo_img = f"<p align='center' style='margin-bottom:0;'><img src='file://{logo}' height='68'></p>" if logo else ""
        cust_lines = ([f"<b>{b['customer']}</b>"] if b["customer"] else ["<b>Walk-in customer</b>"]) + \
                     ([f"Mo: {b['mobile']}"] if b["mobile"] else []) + \
                     ([b["customer_address"]] if b["customer_address"] else [])
        billed_to = "<br>".join(cust_lines)
        def band(text, bg):
            return (f"<table width='100%'><tr><td style='background:{bg};color:#ffffff;padding:5px 8px;"
                    f"font-weight:700;font-size:12px;letter-spacing:1px;'>{text}</td></tr></table>")
        return f"""
<div style='font-family:Segoe UI,Arial;'>
{logo_img}
<h2 align='center' style='color:{NAVY};letter-spacing:2px;margin-bottom:2px;'>{prof['name'].upper()}</h2>
{f"<p align='center' style='color:#5d6f82;font-size:11px;margin-top:0;'>{' &nbsp;|&nbsp; '.join(prof_parts)}</p>" if prof_parts else ''}
<hr color='{NAVY}'>
<table width='100%'><tr><td><span style='color:#5d6f82;font-size:11px;'>BILLED TO</span><br>{billed_to}</td>
<td align='right'><b>Invoice No. {b['bill_no']}</b><br>Date: {DB.disp(b['bill_date'])} &nbsp; Type: {DB.display_type(b)}{f"<br>Event: {DB.disp(b['event_date'])}" if b['event_date'] else ''}{f" &nbsp; Return: {DB.disp(b['return_date'])}" if b['return_date'] else ''}</td></tr></table>
{band('RENTAL ITEMS - charged per day', NAVY) if rent else ''}
{items_table(True, rent, 1) if rent else ''}
{band('SALE &amp; ORDER ITEMS', '#5d6f82') if flat else ''}
{items_table(False, flat, len(rent)+1) if flat else ''}
<br>
<table align='right' border='1' cellspacing='0' cellpadding='4' bordercolor='#d8e0ea'>
<tr><td style='padding:4px;'>Charges Total</td><td align='right' style='padding:4px;'>{b['charges']:,.0f}</td></tr>
<tr><td style='padding:4px;'>Security Deposit (refundable)</td><td align='right' style='padding:4px;'>{b['deposit']:,.0f}</td></tr>
<tr><td style='padding:4px;font-weight:700;color:{NAVY};'>Grand Total</td><td align='right' style='padding:4px;font-weight:700;color:{NAVY};'>&#8377;{b['grand']:,.0f}</td></tr>
<tr><td style='padding:4px;'>Paid (advance + payments)</td><td align='right' style='padding:4px;'>{b['paid']:,.0f}</td></tr>
<tr><td style='padding:4px;font-weight:700;color:{DUE};'>Balance Due</td><td align='right' style='padding:4px;font-weight:700;color:{DUE};'>&#8377;{b['balance']:,.0f}</td></tr></table>
{f"<p style='color:#5d6f82;font-size:11px;'>Rental items are to be returned by {DB.disp(b['return_date']) if b['return_date'] else 'the agreed date'}.{(' The security deposit of &#8377;' + format(b['deposit'], ',.0f') + ' is refunded on safe return of all items.') if b['deposit'] else ''}</p>" if rent else ''}
<p align='center' style='color:{NAVY};'><b>Thank you for your business!</b></p></div>"""
    def render_pdf(self, path):
        """Print the invoice to a real A4 PDF, laid out to fill the printable page."""
        from PySide6.QtGui import QPageSize
        from PySide6.QtCore import QSizeF
        pr = QPrinter(QPrinter.PrinterMode.HighResolution)
        pr.setOutputFormat(QPrinter.OutputFormat.PdfFormat); pr.setOutputFileName(path)
        pr.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        area = pr.pageRect(QPrinter.Unit.Point)
        doc = self.view.document().clone()
        doc.setPageSize(QSizeF(area.width(), area.height()))
        doc.print_(pr)
    def print_pdf(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save invoice PDF", "invoice.pdf", "PDF (*.pdf)")
        if not path: return
        self.render_pdf(path)
        QMessageBox.information(self, "PDF", f"Saved to {path}")


class ReturnsPage(QWidget):
    def __init__(self, app):
        super().__init__(); self.app = app
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 14, 18, 14); lay.setSpacing(10)
        self.overdue = QLabel(); self.overdue.setObjectName("warnbox"); self.overdue.setWordWrap(True)
        lay.addWidget(self.overdue)
        lay.addWidget(self._sect("ACTIVE RENTALS (not yet returned)"))
        self.tbl = table(["No.", "Customer", "Mobile", "Total", "Balance", "Return Date", "Status"])
        self.tbl.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        lay.addWidget(self.tbl)
        btns = QHBoxLayout()
        m = QPushButton("Mark Returned (garments physically back)"); m.setObjectName("primary"); m.clicked.connect(self._mark)
        r = QPushButton("Record Deposit Refund..."); r.setObjectName("ghost"); r.clicked.connect(self._refund)
        btns.addWidget(m); btns.addWidget(r); btns.addStretch(); lay.addLayout(btns)
        note = QLabel("Marking a return only records the garments coming back - the deposit refund is recorded separately, with any deduction for damage or late fees.")
        note.setObjectName("statl"); note.setWordWrap(True); lay.addWidget(note)
    def _sect(self, s):
        l = QLabel(s); l.setObjectName("sect"); return l
    def refresh(self, con):
        ov = DB.overdue_rentals(con)
        if ov:
            txt = "OVERDUE - chase these returns: " + "  |  ".join(
                f"{o['customer']} ({o['mobile']}) - {o['description']}, {o['days_overdue']} day(s) late" for o in ov)
            self.overdue.setText(txt); self.overdue.show()
        else:
            self.overdue.setText("No overdue rentals."); self.overdue.show()
        self.rows = [r for r in DB.list_bills(con) if "RENTAL" in (r["kinds"] or "") and not r["returned_at"]]
        ovd = {o["bill_id"]: o["days_overdue"] for o in ov}
        self.tbl.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            status = f"OVERDUE {ovd[r['id']]}d" if r["id"] in ovd else r["status"]
            for j, v in enumerate([r["bill_no"], DB.customer_label(r), r["mobile"] or "-", money(r["grand"]),
                                   money(r["balance"]), DB.disp(r["return_date"]), status]):
                self.tbl.setItem(i, j, QTableWidgetItem(str(v)))
    def _selected(self):
        i = self.tbl.currentRow()
        if i < 0 or i >= len(self.rows):
            QMessageBox.information(self, "Select", "Select a rental row first"); return None
        return self.rows[i]
    def _mark(self):
        r = self._selected()
        if not r: return
        DB.mark_returned(self.app.con, r["id"], datetime.date.today().isoformat())
        self.app.refresh_all()
        QMessageBox.information(self, "Returned", f"Bill {r['bill_no']} marked returned. Deposit is still HELD - record the refund separately.")
    def _refund(self):
        r = self._selected()
        if not r: return
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout
        dlg = QDialog(self); dlg.setWindowTitle(f"Deposit refund - Bill {r['bill_no']} ({r['customer']})")
        fl = QFormLayout(dlg)
        held = r["deposit"] - r["deposit_refunded"]
        refund = QDoubleSpinBox(); refund.setMaximum(10**9); refund.setPrefix("\u20b9 "); refund.setValue(held)
        ded = QDoubleSpinBox(); ded.setMaximum(10**9); ded.setPrefix("\u20b9 ")
        note = QLineEdit(); note.setPlaceholderText("Deduction reason (damage / late fee)")
        fl.addRow(f"Deposit held: {money(held)}", QLabel(""))
        fl.addRow("Refund to customer", refund); fl.addRow("Deduction (kept by shop)", ded); fl.addRow("Deduction note", note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept); bb.rejected.connect(dlg.reject); fl.addRow(bb)
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        try:
            status = DB.record_deposit_refund(self.app.con, r["id"], refund.value(), ded.value(), note.text().strip())
        except ValueError as e:
            QMessageBox.warning(self, "Refund rejected", str(e)); return
        self.app.refresh_all()
        QMessageBox.information(self, "Refund recorded", f"Status: {status}")

class StockPage(QWidget):
    def __init__(self, app):
        super().__init__(); self.app = app
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 14, 18, 14); lay.setSpacing(10)
        lay.addWidget(self._sect("STOCK / INVENTORY"))
        self.tbl = table(["Item", "Category", "Total Qty", "On Hand Now", "Rent Rate/Day", "Sale Price"])
        lay.addWidget(self.tbl)
        form = QGridLayout(); form.setSpacing(8)
        self.nm = QLineEdit(); self.nm.setPlaceholderText("Item name (exactly as used on bills)")
        self.cat = QComboBox(); self.cat.addItems(["rental", "sale"])
        self.qty = QDoubleSpinBox(); self.qty.setMaximum(10**6); self.qty.setValue(1)
        self.rr = QDoubleSpinBox(); self.rr.setMaximum(10**9); self.rr.setPrefix("\u20b9 ")
        self.sp = QDoubleSpinBox(); self.sp.setMaximum(10**9); self.sp.setPrefix("\u20b9 ")
        form.addWidget(QLabel("Item"), 0, 0); form.addWidget(self.nm, 0, 1)
        form.addWidget(QLabel("Type"), 0, 2); form.addWidget(self.cat, 0, 3)
        form.addWidget(QLabel("Qty"), 1, 0); form.addWidget(self.qty, 1, 1)
        form.addWidget(QLabel("Rent/Day"), 1, 2); form.addWidget(self.rr, 1, 3)
        form.addWidget(QLabel("Sale Price"), 1, 4); form.addWidget(self.sp, 1, 5)
        add = QPushButton("Add Item"); add.setObjectName("primary"); add.clicked.connect(self._add)
        form.addWidget(add, 1, 6)
        lay.addLayout(form)
        lay.addWidget(self._sect("CHECK AVAILABILITY FOR A DATE RANGE"))
        av = QGridLayout(); av.setSpacing(8)
        self.aitem = QComboBox()
        self.afrom = QDateEdit(QDate.currentDate()); self.afrom.setCalendarPopup(True); self.afrom.setDisplayFormat("dd MMM yyyy")
        self.ato = QDateEdit(QDate.currentDate().addDays(3)); self.ato.setCalendarPopup(True); self.ato.setDisplayFormat("dd MMM yyyy")
        chk = QPushButton("Check"); chk.setObjectName("ghost"); chk.clicked.connect(self._check)
        av.addWidget(QLabel("Item"), 0, 0); av.addWidget(self.aitem, 0, 1)
        av.addWidget(QLabel("From"), 0, 2); av.addWidget(self.afrom, 0, 3)
        av.addWidget(QLabel("To"), 0, 4); av.addWidget(self.ato, 0, 5)
        av.addWidget(chk, 0, 6)
        lay.addLayout(av)
        self.aresult = QLabel(""); self.aresult.setWordWrap(True); lay.addWidget(self.aresult)
        lay.addStretch()
    def _sect(self, s):
        l = QLabel(s); l.setObjectName("sect"); return l
    def refresh(self, con):
        items = DB.list_inventory(con)
        self.items = items
        self.tbl.setRowCount(len(items))
        for i, it in enumerate(items):
            onhand = DB.physical_on_hand(con, it["id"])
            for j, v in enumerate([it["name"], it["category"], f"{it['total_qty']:g}", f"{onhand:g}",
                                   money(it["rent_rate_day"]) if it["rent_rate_day"] else "-",
                                   money(it["sale_price"]) if it["sale_price"] else "-"]):
                self.tbl.setItem(i, j, QTableWidgetItem(str(v)))
        cur = self.aitem.currentText()
        self.aitem.clear(); self.aitem.addItems([it["name"] for it in items])
        if cur: self.aitem.setCurrentText(cur)
    def _add(self):
        if not self.nm.text().strip():
            QMessageBox.warning(self, "Missing", "Enter an item name"); return
        DB.add_inventory_item(self.app.con, self.nm.text().strip(), self.cat.currentText(),
                              self.qty.value(), self.sp.value() or None, self.rr.value() or None)
        self.nm.clear(); self.qty.setValue(1); self.rr.setValue(0); self.sp.setValue(0)
        self.app.refresh_all()
    def _check(self):
        it = next((x for x in self.items if x["name"] == self.aitem.currentText()), None)
        if not it: return
        r = DB.check_reservation(self.app.con, it["id"],
                                 self.afrom.date().toString("yyyy-MM-dd"), self.ato.date().toString("yyyy-MM-dd"))
        msg = f"{r['item']}: {r['available']:g} of {r['total']:g} available for these dates."
        if r["overdue_conflicts"]:
            msg += "  WARNING - overdue returns blocking stock: " + "; ".join(
                f"{c['customer']} ({c['days_overdue']}d late)" for c in r["overdue_conflicts"])
            self.aresult.setStyleSheet(f"color:{DUE};font-weight:700;")
        else:
            self.aresult.setStyleSheet(f"color:{NAVY};font-weight:700;")
        self.aresult.setText(msg)

class CustomersPage(QWidget):
    def __init__(self, app):
        super().__init__(); self.app = app
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 14, 18, 14); lay.setSpacing(10)
        lay.addWidget(self._sect("CUSTOMER LEDGER"))
        self.pick = QComboBox(); self.pick.currentIndexChanged.connect(lambda _: self.refresh(self.app.con))
        lay.addWidget(self.pick)
        grid = QGridLayout(); grid.setSpacing(10)
        self.c_billed = Card("Total Billed"); self.c_paid = Card("Total Paid"); self.c_out = Card("Outstanding", due=True)
        for i, c in enumerate([self.c_billed, self.c_paid, self.c_out]): grid.addWidget(c, 0, i)
        lay.addLayout(grid)
        self.tbl = table(["No.", "Date", "Type", "Total", "Paid", "Balance", "Status"])
        lay.addWidget(self.tbl)
    def _sect(self, s):
        l = QLabel(s); l.setObjectName("sect"); return l
    def refresh(self, con):
        custs = DB.list_customers(con)
        if self.pick.count() != len(custs):
            self.pick.blockSignals(True)
            self.pick.clear()
            for c in custs:
                label = c["name"] or f"Walk-in #{c['id']}"
                self.pick.addItem(label, c["id"])
            self.pick.blockSignals(False)
        by_id = {c["id"]: c for c in custs}
        c = by_id.get(self.pick.currentData())
        if not c:
            self.c_billed.set("\u20b90"); self.c_paid.set("\u20b90"); self.c_out.set("\u20b90")
            self.tbl.setRowCount(0); return
        rows, summ = DB.customer_ledger(con, c["id"])
        self.c_billed.set(money(summ["billed"])); self.c_paid.set(money(summ["paid"])); self.c_out.set(money(summ["outstanding"]))
        self.tbl.setRowCount(len(rows))
        for i, r in enumerate(reversed(rows)):
            for j, v in enumerate([r["bill_no"], DB.disp(r["bill_date"]), DB.display_type(r, short=True), money(r["grand"]),
                                   money(r["paid"]), money(r["balance"]), r["status"]]):
                self.tbl.setItem(i, j, QTableWidgetItem(str(v)))

class ReportsPage(QWidget):
    def __init__(self, app):
        super().__init__(); self.app = app
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 14, 18, 14); lay.setSpacing(10)
        lay.addWidget(self._sect("DATE RANGE REPORT"))
        row = QGridLayout(); row.setSpacing(8)
        self.frm = QDateEdit(QDate.currentDate().addDays(-30)); self.frm.setCalendarPopup(True); self.frm.setDisplayFormat("dd MMM yyyy")
        self.to = QDateEdit(QDate.currentDate()); self.to.setCalendarPopup(True); self.to.setDisplayFormat("dd MMM yyyy")
        run = QPushButton("Run Report"); run.setObjectName("primary"); run.clicked.connect(self._run)
        row.addWidget(QLabel("From"), 0, 0); row.addWidget(self.frm, 0, 1)
        row.addWidget(QLabel("To"), 0, 2); row.addWidget(self.to, 0, 3)
        row.addWidget(run, 0, 4)
        lay.addLayout(row)
        grid = QGridLayout(); grid.setSpacing(10)
        self.c_sales = Card("Sales (sale bills)")
        self.c_rent = Card("Rental & Order Charges")
        self.c_coll = Card("Collected (advances + payments)")
        self.c_dep = Card("Deposits Held (refundable - not revenue)")
        for i, c in enumerate([self.c_sales, self.c_rent, self.c_coll, self.c_dep]): grid.addWidget(c, 0, i)
        lay.addLayout(grid)
        note = QLabel("Refundable security deposits are never counted as sales or charges. This report shows business activity, not profit.")
        note.setObjectName("statl"); note.setWordWrap(True); lay.addWidget(note)
        lay.addStretch()
    def _sect(self, s):
        l = QLabel(s); l.setObjectName("sect"); return l
    def refresh(self, con):
        self._run()
    def _run(self):
        r = DB.date_report(self.app.con, self.frm.date().toString("yyyy-MM-dd"), self.to.date().toString("yyyy-MM-dd"))
        self.c_sales.set(money(r["sales"])); self.c_rent.set(money(r["rental_order_charges"]))
        self.c_coll.set(money(r["collected"])); self.c_dep.set(money(r["deposits_held_refundable"]))


class SettingsPage(QWidget):
    def __init__(self, app):
        super().__init__(); self.app = app
        lay = QVBoxLayout(self); lay.setContentsMargins(18, 14, 18, 14); lay.setSpacing(10)
        lay.addWidget(self._sect("SHOP PROFILE (printed on invoices)"))
        prof = QGridLayout(); prof.setSpacing(8)
        self.s_name = QLineEdit(); self.s_addr = QLineEdit(); self.s_phone = QLineEdit(); self.s_email = QLineEdit()
        prof.addWidget(QLabel("Shop Name"), 0, 0); prof.addWidget(self.s_name, 0, 1)
        prof.addWidget(QLabel("Address"), 0, 2); prof.addWidget(self.s_addr, 0, 3)
        prof.addWidget(QLabel("Phone"), 1, 0); prof.addWidget(self.s_phone, 1, 1)
        prof.addWidget(QLabel("Email"), 1, 2); prof.addWidget(self.s_email, 1, 3)
        lay.addLayout(prof)
        b = QPushButton("Save Shop Profile"); b.setObjectName("primary"); b.clicked.connect(self._save_profile)
        lay.addWidget(b)
        lrow = QHBoxLayout(); lrow.setSpacing(10)
        self.logo_prev = QLabel("No logo set"); self.logo_prev.setObjectName("statl")
        self.logo_prev.setFixedHeight(64); self.logo_prev.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        lpick = QPushButton("Choose Logo Image..."); lpick.setObjectName("ghost"); lpick.clicked.connect(self._logo)
        lclr = QPushButton("Remove Logo"); lclr.setObjectName("ghost"); lclr.clicked.connect(self._logo_clear)
        lrow.addWidget(self.logo_prev, 1); lrow.addWidget(lpick); lrow.addWidget(lclr)
        lay.addLayout(lrow)
        lnote = QLabel("The logo prints above the shop name on invoices. It is stored only on this PC.")
        lnote.setObjectName("statl"); lnote.setWordWrap(True); lay.addWidget(lnote)
        lay.addWidget(self._sect("SECURITY"))
        sec = QGridLayout(); sec.setSpacing(8)
        self.pw_cur = QLineEdit(); self.pw_cur.setEchoMode(QLineEdit.EchoMode.Password); self.pw_cur.setPlaceholderText("Current password")
        self.pw_new = QLineEdit(); self.pw_new.setEchoMode(QLineEdit.EchoMode.Password); self.pw_new.setPlaceholderText("New password (min 8 characters)")
        self.pw_con = QLineEdit(); self.pw_con.setEchoMode(QLineEdit.EchoMode.Password); self.pw_con.setPlaceholderText("Confirm new password")
        sec.addWidget(self.pw_cur, 0, 0); sec.addWidget(self.pw_new, 0, 1); sec.addWidget(self.pw_con, 0, 2)
        lay.addLayout(sec)
        b = QPushButton("Set / Change Password"); b.setObjectName("primary"); b.clicked.connect(self._set_pw)
        lay.addWidget(b)
        self.pw_note = QLabel(); self.pw_note.setObjectName("statl"); lay.addWidget(self.pw_note)
        lay.addWidget(self._sect("BACKUP & DATA"))
        self.path_lab = QLabel(); self.path_lab.setObjectName("statl"); self.path_lab.setWordWrap(True)
        lay.addWidget(self.path_lab)
        row = QHBoxLayout()
        bb = QPushButton("Back Up Now (verified)"); bb.setObjectName("primary"); bb.clicked.connect(self._backup)
        rb = QPushButton("Restore from Backup File..."); rb.setObjectName("ghost"); rb.clicked.connect(self._restore)
        row.addWidget(bb); row.addWidget(rb); row.addStretch(); lay.addLayout(row)
        lay.addWidget(self._sect("RENTAL POLICY"))
        self.tap = QComboBox(); self.tap.addItems([
            "Item can be re-booked ON its return date (same-day turnaround)",
            "Item is free the day AFTER its return date"])
        self.tap.currentIndexChanged.connect(self._policy)
        lay.addWidget(self.tap)
        lay.addStretch()
    def _sect(self, s):
        l = QLabel(s); l.setObjectName("sect"); return l
    def refresh(self, con):
        p = DB.shop_profile(con)
        self.s_name.setText(p["name"]); self.s_addr.setText(p["address"])
        self.s_phone.setText(p["phone"]); self.s_email.setText(p["email"])
        self.pw_note.setText("App locks on startup - password is set." if DB.has_password(con)
                             else "No password set - the app opens without one. Set one to lock it on startup.")
        self.pw_cur.setVisible(DB.has_password(con))
        if self.app.demo:
            self.path_lab.setText("Data location: the app's data folder on this PC (demo database) | automatic verified backup on every exit")
        else:
            self.path_lab.setText(f"Data file: {DB.db_path(self.app.demo)} | Backups: {DB.APP_DIR}/backups/ (auto-backup on every exit)")
        self.tap.blockSignals(True)
        self.tap.setCurrentIndex(0 if DB.SAME_DAY_TURNAROUND else 1)
        self.tap.blockSignals(False)
        self._logo_show()
    def _logo(self):
        from PySide6.QtGui import QPixmap
        path, _ = QFileDialog.getOpenFileName(self, "Choose logo image", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if not path: return
        import shutil as _sh
        ext = path.rsplit(".", 1)[-1].lower()
        dest = os.path.join(DB.APP_DIR, f"shop-logo.{ext}")
        _sh.copy(path, dest)
        DB.set_setting(self.app.con, "shop_logo", dest)
        self._logo_show()
        QMessageBox.information(self, "Logo saved", "Logo saved on this PC - it will print on new invoices.")
    def _logo_clear(self):
        DB.set_setting(self.app.con, "shop_logo", "")
        self._logo_show()
    def _logo_show(self):
        from PySide6.QtGui import QPixmap
        p = DB.shop_logo(self.app.con)
        if p:
            pm = QPixmap(p)
            if not pm.isNull():
                self.logo_prev.setPixmap(pm.scaledToHeight(56, Qt.TransformationMode.SmoothTransformation)); return
        self.logo_prev.setPixmap(QPixmap()); self.logo_prev.setText("No logo set")
    def _save_profile(self):
        con = self.app.con
        DB.set_setting(con, "shop_name", self.s_name.text().strip() or "Your Shop Name")
        DB.set_setting(con, "shop_address", self.s_addr.text().strip())
        DB.set_setting(con, "shop_phone", self.s_phone.text().strip())
        DB.set_setting(con, "shop_email", self.s_email.text().strip())
        self.app._apply_brand()
        QMessageBox.information(self, "Saved", "Shop profile saved - it now shows on the app and new invoices.")
    def _set_pw(self):
        con = self.app.con
        if DB.has_password(con) and not DB.verify_password(con, self.pw_cur.text()):
            QMessageBox.warning(self, "Wrong password", "Current password is incorrect."); return
        if self.pw_new.text() != self.pw_con.text():
            QMessageBox.warning(self, "Mismatch", "New passwords do not match."); return
        try: DB.set_password(con, self.pw_new.text())
        except ValueError as e:
            QMessageBox.warning(self, "Too short", str(e)); return
        self.pw_cur.clear(); self.pw_new.clear(); self.pw_con.clear()
        self.refresh(con)
        QMessageBox.information(self, "Password updated", "Password saved. The app will ask for it on next start.")
    def _backup(self):
        r = DB.auto_backup(demo=self.app.demo)
        msg = f"Backup saved and verified (integrity check passed):\n{r['dest']}" if r["verified"] \
              else f"Backup written but verification FAILED - do not rely on it:\n{r['dest']}"
        QMessageBox.information(self, "Backup", msg)
    def _restore(self):
        path, _ = QFileDialog.getOpenFileName(self, "Restore from backup", str(DB.APP_DIR), "SQLite backup (*.db)")
        if not path: return
        ans = QMessageBox.question(self, "Confirm restore", "This replaces ALL current data with the backup. Continue?")
        if ans != QMessageBox.StandardButton.Yes: return
        try: r = DB.restore_db(path, demo=self.app.demo)
        except ValueError as e:
            QMessageBox.warning(self, "Not restored", str(e)); return
        self.app.refresh_all()
        QMessageBox.information(self, "Restored", f"Data restored and verified:\n{r['restored']}")
    def _policy(self, i):
        DB.set_setting(self.app.con, "same_day_turnaround", "1" if i == 0 else "0")
        DB.apply_turnaround_policy(self.app.con)

class LockDialog(QDialog):
    """Startup lock: shop logo + name on top, password below. 3 wrong tries close the app."""
    def __init__(self, con):
        super().__init__()
        self.con = con; self.ok = False; self.tries = 0
        self.setWindowTitle("Shop Billing - Locked")
        self.setMinimumWidth(340)
        lay = QVBoxLayout(self); lay.setContentsMargins(32, 24, 32, 24); lay.setSpacing(10)
        logo = DB.shop_logo(con)
        if logo:
            pm = QPixmap(logo)
            if not pm.isNull():
                l = QLabel(); l.setAlignment(Qt.AlignmentFlag.AlignCenter)
                l.setPixmap(pm.scaled(280, 160, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                lay.addWidget(l)
        name = DB.shop_profile(con)["name"]
        t = QLabel(name); t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setStyleSheet("font-size:17px;font-weight:700;color:#16324f;")
        lay.addWidget(t)
        sub = QLabel("Enter your password to unlock"); sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("color:#5d6f82;"); lay.addWidget(sub)
        self.pw = QLineEdit(); self.pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw.setPlaceholderText("Password"); self.pw.returnPressed.connect(self._try)
        lay.addWidget(self.pw)
        b = QPushButton("Unlock"); b.setObjectName("primary"); b.clicked.connect(self._try)
        lay.addWidget(b)
    def _try(self):
        if DB.verify_password(self.con, self.pw.text()):
            self.ok = True; self.accept(); return
        self.tries += 1; self.pw.clear()
        if self.tries >= 3:
            self.reject(); return
        QMessageBox.warning(self, "Wrong password", "Incorrect password - try again.")

def bootstrap_brand(con):
    """Private delivered packages can carry a bundled brand next to the app:
    bundle-logo.png and bundle-config.json ({"shop_name": ...}). Applied once, on
    first run only, into the local settings; the public build ships neither file."""
    import json, shutil
    if DB.get_setting(con, "brand_bootstrapped"):
        return
    spots = [os.path.dirname(os.path.abspath(__file__)), os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else ""]
    for base in spots:
        if not base: continue
        logo = os.path.join(base, "bundle-logo.png")
        cfg = os.path.join(base, "bundle-config.json")
        if os.path.exists(logo) and not DB.shop_logo(con):
            dest = os.path.join(DB.APP_DIR, "shop-logo.png")
            shutil.copy(logo, dest)
            DB.set_setting(con, "shop_logo", dest)
        if os.path.exists(cfg):
            try:
                data = json.load(open(cfg, encoding="utf-8"))
                if data.get("shop_name") and DB.get_setting(con, "shop_name") in (None, "", "Your Shop Name"):
                    DB.set_setting(con, "shop_name", data["shop_name"])
            except Exception:
                pass
    DB.set_setting(con, "brand_bootstrapped", "1")

class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Shop Billing Software")
        self.resize(1120, 720)
        self.demo = "--demo" in sys.argv
        self.con = DB.connect(demo=self.demo)
        bootstrap_brand(self.con)
        if self.demo: DB.seed_demo(self.con)
        DB.apply_turnaround_policy(self.con)
        if DB.has_password(self.con):
            dlg = LockDialog(self.con)
            dlg.exec()
            if not dlg.ok:
                sys.exit(0)
        central = QWidget(); outer = QVBoxLayout(central); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        bar = QLabel("DESIGN PREVIEW - demo data only, not a real shop  |  final build after your design feedback" if self.demo
                     else "Data is saved in the shop.db file on this PC. Use Backup regularly - keep a copy on another drive too.")
        bar.setObjectName("demobar"); bar.setAlignment(Qt.AlignCenter); outer.addWidget(bar)
        body = QHBoxLayout(); body.setContentsMargins(0, 0, 0, 0); body.setSpacing(0)
        side = QFrame(); side.setObjectName("sidebar"); side.setFixedWidth(215)
        sl = QVBoxLayout(side); sl.setContentsMargins(0, 0, 0, 0); sl.setSpacing(0)
        self.brand_logo = QLabel(); self.brand_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.brand_logo.setObjectName("brandlogo"); self.brand_logo.hide()
        sl.addWidget(self.brand_logo)
        self.brand = QLabel(objectName="brand"); self.brand.setWordWrap(True)
        sl.addWidget(self.brand)
        sl.addWidget(QLabel("Sale \u2022 Rental \u2022 Wedding Orders", objectName="brandsub"))
        self.navg = QButtonGroup(self); self.nav = []
        self.labels = ["Home", "Records", "New Bill", "Returns", "Stock", "Customers", "Reports", "Invoice Preview", "Settings"]
        for i, label in enumerate(self.labels):
            b = QPushButton(label); b.setObjectName("nav"); b.setCheckable(True)
            b.clicked.connect(lambda _=False, i=i, l=label: self._nav(i, l))
            self.navg.addButton(b); sl.addWidget(b); self.nav.append(b)
        sl.addStretch()
        body.addWidget(side)
        self.stack = QStackedWidget()
        self.p_dash = Dashboard(self); self.p_dash.build()
        self.p_rec = Records(self); self.p_bill = NewBill(self)
        self.p_ret = ReturnsPage(self); self.p_stock = StockPage(self)
        self.p_cust = CustomersPage(self); self.p_rep = ReportsPage(self)
        self.p_inv = Invoice(self); self.p_set = SettingsPage(self)
        self.page_list = [self.p_dash, self.p_rec, self.p_bill, self.p_ret, self.p_stock, self.p_cust, self.p_rep, self.p_inv, self.p_set]
        for p in self.page_list: self.stack.addWidget(p)
        body.addWidget(self.stack, 1); outer.addLayout(body)
        self.setCentralWidget(central)
        self.go(0)
    def _nav(self, i, label):
        self.go(i)
    def go(self, i):
        self.stack.setCurrentIndex(i)
        for j, b in enumerate(self.nav[:9]): b.setChecked(j == i)
        if i == 7: self.p_inv.show_latest(self.con)
        else:
            p = self.page_list[i]
            if hasattr(p, "refresh"): p.refresh(self.con)
    def new_bill(self, t): self.p_bill.preset(t); self.go(2)
    def _apply_brand(self):
        name = DB.shop_profile(self.con)["name"]
        self.brand.setText(name)
        self.setWindowTitle(f"{name} - Billing Software")
        logo = DB.shop_logo(self.con)
        pm = QPixmap(logo) if logo else QPixmap()
        if not pm.isNull():
            self.brand_logo.setPixmap(pm.scaled(170, 76, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            self.brand_logo.show()
        else:
            self.brand_logo.clear(); self.brand_logo.hide()
    def refresh_all(self):
        self._apply_brand()
        for i, p in enumerate(self.page_list):
            if i == 7: continue
            if hasattr(p, "refresh"): p.refresh(self.con)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(base, "style.qss")) as f:
        app.setStyleSheet(f.read())
    w = Main()
    if "--shot" not in sys.argv and "--demo-shot" not in sys.argv:
        logo = DB.shop_logo(w.con)
        pm = QPixmap(logo) if logo else QPixmap()
        if not pm.isNull():
            sp = QSplashScreen(pm.scaled(380, 230, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            sp.show(); app.processEvents()
            import time; time.sleep(1.5)
            w.refresh_all(); w.show(); sp.finish(w)
            sys.exit(app.exec())
    if "--shot" in sys.argv or "--demo-shot" in sys.argv:
        w.resize(1120, 720); w.show()
        w.refresh_all()
        out = sys.argv[sys.argv.index("--shot") + 1]
        app.processEvents()
        for i, name in [(0, "dash"), (2, "newbill")]:
            w.go(i); app.processEvents(); w.grab().save(f"{out}/desktop-{name}.png")
        w.p_bill.preset("RENTAL"); w.go(2); app.processEvents()
        w.grab().save(f"{out}/desktop-newbill-rental.png")
        w.go(3); app.processEvents(); w.grab().save(f"{out}/desktop-returns.png")
        w.go(4); app.processEvents(); w.grab().save(f"{out}/desktop-stock.png")
        w.go(7); app.processEvents(); w.grab().save(f"{out}/desktop-invoice.png")
        w.p_inv.render_pdf(f"{out}/desktop-invoice.pdf")
        w.go(8); app.processEvents(); w.grab().save(f"{out}/desktop-settings.png")
        print("shots saved to", out)
        sys.exit(0)
    w.refresh_all(); w.show()
    sys.exit(app.exec())
