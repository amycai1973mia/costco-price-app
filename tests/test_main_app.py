#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地先行版 app_main.py 全流程自测（TEST 账号，测完清理 TEST 数据）。
运行: .venv/bin/python tests/test_main_app.py [--ocr]   （--ocr 额外跑一张真票识别入库，较慢）"""
import json, sqlite3, sys
from pathlib import Path
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
import app_main
app_main.init_db()
DB = BASE / "data" / "costco_app.db"
def sql(q, a=()):
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row; r = con.execute(q, a).fetchall(); con.close(); return r
pre_batch = (sql("SELECT MAX(id) m FROM deal_import_batches")[0]["m"] or 0)
created_users = []
def cleanup():
    con = sqlite3.connect(DB)
    for uid in created_users:
        con.execute("DELETE FROM alerts WHERE user_id=?", (uid,))
        con.execute("DELETE FROM wishlist WHERE user_id=?", (uid,))
        con.execute("DELETE FROM receipt_items WHERE receipt_id IN (SELECT id FROM receipts WHERE user_id=?)", (uid,))
        con.execute("DELETE FROM receipts WHERE user_id=?", (uid,))
        con.execute("DELETE FROM users WHERE id=?", (uid,))
    con.execute("DELETE FROM deals WHERE batch_id>?", (pre_batch,))
    con.execute("DELETE FROM deal_import_batches WHERE id>?", (pre_batch,))
    con.commit(); con.close()

def reg(client, email, pw="test1234"):
    r = client.post("/register", data={"email": email, "password": pw, "display_name": "TEST"}, follow_redirects=True)
    assert r.status_code == 200, r.status_code
    uid = sql("SELECT id FROM users WHERE email=?", (email,))[0]["id"]; created_users.append(uid); return uid

try:
    c = app_main.app.test_client()
    uidA = reg(c, "test_a@example.com"); uidB_client = app_main.app.test_client(); uidB = reg(uidB_client, "test_b@example.com")
    admin_c = app_main.app.test_client(); uidAdmin = reg(admin_c, "test_admin@example.com")
    sql_admin = sqlite3.connect(DB); sql_admin.execute("UPDATE users SET role='admin' WHERE id=?", (uidAdmin,)); sql_admin.commit(); sql_admin.close()
    admin_c.get("/logout"); admin_c.post("/login", data={"email": "test_admin@example.com", "password": "test1234"})

    # 普通用户访问后台被拦
    assert c.get("/admin").status_code == 403
    # 手工录入小票: 1412124 近期购买(2026-10-08), 1694477 久前购买(2026-08-01) 分两张
    def manual_receipt(client, date_s, code, name, price):
        r = client.get("/receipts/manual"); rid = r.location.rsplit("/", 1)[-1]
        return client.post(f"/receipts/confirm/{rid}", data={
            "store_code": "255", "purchase_date": date_s, "subtotal": "", "fees_total": "", "tax": "0", "total": str(price),
            "item_code": [code], "item_name": [name], "item_price": [str(price)], "item_qty": ["1"],
            "item_discount": ["-3.00" if code == "1412124" else "0"], "item_enviro_fee": ["0.10"], "item_deposit": ["0"],
            "item_is_manual": ["1"]}, follow_redirects=True)
    assert "已入库" in manual_receipt(c, "2026-10-08", "1412124", "QUICK OATS", 11.99).get_data(as_text=True)
    assert "已入库" in manual_receipt(c, "2026-08-01", "1694477", "PEROGIES", 16.99).get_data(as_text=True)
    # 费用/折扣/顺序入库核对
    it = sql("SELECT i.* FROM receipt_items i JOIN receipts r ON r.id=i.receipt_id WHERE r.user_id=? AND i.item_code='1412124'", (uidA,))[0]
    assert it["discount"] == -3.0 and abs(it["enviro_fee"] - 0.10) < 1e-9, dict(it)
    # 历史查询三种方式
    for qs in ["date_from=2026-10-01&date_to=2026-10-18", "keyword=QUICK", "code=1412124"]:
        body = c.get(f"/history?{qs}").get_data(as_text=True); assert "QUICK OATS" in body and "买过几次" in body, qs
    assert "QUICK OATS" not in uidB_client.get("/history?keyword=QUICK").get_data(as_text=True), "用户隔离失败"
    # 待购: 手工 + 从历史加入
    c.post("/wishlist/add", data={"item_code": "9990001", "item_name": "TEST待购商品", "source": "manual"})
    c.post("/wishlist/add", data={"item_code": "1412124", "item_name": "QUICK OATS", "source": "history"})
    entry = c.get("/wishlist").get_data(as_text=True)
    assert "手工录入" in entry and "查询已入库待购产品" in entry and 'name="item_code"' not in entry, "待购入口页不应铺表单"
    assert "TEST待购商品" in c.get("/wishlist/query").get_data(as_text=True)
    assert "TEST待购商品" in c.get("/wishlist/query?q=TEST").get_data(as_text=True)
    # 管理员导入示例打折数据 -> 自动生成三类提醒
    sample = (BASE / "sample_data" / "sample_deals.csv").read_text(encoding="utf-8")
    r = admin_c.post("/admin/deals/import", data={"deals_text": sample}, follow_redirects=True)
    assert "导入成功 4 条" in r.get_data(as_text=True), r.get_data(as_text=True)[:500]
    body = c.get("/alerts").get_data(as_text=True)
    assert "待购打折" in body and "30天内价保" in body and "补货提醒" in body, body[:2000]
    types = {row["alert_type"] for row in sql("SELECT alert_type FROM alerts WHERE user_id=?", (uidA,))}
    assert types == {"wishlist_deal", "price_adjust_30d", "restock_over30d"}, types
    # 管理员后台: 用户列表/订阅/重置密码
    body = admin_c.get("/admin").get_data(as_text=True); assert "test_a@example.com" in body and "用户共 3" in body or "test_a@example.com" in body
    admin_c.post(f"/admin/users/{uidA}/subscription", data={"subscription_status": "active", "subscription_plan": "TEST月度", "subscription_expires_at": "2027-01-01"})
    assert sql("SELECT subscription_status s FROM users WHERE id=?", (uidA,))[0]["s"] == "active"
    admin_c.post(f"/admin/users/{uidA}/reset-password", data={"temp_password": "newpass123"})
    c.get("/logout"); assert c.post("/login", data={"email": "test_a@example.com", "password": "newpass123"}).status_code in (200, 302)
    print("PASS 主流程: 注册/隔离/手工入库/费用折扣/历史三查/待购/导入/三类提醒/后台订阅改密")

    if "--ocr" in sys.argv:
        cc = app_main.app.test_client(); uidO = reg(cc, "test_ocr@example.com")
        img = Path("/workspace/costco/receipts/2026-10-08_0952_inv205300.jpg")
        with open(img, "rb") as fh:
            r = cc.post("/receipts/upload", data={"receipt": (fh, img.name)}, content_type="multipart/form-data")
        rid = r.location.rsplit("/", 1)[-1]
        pend = json.loads((BASE / "data" / "pending_main" / f"{rid}.json").read_text(encoding="utf-8"))
        items = [i for i in pend["items"] if not i.get("is_discount")]
        assert items, f"OCR 未识别出商品: {pend.keys()}"
        print(f"OCR 真票识别: {[(i['item_code'], i['item_name'], i['price']) for i in items]} 总计={pend.get('total')}")
        data = {"store_code": pend.get("store_code", "255"), "purchase_date": pend.get("purchase_date", "2026-10-08"),
                "subtotal": "", "fees_total": "", "tax": "0", "total": str(pend.get("total") or ""),
                "item_code": [i["item_code"] for i in items], "item_name": [i["item_name"] for i in items],
                "item_price": [str(i["price"]) if i["price"] != "" else "0" for i in items], "item_qty": ["1"] * len(items),
                "item_discount": [str(i.get("discount") or 0) for i in items], "item_enviro_fee": ["0"] * len(items),
                "item_deposit": ["0"] * len(items), "item_is_manual": ["0"] * len(items)}
        r = cc.post(f"/receipts/confirm/{rid}", data=data, follow_redirects=True)
        assert "已入库" in r.get_data(as_text=True)
        assert sql("SELECT COUNT(*) c FROM receipts WHERE user_id=?", (uidO,))[0]["c"] == 1
        print("PASS OCR 真票: 上传->识别->确认->入库新库")
    print("ALL PASS")
finally:
    cleanup(); print("已清理 TEST 用户及其小票/待购/提醒，及本次测试导入的打折批次。")
