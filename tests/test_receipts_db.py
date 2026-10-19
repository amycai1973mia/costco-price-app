#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小票录入→正式数据库专项自测（TEST 账号，测完清理）。
运行: .venv/bin/python tests/test_receipts_db.py [--ocr]
覆盖: 未点入库查不到 / 确认入库字段逐项 / 防重提示 / 用户隔离 / 历史三查+加入待购 /
      多张合并函数 / 手机版JSON导入正式库+导入防重 / 入库后返回主菜单完成页。"""
import io, json, sqlite3, sys
from pathlib import Path
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
import app_main
app_main.init_db()
DB = BASE / "data" / "costco_app.db"
def sql(q, a=()):
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row; r = con.execute(q, a).fetchall(); con.close(); return r
created = []
def cleanup():
    con = sqlite3.connect(DB)
    for uid in created:
        con.execute("DELETE FROM alerts WHERE user_id=?", (uid,))
        con.execute("DELETE FROM wishlist WHERE user_id=?", (uid,))
        con.execute("DELETE FROM receipt_items WHERE receipt_id IN (SELECT id FROM receipts WHERE user_id=?)", (uid,))
        con.execute("DELETE FROM receipts WHERE user_id=?", (uid,))
        con.execute("DELETE FROM users WHERE id=?", (uid,))
    con.commit(); con.close()
def reg(c, email):
    r = c.post("/register", data={"email": email, "password": "test1234", "display_name": "TEST"}, follow_redirects=True)
    assert r.status_code == 200
    uid = sql("SELECT id FROM users WHERE email=?", (email,))[0]["id"]; created.append(uid); return uid

try:
    c = app_main.app.test_client(); uid = reg(c, "test_receipts@example.com")
    other = app_main.app.test_client(); reg(other, "test_receipts_b@example.com")
    # 1) 未点入库查不到：只打开手工确认页，不提交
    r = c.get("/receipts/manual"); rid = r.location.rsplit("/", 1)[-1]
    assert sql("SELECT COUNT(*) c FROM receipts WHERE user_id=?", (uid,))[0]["c"] == 0
    assert "TESTITEM ONE" not in c.get("/history?keyword=TESTITEM").get_data(as_text=True)  # 表单会回显关键词，故查商品名整串
    print("PASS 1 未点确认入库时数据库/历史都查不到")
    # 2) 确认入库：2件，含折扣/环保费/押金/税，字段逐项核对
    form = {"store_code": "255", "purchase_date": "20261003", "invoice_no": "TESTINV001",
            "subtotal": "21.99", "fees_total": "0.17", "tax": "1.00", "total": "23.16",
            "item_code": ["1110001", "1110002"], "item_name": ["TESTITEM ONE", "TESTITEM TWO"],
            "item_price": ["10.00", "15.49"], "item_qty": ["1", "1"],
            "item_discount": ["-3.50", "0"], "item_enviro_fee": ["0.07", "0"], "item_deposit": ["0.10", "0"],
            "item_is_manual": ["0", "1"]}
    r = c.post(f"/receipts/confirm/{rid}", data=form, follow_redirects=True)
    body = r.get_data(as_text=True); assert "已入库 ✓" in body and "返回主菜单" in body, body[:400]
    rec = sql("SELECT * FROM receipts WHERE user_id=?", (uid,))[0]
    assert (rec["store_code"], rec["purchase_date"], rec["invoice_no"]) == ("255", "2026-10-03", "TESTINV001"), dict(rec)
    assert abs(rec["subtotal"]-21.99)<1e-9 and abs(rec["fees_total"]-0.17)<1e-9 and abs(rec["tax"]-1.00)<1e-9 and abs(rec["total"]-23.16)<1e-9
    assert rec["item_count"] == 2 and rec["store_id"] is not None, dict(rec)
    its = sql("SELECT * FROM receipt_items WHERE receipt_id=? ORDER BY line_order", (rec["id"],))
    assert [i["item_code"] for i in its] == ["1110001", "1110002"]
    assert its[0]["discount"] == -3.5 and abs(its[0]["enviro_fee"]-0.07)<1e-9 and abs(its[0]["deposit"]-0.10)<1e-9
    assert its[1]["is_manual"] == 1 and its[1]["price"] == 15.49
    print("PASS 2 确认入库字段逐项对（门店/日期/发票号/小计/费用/税/总计/顺序/折扣/费用/手填/store_id）")
    # 3) 防重：同门店+日期+总计+件数再入一次，先提示不新增；确认是另一张后才入
    r = c.get("/receipts/manual"); rid2 = r.location.rsplit("/", 1)[-1]
    r = c.post(f"/receipts/confirm/{rid2}", data=form)
    assert "可能已经入过库了" in r.get_data(as_text=True)
    assert sql("SELECT COUNT(*) c FROM receipts WHERE user_id=?", (uid,))[0]["c"] == 1, "防重时不应新增"
    form2 = dict(form); form2["confirm_duplicate"] = "1"; form2["invoice_no"] = "TESTINV002"
    r = c.post(f"/receipts/confirm/{rid2}", data=form2, follow_redirects=True)
    assert "已入库 ✓" in r.get_data(as_text=True)
    assert sql("SELECT COUNT(*) c FROM receipts WHERE user_id=?", (uid,))[0]["c"] == 2
    print("PASS 3 重复入库先提示不新增，用户确认是另一张后才入")
    # 4) 历史三查 + 加入待购不回退 + 用户隔离
    for qs in ["date_from=2026-10-01&date_to=2026-10-31", "keyword=TESTITEM", "code=1110001"]:
        assert "TESTITEM ONE" in c.get(f"/history?{qs}").get_data(as_text=True), qs
    assert "TESTITEM ONE" not in other.get("/history?keyword=TESTITEM").get_data(as_text=True)
    c.post("/wishlist/add", data={"item_code": "1110001", "item_name": "TESTITEM ONE", "item_price": "10.00", "source": "history"})
    assert "TESTITEM ONE" in c.get("/wishlist/query?code=1110001").get_data(as_text=True)
    print("PASS 4 历史按日期/名称/代码查到、加入待购可用、其他用户查不到")
    # 5) 多张合并不重叠/接缝去重（函数级）
    p1 = {"store_code": "255", "purchase_date": "2026-10-03", "subtotal": 20.0, "total": None, "items": [{"item_code": "1", "item_name": "A", "price": 10.0}, {"item_code": "2", "item_name": "B", "price": 10.0}]}
    p2 = {"store_code": "", "purchase_date": "", "subtotal": None, "total": 30.0, "expected_item_count": 3, "items": [{"item_code": "2", "item_name": "B", "price": 10.0}, {"item_code": "3", "item_name": "C", "price": 10.0}]}
    m = app_main.merge_receipt_parts([p1, p2])
    assert [i["item_code"] for i in m["items"]] == ["1", "2", "3"] and m["total"] == 30.0 and m["store_code"] == "255", m
    print("PASS 5 多张合并：接缝重复去掉、总计取最后一张、件数=3")
    # 6) 手机版导出 JSON 导入正式库 + 导入防重
    payload = {"app": "costco-price-app", "kind": "receipts", "receipts": [
        {"store_code": "255", "purchase_date": "2026/10/05", "subtotal": 10.0, "tax": 0.5, "total": 10.67, "item_count": 1,
         "items": [{"item_code": "2220001", "item_name": "PHONE ITEM", "price": 10.0, "discount": "", "manual": False,
                    "attached_fees": [{"fee_name": "ENVIRO FEE", "amount": 0.07}, {"fee_name": "DEPOSIT", "amount": 0.10}]}], "fees": []}]}
    data = {"receipts_json": (io.BytesIO(json.dumps(payload).encode()), "costco-receipts-export.json")}
    r = c.post("/receipts/import-json", data=data, content_type="multipart/form-data", follow_redirects=True)
    assert "新入 1 张" in r.get_data(as_text=True), r.get_data(as_text=True)[:300]
    it = sql("SELECT i.* FROM receipt_items i JOIN receipts r ON r.id=i.receipt_id WHERE r.user_id=? AND i.item_code='2220001'", (uid,))[0]
    assert abs(it["enviro_fee"]-0.07)<1e-9 and abs(it["deposit"]-0.10)<1e-9
    data = {"receipts_json": (io.BytesIO(json.dumps(payload).encode()), "costco-receipts-export.json")}
    r = c.post("/receipts/import-json", data=data, content_type="multipart/form-data", follow_redirects=True)
    assert "新入 0 张" in r.get_data(as_text=True) and "跳过 1 张" in r.get_data(as_text=True)
    print("PASS 6 手机版导出JSON可导入正式库（费用挂回商品），重复导入跳过")
    count = sql("SELECT COUNT(*) c FROM receipts WHERE user_id=?", (uid,))[0]["c"]
    assert count == 3, count
    if "--ocr" in sys.argv:
        cc = app_main.app.test_client(); uidO = reg(cc, "test_receipts_ocr@example.com")
        img = Path("/workspace/costco/receipts/2026-10-08_0952_inv205300.jpg")
        with open(img, "rb") as fh:
            r = cc.post("/receipts/upload", data={"receipt": (fh, img.name)}, content_type="multipart/form-data")
        ridO = r.location.rsplit("/", 1)[-1]
        pend = json.loads((BASE / "data" / "pending_main" / f"{ridO}.json").read_text(encoding="utf-8"))
        items = [i for i in pend["items"] if not i.get("is_discount")]
        assert items, pend.keys()
        assert sql("SELECT COUNT(*) c FROM receipts WHERE user_id=?", (uidO,))[0]["c"] == 0, "未确认不应入库"
        dataO = {"store_code": pend.get("store_code", "255"), "purchase_date": pend.get("purchase_date", "2026-10-08"),
                 "subtotal": "", "fees_total": "", "tax": str(pend.get("tax") or 0), "total": str(pend.get("total") or ""),
                 "item_code": [i["item_code"] for i in items], "item_name": [i["item_name"] for i in items],
                 "item_price": [str(i["price"]) if i["price"] != "" else "0" for i in items], "item_qty": ["1"]*len(items),
                 "item_discount": [str(i.get("discount") or 0) for i in items],
                 "item_enviro_fee": [str(i.get("enviro_fee") or 0) for i in items],
                 "item_deposit": [str(i.get("deposit") or 0) for i in items],
                 "item_is_manual": ["0"]*len(items)}
        r = cc.post(f"/receipts/confirm/{ridO}", data=dataO, follow_redirects=True)
        assert "已入库 ✓" in r.get_data(as_text=True)
        got = sql("SELECT * FROM receipts WHERE user_id=?", (uidO,))[0]
        print(f"PASS 7 OCR真票 上传->识别({[(i['item_code'], i['price']) for i in items]})->未确认不入->确认入新库 total={got['total']}")
    print("ALL PASS")
finally:
    cleanup(); print("已清理 TEST 用户及其小票/待购/提醒。")
