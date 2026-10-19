#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Costco 小票 App — 本地先行版主程序（Flask + SQLite data/costco_app.db）
入口: .venv/bin/python app_main.py  -> http://127.0.0.1:5004
线上 GitHub Pages 网页版(docs/)与旧电脑版 app.py/costco.db 均不受本文件影响。
所有写操作只写本地 SQLite，不接付费 API。识别沿用现有 ocr_parser.recognize。
管理员: 首次启动时若设了环境变量 COSTCO_ADMIN_EMAIL + COSTCO_ADMIN_PASSWORD 且库中无管理员，
则创建该管理员；或运行 init_admin.py 交互创建。代码中不写明文密码。
"""
import csv, io, json, os, secrets, sqlite3, uuid
from datetime import datetime, date
from functools import wraps
from pathlib import Path
from flask import Flask, request, redirect, url_for, render_template, session, flash, abort, g
from werkzeug.security import generate_password_hash, check_password_hash

BASE = Path(__file__).resolve().parent
DB = BASE / "data" / "costco_app.db"
UPLOADS = BASE / "uploads_main"; UPLOADS.mkdir(exist_ok=True)
PENDING = BASE / "data" / "pending_main"; PENDING.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, template_folder="templates_main", static_folder="static")
_secret_file = BASE / "data" / ".secret_key"
if os.environ.get("COSTCO_SECRET_KEY"):
    app.secret_key = os.environ["COSTCO_SECRET_KEY"]
elif _secret_file.exists():
    app.secret_key = _secret_file.read_text().strip()
else:
    app.secret_key = secrets.token_hex(32)
    try: _secret_file.write_text(app.secret_key)
    except OSError: pass

def db():
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con

def init_db():
    # 复用建库脚本的 SCHEMA，保证结构与 create_database.py 一致
    import create_database
    con = db(); con.executescript(create_database.SCHEMA); con.commit()
    # 环境变量初始化管理员（仅当库中无 admin 时）
    email = os.environ.get("COSTCO_ADMIN_EMAIL"); pw = os.environ.get("COSTCO_ADMIN_PASSWORD")
    if email and pw and not con.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():
        con.execute("INSERT INTO users(email,password_hash,role,display_name) VALUES(?,?, 'admin',?)",
                    (email.strip().lower(), generate_password_hash(pw), "运营者"))
        con.commit()
    con.close()

def norm_date(s):
    s = (s or "").strip().replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try: return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError: pass
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) == 8:
        try: return datetime.strptime(digits, "%Y%m%d").strftime("%Y-%m-%d")
        except ValueError: pass
    return s

def fnum(v, default=0.0):
    try: return float(str(v).strip()) if str(v).strip() != "" else default
    except (ValueError, AttributeError): return default

def current_user():
    uid = session.get("user_id")
    if not uid: return None
    con = db(); u = con.execute("SELECT * FROM users WHERE id=? AND is_active=1", (uid,)).fetchone(); con.close()
    return u

def login_required(f):
    @wraps(f)
    def w(*a, **kw):
        if not current_user(): return redirect(url_for("login", next=request.path))
        return f(*a, **kw)
    return w

def admin_required(f):
    @wraps(f)
    def w(*a, **kw):
        u = current_user()
        if not u: return redirect(url_for("login"))
        if u["role"] != "admin": abort(403)
        return f(*a, **kw)
    return w

@app.context_processor
def inject_user(): return {"me": current_user()}

# ---------------- 账号 ----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower(); pw = request.form.get("password", "")
        name = request.form.get("display_name", "").strip()
        if not email or len(pw) < 6: flash("请填邮箱，密码至少 6 位。"); return render_template("auth.html", mode="register")
        con = db()
        try:
            cur = con.execute("INSERT INTO users(email,password_hash,display_name) VALUES(?,?,?)",
                              (email, generate_password_hash(pw), name or email))
            con.commit(); session["user_id"] = cur.lastrowid; con.close()
            flash("注册成功，欢迎使用！"); return redirect(url_for("home"))
        except sqlite3.IntegrityError:
            con.close(); flash("这个邮箱已经注册过了，请直接登录。")
    return render_template("auth.html", mode="register")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower(); pw = request.form.get("password", "")
        con = db(); u = con.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone(); con.close()
        if u and u["is_active"] and check_password_hash(u["password_hash"], pw):
            session["user_id"] = u["id"]
            con = db(); con.execute("UPDATE users SET last_login_at=datetime('now') WHERE id=?", (u["id"],)); con.commit(); con.close()
            return redirect(request.args.get("next") or url_for("home"))
        flash("邮箱或密码不对，或账号已停用。")
    return render_template("auth.html", mode="login")

@app.route("/logout")
def logout():
    session.clear(); flash("已退出登录。"); return redirect(url_for("login"))

# ---------------- 首页 ----------------
@app.route("/")
@login_required
def home():
    u = current_user(); con = db()
    stats = {
        "receipts": con.execute("SELECT COUNT(*) c FROM receipts WHERE user_id=?", (u["id"],)).fetchone()["c"],
        "wishlist": con.execute("SELECT COUNT(*) c FROM wishlist WHERE user_id=? AND is_active=1", (u["id"],)).fetchone()["c"],
        "alerts": con.execute("SELECT COUNT(*) c FROM alerts WHERE user_id=? AND is_read=0", (u["id"],)).fetchone()["c"],
    }; con.close()
    return render_template("home.html", stats=stats)

# ---------------- 小票：识别确认入库 / 手工录入 ----------------
@app.route("/receipts/upload", methods=["POST"])
@login_required
def receipt_upload():
    f = request.files.get("receipt")
    if not f or not f.filename: flash("请先选一张小票照片。"); return redirect(url_for("home"))
    rid = uuid.uuid4().hex[:12]
    ext = Path(f.filename).suffix.lower(); ext = ext if ext in (".jpg", ".jpeg", ".png", ".webp") else ".jpg"
    dest = UPLOADS / f"{rid}{ext}"; f.save(dest)
    parsed = {"store_code": "", "purchase_date": "", "total": None, "subtotal": None, "tax": None, "items": [], "raw_lines": []}
    try:
        from ocr_parser import recognize
        parsed = recognize(str(dest), str(PENDING / rid))
    except Exception as e:
        parsed["error"] = str(e)
    parsed["receipt_key"] = rid; parsed["image_name"] = dest.name; parsed["owner"] = session["user_id"]
    (PENDING / f"{rid}.json").write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
    return redirect(url_for("receipt_confirm", rid=rid))

@app.route("/receipts/manual")
@login_required
def receipt_manual():
    rid = "manual" + uuid.uuid4().hex[:8]
    data = {"receipt_key": rid, "image_name": "", "store_code": "", "purchase_date": date.today().isoformat(),
            "subtotal": "", "fees_total": "", "tax": "", "total": "", "items": [], "owner": session["user_id"], "manual": True}
    (PENDING / f"{rid}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return redirect(url_for("receipt_confirm", rid=rid))

def load_pending(rid):
    p = PENDING / f"{rid}.json"
    if not p.exists(): abort(404)
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("owner") != session.get("user_id"): abort(403)
    return data

@app.route("/receipts/confirm/<rid>")
@login_required
def receipt_confirm(rid):
    return render_template("receipt_confirm.html", d=load_pending(rid), rid=rid)

@app.route("/receipts/confirm/<rid>", methods=["POST"])
@login_required
def receipt_save(rid):
    data = load_pending(rid)
    codes = request.form.getlist("item_code"); names = request.form.getlist("item_name")
    prices = request.form.getlist("item_price"); qtys = request.form.getlist("item_qty")
    discs = request.form.getlist("item_discount"); fees_e = request.form.getlist("item_enviro_fee")
    fees_d = request.form.getlist("item_deposit"); manuals = request.form.getlist("item_is_manual")
    dels = set(request.form.getlist("delete_item"))
    items = []; fees_total = 0.0
    for i, code in enumerate(codes):
        if str(i) in dels: continue
        name = names[i].strip() if i < len(names) else ""
        if not code.strip() and not name: continue
        ef = fnum(fees_e[i]) if i < len(fees_e) else 0.0; dp = fnum(fees_d[i]) if i < len(fees_d) else 0.0
        fees_total += ef + dp
        items.append(dict(item_code=code.strip(), item_name=name, price=fnum(prices[i]) if i < len(prices) else 0.0,
                          discount=fnum(discs[i]) if i < len(discs) else 0.0, enviro_fee=ef, deposit=dp,
                          quantity=int(fnum(qtys[i], 1)) if i < len(qtys) else 1,
                          is_manual=1 if (i < len(manuals) and manuals[i] == "1") else 0, line_order=len(items)))
    subtotal_in = request.form.get("subtotal", "").strip()
    subtotal = fnum(subtotal_in) if subtotal_in else round(sum(it["price"] + it["discount"] for it in items), 2)
    fees_in = request.form.get("fees_total", "").strip()
    fees_total = fnum(fees_in) if fees_in else round(fees_total, 2)
    tax = fnum(request.form.get("tax")); total_in = request.form.get("total", "").strip()
    total = fnum(total_in) if total_in else round(subtotal + fees_total + tax, 2)
    con = db()
    cur = con.execute("""INSERT INTO receipts(user_id,store_code,purchase_date,subtotal,fees_total,tax,total,item_count,image_path,source)
                         VALUES(?,?,?,?,?,?,?,?,?,?)""",
                      (session["user_id"], request.form.get("store_code", "").strip(), norm_date(request.form.get("purchase_date", "")),
                       subtotal, fees_total, tax, total, len(items), data.get("image_name", ""), "manual" if data.get("manual") else "receipt_scan"))
    receipt_id = cur.lastrowid
    for it in items:
        con.execute("""INSERT INTO receipt_items(receipt_id,item_code,item_name,price,discount,enviro_fee,deposit,quantity,is_manual,line_order)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (receipt_id, it["item_code"], it["item_name"], it["price"], it["discount"], it["enviro_fee"], it["deposit"], it["quantity"], it["is_manual"], it["line_order"]))
    con.commit(); con.close()
    (PENDING / f"{rid}.json").unlink(missing_ok=True)
    flash(f"已入库 ✓ 共 {len(items)} 件，总计 ${total:.2f}")
    return redirect(url_for("receipts_list"))

@app.route("/receipts")
@login_required
def receipts_list():
    con = db()
    rows = con.execute("SELECT * FROM receipts WHERE user_id=? ORDER BY purchase_date DESC, id DESC", (session["user_id"],)).fetchall()
    out = [(r, con.execute("SELECT * FROM receipt_items WHERE receipt_id=? ORDER BY line_order,id", (r["id"],)).fetchall()) for r in rows]
    con.close(); return render_template("receipts.html", receipts=out)

@app.route("/uploads_main/<name>")
@login_required
def uploaded_main(name): 
    from flask import send_from_directory; return send_from_directory(UPLOADS, name)

# ---------------- 历史购买查询 ----------------
@app.route("/history")
@login_required
def history():
    uid = session["user_id"]
    df, dt, kw, code = (request.args.get("date_from", ""), request.args.get("date_to", ""),
                        request.args.get("keyword", "").strip(), request.args.get("code", "").strip())
    where = ["r.user_id=?"]; args = [uid]
    if df: where.append("r.purchase_date>=?"); args.append(norm_date(df))
    if dt: where.append("r.purchase_date<=?"); args.append(norm_date(dt))
    if kw: where.append("i.item_name LIKE ?"); args.append(f"%{kw}%")
    if code: where.append("i.item_code=?"); args.append(code)
    con = db()
    rows = con.execute(f"""SELECT r.purchase_date,r.store_code,i.* FROM receipt_items i JOIN receipts r ON r.id=i.receipt_id
                           WHERE {' AND '.join(where)} ORDER BY r.purchase_date DESC, i.line_order""", args).fetchall()
    # 汇总: 每个商品买过几次/上次价格/上次日期（在当前筛选结果基础上）
    agg = {}
    for r in rows:
        k = (r["item_code"], r["item_name"]); a = agg.setdefault(k, {"count": 0, "last_date": "", "last_price": None})
        a["count"] += 1
        if r["purchase_date"] and r["purchase_date"] >= a["last_date"]: a["last_date"] = r["purchase_date"]; a["last_price"] = r["price"]
    summary = [{"item_code": k[0], "item_name": k[1], **v} for k, v in agg.items()]
    con.close()
    return render_template("history.html", rows=rows, summary=summary, q=dict(date_from=df, date_to=dt, keyword=kw, code=code), searched=bool(request.args))

# ---------------- 待购清单 ----------------
# 待购只记三项主体：商品代码 / 商品名称 / 目前价格（参考价格）。价格不设门槛：
# wishlist 表无价格列，价格以「参考价 $X」拼入 note 保存，查询时解析出来单独成列/筛选/排序。
# 税、环保费/押金、小计、总额是小票那边的，待购识别与确认页一律不收这些。
import re as _re
def _wishlist_price(note):
    m=_re.search(r"参考价\s*\$\s*([0-9]+(?:\.[0-9]{1,2})?)", note or "")
    return float(m.group(1)) if m else None
def _wishlist_clean_note(note):
    s=_re.sub(r"参考价\s*\$\s*[0-9]+(?:\.[0-9]{1,2})?", "", note or "")
    s=_re.sub(r"数量\s*[0-9]+", "", s)
    return " · ".join(x.strip() for x in s.split("·") if x.strip())
def _wishlist_enrich(rows):
    out=[]
    for r in rows:
        d=dict(r); pv=_wishlist_price(d.get("note"))
        d["price_value"]=pv; d["price_display"]=(f"${pv:.2f}" if pv is not None else "—")
        d["clean_note"]=_wishlist_clean_note(d.get("note")); d["entry_date"]=(d.get("created_at") or "")[:10]
        d["source_label"]={"manual":"手工","history":"从已购记录","photo":"拍照"}.get(d.get("source"), d.get("source") or "")
        out.append(d)
    return out

@app.route("/wishlist")
@login_required
def wishlist():
    return render_template("wishlist.html")

def _wishlist_note_with_price_note(form):
    # 价格只是目前价格/参考价格（拼进备注显示与解析），不是期望价格门槛。
    note = (form.get("note", "") or "").strip()
    price = (form.get("item_price", "") or "").strip()
    parts = []
    if price: parts.append(f"参考价 ${price}")
    if note: parts.append(note)
    return " · ".join(parts)

@app.route("/wishlist/add", methods=["POST"])
@login_required
def wishlist_add():
    code = request.form.get("item_code", "").strip(); name = request.form.get("item_name", "").strip()
    source = request.form.get("source", "manual"); note = _wishlist_note_with_price_note(request.form)
    src_item = request.form.get("source_receipt_item_id") or None
    if source not in ("manual", "history", "photo"): source = "manual"
    if not code and not name: flash("请至少填商品名称或代码。"); return redirect(url_for("wishlist_manual" if source=="manual" else "wishlist"))
    con = db()
    try:
        con.execute("INSERT INTO wishlist(user_id,item_code,item_name,note,source,source_receipt_item_id) VALUES(?,?,?,?,?,?)",
                    (session["user_id"], code, name, note, source, src_item)); con.commit(); added=1
    except sqlite3.IntegrityError: added=0; flash("这个商品已经在你的待购清单里了。")
    con.close()
    if source == "history": flash("已加入待购清单 ✓"); return redirect(url_for("history"))
    if added: return redirect(url_for("wishlist_done", added=1))
    return redirect(url_for("wishlist_query"))

@app.route("/wishlist/manual")
@login_required
def wishlist_manual():
    return render_template("wishlist_manual.html")

@app.route("/wishlist/done")
@login_required
def wishlist_done():
    try: added=int(request.args.get("added", "1"))
    except ValueError: added=1
    skipped=request.args.get("skipped", "")
    return render_template("wishlist_done.html", added=added, skipped=skipped)

@app.route("/wishlist/query")
@login_required
def wishlist_query():
    # 查询条件：名称 / 代码 / 录入日期范围 / 价格范围；默认按录入日期新到旧，价格可排序
    qa={
        "q": request.args.get("q", "").strip(),
        "name": request.args.get("name", "").strip(),
        "code": request.args.get("code", "").strip(),
        "date_from": request.args.get("date_from", "").strip(),
        "date_to": request.args.get("date_to", "").strip(),
        "price_min": request.args.get("price_min", "").strip(),
        "price_max": request.args.get("price_max", "").strip(),
        "sort": request.args.get("sort", "date_desc").strip(),
    }
    con = db()
    rows = con.execute("SELECT * FROM wishlist WHERE user_id=? AND is_active=1 ORDER BY id DESC", (session["user_id"],)).fetchall()
    con.close()
    rows=_wishlist_enrich(rows)
    def _f(s):
        try: return float(s)
        except (TypeError, ValueError): return None
    pmin, pmax=_f(qa["price_min"]), _f(qa["price_max"])
    def keep(d):
        if qa["q"] and qa["q"].lower() not in (d.get("item_name") or "").lower() and qa["q"].lower() not in (d.get("item_code") or "").lower(): return False
        if qa["name"] and qa["name"].lower() not in (d.get("item_name") or "").lower(): return False
        if qa["code"] and qa["code"].lower() not in (d.get("item_code") or "").lower(): return False
        if qa["date_from"] and d["entry_date"] < qa["date_from"]: return False
        if qa["date_to"] and d["entry_date"] > qa["date_to"]: return False
        if pmin is not None and (d["price_value"] is None or d["price_value"] < pmin): return False
        if pmax is not None and (d["price_value"] is None or d["price_value"] > pmax): return False
        return True
    rows=[d for d in rows if keep(d)]
    if qa["sort"]=="price_asc": rows.sort(key=lambda d:(d["price_value"] is None, d["price_value"] or 0))
    elif qa["sort"]=="price_desc": rows.sort(key=lambda d:(d["price_value"] is None, -(d["price_value"] or 0)))
    # date_desc 已由 SQL id DESC（录入越新 id 越大）保证
    filtered=any(qa[k] for k in ("q","name","code","date_from","date_to","price_min","price_max"))
    return render_template("wishlist_query.html", rows=rows, q=qa["q"], qa=qa, filtered=filtered)

@app.route("/wishlist/photo/confirm-add", methods=["POST"])
@login_required
def wishlist_photo_confirm_add():
    codes = request.form.getlist("item_code"); names = request.form.getlist("item_name")
    prices = request.form.getlist("item_price"); notes = request.form.getlist("item_note")
    selected = set(request.form.getlist("selected"))
    con = db(); added = 0; skipped = 0
    for i in range(max(len(codes), len(names))):
        if selected and str(i) not in selected: continue
        code = codes[i].strip() if i < len(codes) else ""; name = names[i].strip() if i < len(names) else ""
        if not code and not name: continue
        note = _wishlist_note_with_price_note({"item_price": prices[i] if i < len(prices) else "", "note": notes[i] if i < len(notes) else ""})
        try:
            con.execute("INSERT INTO wishlist(user_id,item_code,item_name,note,source) VALUES(?,?,?,?, 'photo')",
                        (session["user_id"], code, name, note)); added += 1
        except sqlite3.IntegrityError: skipped += 1
    con.commit(); con.close()
    # 完成提示 + 返回主菜单在完成页；本次识别结果不保留（确认页是一次性渲染，离开即清空）
    return redirect(url_for("wishlist_done", added=added, skipped=skipped))

@app.route("/wishlist/<int:wid>/delete", methods=["POST"])
@login_required
def wishlist_delete(wid):
    con = db(); con.execute("UPDATE wishlist SET is_active=0 WHERE id=? AND user_id=?", (wid, session["user_id"])); con.commit(); con.close()
    flash("已从待购清单移除。")
    # 删后回到查询页，并尽量保留原来的查询条件
    keep={k:v for k,v in request.form.items() if k in ("q","name","code","date_from","date_to","price_min","price_max","sort") and v}
    return redirect(url_for("wishlist_query", **keep))

def _sign_items_from_raw(raw_lines):
    """商品牌兜底：小票解析没出商品时，从原始行里抓 代码/名称/价格 三项各一份，组成一件。
    只抓三项，税/环保费/押金/总额等词所在行不作名称。"""
    texts=[(l.get("text") if isinstance(l, dict) else str(l) or "").strip() for l in (raw_lines or [])]
    texts=[t for t in texts if t]
    if not texts: return []
    code=""; price=None; name_parts=[]
    for t in texts:
        if not code:
            m=_re.search(r"\b(\d{5,7})\b", t)
            if m: code=m.group(1)
        if price is None:
            m=_re.search(r"\$?\s*(\d{1,4}\.\d{2})\b", t)
            if m and not _re.search(r"SUBTOTAL|TOTAL|TAX", t, _re.I): price=float(m.group(1))
        if _re.search(r"SUBTOTAL|TOTAL|TAX|ENVIRO|DEPOSIT|ITEMS\s*SOLD", t, _re.I): continue
        words=_re.sub(r"\b\d{5,7}\b", " ", t); words=_re.sub(r"\$?\s*\d{1,4}\.\d{2}\b", " ", words)
        words=" ".join(w for w in words.replace("$"," ").split() if w.upper() not in ("ITEM","COSTCO"))
        if len(_re.sub(r"[^A-Za-z]", "", words))>=3: name_parts.append(words)
    name=max(name_parts, key=lambda s: len(_re.sub(r"[^A-Za-z]", "", s))) if name_parts else ""
    if code or name or price is not None:
        return [{"item_code":code, "item_name":name, "price":("" if price is None else price)}]
    return []

@app.route("/wishlist/photo", methods=["POST"])
@login_required
def wishlist_photo():
    files=[f for f in request.files.getlist("photos") if f and f.filename]
    if not files:
        f=request.files.get("receipt")
        if f and f.filename: files=[f]
    if not files: flash("请先选照片。"); return redirect(url_for("wishlist"))
    items=[]; failed=0
    try:
        from ocr_parser import recognize
        for f in files:
            rid = uuid.uuid4().hex[:12]; dest = UPLOADS / f"wish{rid}.jpg"; f.save(dest)
            try:
                result=recognize(str(dest), str(PENDING / rid))
                got=[{"item_code":it.get("item_code",""), "item_name":it.get("item_name",""), "price":it.get("price","")}
                     for it in result.get("items", []) if not it.get("is_discount") and not it.get("is_fee")]
                if not got:
                    # 商品牌不是小票：小票预处理会裁掉牌子边缘/大字价格，故兜底改为对原图直认再抓三项
                    try:
                        from ocr_parser import ocr_lines as _ol
                        got=_sign_items_from_raw(_ol(str(dest)))
                    except Exception: got=[]
                    if not got: got=_sign_items_from_raw(result.get("raw_lines"))
                elif len(got)==1 and (not got[0]["item_name"] or got[0]["item_name"].strip().upper() in ("ITEM","COSTCO")):
                    fb=[]
                    try:
                        from ocr_parser import ocr_lines as _ol
                        fb=_sign_items_from_raw(_ol(str(dest)))
                    except Exception: fb=[]
                    if not fb: fb=_sign_items_from_raw(result.get("raw_lines"))
                    if fb and fb[0]["item_name"]: got[0]["item_name"]=fb[0]["item_name"]
                items.extend(got)
            except Exception: failed+=1
    except Exception as e: flash(f"识别失败：{e}，可以改用手工填写。"); return redirect(url_for("wishlist"))
    if failed: flash(f"有 {failed} 张照片没识别成功，其余已列在下面核对。")
    return render_template("wishlist_photo.html", items=items, photo_count=len(files))

# ---------------- 提醒对比（纯本地 SQL/逻辑，不调用 AI） ----------------
def generate_alerts(only_user=None):
    con = db(); created = 0; today_s = date.today().isoformat()
    users = [only_user] if only_user else [r["id"] for r in con.execute("SELECT id FROM users WHERE is_active=1").fetchall()]
    for uid in users:
        # 待购命中
        for w in con.execute("SELECT * FROM wishlist WHERE user_id=? AND is_active=1 AND item_code IS NOT NULL AND item_code<>''", (uid,)).fetchall():
            for d in con.execute("SELECT * FROM deals WHERE item_code=? AND (end_date IS NULL OR end_date='' OR end_date>=?) ORDER BY id DESC", (w["item_code"], today_s)).fetchall():
                if con.execute("SELECT 1 FROM alerts WHERE user_id=? AND deal_id=? AND alert_type='wishlist_deal' AND wishlist_id=?", (uid, d["id"], w["id"])).fetchone(): continue
                con.execute("""INSERT INTO alerts(user_id,alert_type,item_code,item_name,wishlist_id,deal_id,message) VALUES(?, 'wishlist_deal',?,?,?,?,?)""",
                            (uid, w["item_code"], w["item_name"] or d["item_name"], w["id"], d["id"],
                             f"你想买的「{w['item_name'] or d['item_name']}」（{w['item_code']}）正在打折：原价 ${d['original_price']} → ${d['sale_price']}，快去买！"))
                con.execute("UPDATE wishlist SET is_alerted=1,last_alerted_at=datetime('now') WHERE id=?", (w["id"],)); created += 1
        # 已购: 每商品最近一次购买
        for row in con.execute("""SELECT i.item_code, MAX(i.item_name) item_name, MAX(r.purchase_date) last_date,
                                  (SELECT id FROM receipts WHERE user_id=? ORDER BY purchase_date DESC LIMIT 1) dummy,
                                  (SELECT rr.id FROM receipts rr JOIN receipt_items ii ON ii.receipt_id=rr.id WHERE rr.user_id=? AND ii.item_code=i.item_code ORDER BY rr.purchase_date DESC LIMIT 1) receipt_id
                                  FROM receipt_items i JOIN receipts r ON r.id=i.receipt_id WHERE r.user_id=? GROUP BY i.item_code""", (uid, uid, uid)).fetchall():
            if not row["item_code"] or not row["last_date"]: continue
            for d in con.execute("SELECT * FROM deals WHERE item_code=? ORDER BY id DESC", (row["item_code"],)).fetchall():
                deal_date_s = norm_date(d["start_date"] or d["collected_at"] or today_s)
                try: days = (datetime.strptime(deal_date_s, "%Y-%m-%d").date() - datetime.strptime(norm_date(row["last_date"]), "%Y-%m-%d").date()).days
                except ValueError: continue
                if days < 0: continue
                atype = "price_adjust_30d" if days <= 30 else "restock_over30d"
                if con.execute("SELECT 1 FROM alerts WHERE user_id=? AND deal_id=? AND alert_type=? AND receipt_id=?", (uid, d["id"], atype, row["receipt_id"])).fetchone(): continue
                msg = (f"你 {row['last_date']} 买的「{row['item_name']}」（{row['item_code']}）现在打折 ${d['sale_price']}，30天内可去 Costco 做价格调整退差价！" if atype == "price_adjust_30d"
                       else f"你以前买过的「{row['item_name']}」（{row['item_code']}）又打折了 ${d['sale_price']}，需要补货可以去看看。")
                con.execute("INSERT INTO alerts(user_id,alert_type,item_code,item_name,receipt_id,deal_id,message) VALUES(?,?,?,?,?,?,?)",
                            (uid, atype, row["item_code"], row["item_name"], row["receipt_id"], d["id"], msg)); created += 1
    con.commit(); con.close(); return created

@app.route("/alerts")
@login_required
def alerts_list():
    con = db(); rows = con.execute("SELECT * FROM alerts WHERE user_id=? ORDER BY id DESC", (session["user_id"],)).fetchall()
    con.execute("UPDATE alerts SET is_read=1 WHERE user_id=?", (session["user_id"],)); con.commit(); con.close()
    return render_template("alerts.html", rows=rows)

@app.route("/alerts/check", methods=["POST"])
@login_required
def alerts_check():
    n = generate_alerts(session["user_id"]); flash(f"已检查最新打折，新生成 {n} 条提醒。"); return redirect(url_for("alerts_list"))

# ---------------- 运营后台 ----------------
@app.route("/admin")
@admin_required
def admin_home():
    con = db()
    users = con.execute("SELECT * FROM users ORDER BY id").fetchall()
    stats = {"users": len(users), "active_sub": sum(1 for u in users if u["subscription_status"] in ("active", "trial")),
             "receipts": con.execute("SELECT COUNT(*) c FROM receipts").fetchone()["c"],
             "deals": con.execute("SELECT COUNT(*) c FROM deals").fetchone()["c"],
             "alerts": con.execute("SELECT COUNT(*) c FROM alerts").fetchone()["c"]}
    batches = con.execute("SELECT * FROM deal_import_batches ORDER BY id DESC LIMIT 10").fetchall()
    deals = con.execute("SELECT * FROM deals ORDER BY id DESC LIMIT 20").fetchall()
    con.close(); return render_template("admin.html", users=users, stats=stats, batches=batches, deals=deals)

@app.route("/admin/users/<int:uid>/subscription", methods=["POST"])
@admin_required
def admin_subscription(uid):
    status = request.form.get("subscription_status", "free"); plan = request.form.get("subscription_plan", "").strip(); exp = request.form.get("subscription_expires_at", "").strip()
    if status not in ("free", "trial", "active", "expired", "cancelled"): abort(400)
    con = db(); con.execute("UPDATE users SET subscription_status=?,subscription_plan=?,subscription_expires_at=?,updated_at=datetime('now') WHERE id=?",
                            (status, plan or None, norm_date(exp) if exp else None, uid)); con.commit(); con.close()
    flash("订阅状态已更新。"); return redirect(url_for("admin_home"))

@app.route("/admin/users/<int:uid>/reset-password", methods=["POST"])
@admin_required
def admin_reset_pw(uid):
    # 本地版: 管理员设临时密码（只存哈希）。正式版应走邮件重置链接（users.password_reset_token_hash 已预留）。
    temp = request.form.get("temp_password", "")
    if len(temp) < 6: flash("临时密码至少 6 位。"); return redirect(url_for("admin_home"))
    con = db(); con.execute("UPDATE users SET password_hash=?,updated_at=datetime('now') WHERE id=?", (generate_password_hash(temp), uid)); con.commit(); con.close()
    flash("已为该用户设置临时密码，请线下告诉用户，登录后尽快修改（本地版暂无自助改密页，见说明）。"); return redirect(url_for("admin_home"))

FIELD_ALIASES = {"item_code": ["item_code", "code", "商品代码", "代码"], "item_name": ["item_name", "name", "商品名称", "名称"],
                 "original_price": ["original_price", "原价"], "sale_price": ["sale_price", "折后价", "折后", "售价"],
                 "savings": ["savings", "省", "省了多少"], "province": ["province", "省份"], "store_code": ["store_code", "门店", "门店代码"],
                 "start_date": ["start_date", "开始日期", "开始"], "end_date": ["end_date", "结束日期", "结束"]}

def parse_deals_text(text):
    text = (text or "").strip()
    if not text: return []
    rows = []
    if text.startswith("[") or text.startswith("{"):
        data = json.loads(text); rows = data if isinstance(data, list) else data.get("deals", [])
    else:
        rows = list(csv.DictReader(io.StringIO(text)))
    out = []
    for r in rows:
        item = {}
        for key, aliases in FIELD_ALIASES.items():
            for a in aliases:
                if a in r and str(r[a]).strip() != "": item[key] = str(r[a]).strip(); break
        if not item.get("item_code") and not item.get("item_name"): continue
        item["original_price"] = fnum(item.get("original_price")) or None; item["sale_price"] = fnum(item.get("sale_price")) or None
        item["savings"] = fnum(item["savings"]) if item.get("savings") else (round(item["original_price"] - item["sale_price"], 2) if item["original_price"] and item["sale_price"] else None)
        item["start_date"] = norm_date(item["start_date"]) if item.get("start_date") else None
        item["end_date"] = norm_date(item["end_date"]) if item.get("end_date") else None
        out.append(item)
    return out

@app.route("/admin/deals/import", methods=["POST"])
@admin_required
def admin_deals_import():
    text = request.form.get("deals_text", "")
    f = request.files.get("deals_file")
    if f and f.filename: text = f.read().decode("utf-8-sig", errors="replace")
    try: items = parse_deals_text(text)
    except Exception as e: flash(f"导入失败，格式不对：{e}"); return redirect(url_for("admin_home"))
    if not items: flash("没有读到任何打折商品，请检查内容。"); return redirect(url_for("admin_home"))
    con = db()
    cur = con.execute("INSERT INTO deal_import_batches(collected_date,source,item_count,notes) VALUES(date('now'),'admin_import',?,?)",
                      (len(items), "本地后台导入（示例/人工）")); batch_id = cur.lastrowid
    for it in items:
        con.execute("""INSERT INTO deals(batch_id,item_code,item_name,original_price,sale_price,savings,province,store_code,start_date,end_date,collected_at,source)
                       VALUES(?,?,?,?,?,?,?,?,?,?,date('now'),'admin_import')""",
                    (batch_id, it.get("item_code"), it.get("item_name"), it["original_price"], it["sale_price"], it["savings"], it.get("province"), it.get("store_code"), it["start_date"], it["end_date"]))
    con.commit(); con.close()
    n = generate_alerts()  # 导入后自动为全体用户生成提醒
    flash(f"导入成功 {len(items)} 条打折商品，并自动检查生成了 {n} 条新提醒。")
    return redirect(url_for("admin_home"))

if __name__ == "__main__":
    init_db(); app.run(host="0.0.0.0", port=int(os.environ.get("COSTCO_MAIN_PORT", "5004")), debug=False)
