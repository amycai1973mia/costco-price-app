import os, json, sqlite3, uuid
from pathlib import Path
from datetime import datetime
from flask import Flask, request, redirect, url_for, render_template, send_from_directory, abort
from ocr_parser import recognize

BASE=Path(__file__).parent
UPLOADS=BASE/"uploads"; PENDING=BASE/"data"/"pending"; DB=BASE/"data"/"costco.db"
UPLOADS.mkdir(exist_ok=True); PENDING.mkdir(parents=True, exist_ok=True)
app=Flask(__name__)

def db():
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS receipts(id INTEGER PRIMARY KEY AUTOINCREMENT, store_code TEXT, purchase_date TEXT, total REAL, image_path TEXT, imported_at TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS receipt_items(id INTEGER PRIMARY KEY AUTOINCREMENT, receipt_id INTEGER REFERENCES receipts(id), item_code TEXT, item_name TEXT, price REAL, quantity INTEGER)""")
    return con

@app.route("/")
def index(): return render_template("index.html")

@app.route("/upload", methods=["POST"])
def upload():
    f=request.files.get("receipt")
    if not f or not f.filename: return redirect(url_for("index"))
    rid=uuid.uuid4().hex[:12]
    ext=Path(f.filename).suffix.lower() or ".jpg"
    if ext not in (".jpg",".jpeg",".png",".webp"): ext=".jpg"
    dest=UPLOADS/f"{rid}{ext}"; f.save(dest)
    try:
        parsed=recognize(str(dest), str(PENDING/rid))
    except Exception as e:
        parsed={"store_code":"","store_confidence":0.3,"purchase_date":"","date_confidence":0.3,"total":None,"total_confidence":0.3,"items":[],"raw_lines":[],"error":str(e)}
    parsed["receipt_key"]=rid; parsed["image_name"]=dest.name
    (PENDING/f"{rid}.json").write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
    return redirect(url_for("confirm", rid=rid))

@app.route("/confirm/<rid>")
def confirm(rid):
    p=PENDING/f"{rid}.json"
    if not p.exists(): abort(404)
    data=json.loads(p.read_text(encoding="utf-8"))
    return render_template("confirm.html", d=data)

@app.route("/confirm/<rid>", methods=["POST"])
def save(rid):
    p=PENDING/f"{rid}.json"
    if not p.exists(): abort(404)
    data=json.loads(p.read_text(encoding="utf-8"))
    store=request.form.get("store_code","").strip(); date=request.form.get("purchase_date","").strip()
    total=request.form.get("total","").strip()
    codes=request.form.getlist("item_code"); names=request.form.getlist("item_name")
    prices=request.form.getlist("item_price"); qtys=request.form.getlist("item_qty"); dels=request.form.getlist("delete_item")
    discs=request.form.getlist("item_discount"); disc_codes=request.form.getlist("item_discount_code")
    con=db()
    cur=con.execute("INSERT INTO receipts(store_code,purchase_date,total,image_path,imported_at) VALUES(?,?,?,?,?)",
        (store,date,float(total) if total else None, data.get("image_name",""), datetime.now().isoformat(timespec="seconds")))
    receipt_id=cur.lastrowid
    for i,code in enumerate(codes):
        if str(i) in dels: continue
        if not code.strip() and not (names[i].strip() if i<len(names) else ""): continue
        try: price=float(prices[i]) if prices[i].strip() else 0
        except: price=0
        try: qty=int(qtys[i]) if qtys[i].strip() else 1
        except: qty=1
        con.execute("INSERT INTO receipt_items(receipt_id,item_code,item_name,price,quantity) VALUES(?,?,?,?,?)",
            (receipt_id, code.strip(), names[i].strip(), price, qty))
        # 折扣挂在商品下保存为负数行, 不丢折扣信息
        if i < len(discs) and discs[i].strip():
            try: dv=float(discs[i])
            except: dv=None
            if dv is not None:
                con.execute("INSERT INTO receipt_items(receipt_id,item_code,item_name,price,quantity) VALUES(?,?,?,?,?)",
                    (receipt_id, disc_codes[i].strip() if i < len(disc_codes) else "", f"折扣 {names[i].strip()}", dv, 1))
    con.commit(); con.close()
    return redirect(url_for("records"))

@app.route("/records")
def records():
    con=db()
    receipts=con.execute("SELECT * FROM receipts ORDER BY id DESC").fetchall()
    out=[]
    for r in receipts:
        items=con.execute("SELECT * FROM receipt_items WHERE receipt_id=? ORDER BY id", (r["id"],)).fetchall()
        out.append((r,items))
    con.close()
    return render_template("records.html", receipts=out)

@app.route("/uploads/<name>")
def uploaded(name): return send_from_directory(UPLOADS, name)

if __name__=="__main__":
    db().close()
    app.run(host="0.0.0.0", port=5003, debug=False)
