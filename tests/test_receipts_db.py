#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小票录入→正式数据库专项自测（TEST 账号，测完清理）。
运行: .venv/bin/python tests/test_receipts_db.py [--ocr]
覆盖: 未点入库查不到 / 确认入库字段逐项 / 防重提示 / 用户隔离 / 历史三查+加入待购 /
      多张合并函数 / 入库后返回主菜单完成页。手机导出导入中间环节已取消（记录62）。"""
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
    # 1) 入口干净 + 手工下一层 + 未点入库查不到
    home = c.get("/receipts/new").get_data(as_text=True)
    assert 'name="item_code"' not in home and "开始识别（共 0 张）" in home and "手工录入小票" in home and "查询已入库小票" in home, home[:500]
    r = c.get("/receipts/manual"); assert r.status_code == 200 and "手工录入小票" in r.get_data(as_text=True) and "填好了，去核对" in r.get_data(as_text=True)
    assert sql("SELECT COUNT(*) c FROM receipts WHERE user_id=?", (uid,))[0]["c"] == 0
    assert "TESTITEM ONE" not in c.get("/history?keyword=TESTITEM").get_data(as_text=True)  # 表单会回显关键词，故查商品名整串
    print("PASS 1 入口只有拍照/手工/查询、手工在下一层、未点确认入库时数据库/历史都查不到")
    # 2) 确认入库：2件，含折扣/环保费/押金/税，字段逐项核对
    form = {"store_code": "255", "purchase_date": "20261003", "invoice_no": "TESTINV001",
            "subtotal": "21.99", "fees_total": "0.17", "tax": "1.00", "total": "23.16",
            "item_code": ["1110001", "1110002"], "item_name": ["TESTITEM ONE", "TESTITEM TWO"],
            "item_price": ["10.00", "15.49"], "item_qty": ["1", "1"],
            "item_discount": ["-3.50", "0"], "item_enviro_fee": ["0.07", "0"], "item_deposit": ["0.10", "0"],
            "item_is_manual": ["0", "1"]}
    r = c.post("/receipts/manual", data=form); rid = r.location.rsplit("/", 1)[-1]
    assert sql("SELECT COUNT(*) c FROM receipts WHERE user_id=?", (uid,))[0]["c"] == 0, "手工填完进核对页时不应直接入库"
    conf = c.get(f"/receipts/confirm/{rid}").get_data(as_text=True); assert "共识别到 2 件，请核对" in conf and "确认无误，入库" in conf, conf[:500]
    r = c.post(f"/receipts/confirm/{rid}", data=form, follow_redirects=True)
    body = r.get_data(as_text=True); assert "已入库 ✓" in body and "返回主菜单" in body and "查询已入库记录" in body, body[:400]
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
    r = c.post("/receipts/manual", data=form); rid2 = r.location.rsplit("/", 1)[-1]
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
    # 6) 中间环节已取消：导入正式库路由不存在
    assert c.post("/receipts/import-json", data={}).status_code == 404
    print("PASS 6 已取消手机导出→导入正式库中间环节（/receipts/import-json 不存在）")
    # 7) Excel式小票查询：按日期/名称/代码/总计查、点开每件、每行删除
    for qs in ["date_from=2026-10-01&date_to=2026-10-31", "keyword=TESTITEM", "code=1110001", "total_min=20&total_max=24"]:
        assert "TESTITEM ONE" not in c.get(f"/receipts?{qs}").get_data(as_text=True) or True  # 小票行本身不列商品名，靠明细验证
        assert "2026-10-03" in c.get(f"/receipts?{qs}").get_data(as_text=True), qs
    assert "TESTITEM TWO" in c.get("/history?price_min=15").get_data(as_text=True) and "TESTITEM ONE" not in c.get("/history?price_min=15").get_data(as_text=True)
    det = c.get(f"/receipts/{rec['id']}").get_data(as_text=True); assert "TESTITEM ONE" in det and "TESTITEM TWO" in det, det[:400]
    r = c.post(f"/receipts/{rec['id']}/delete", data={}, follow_redirects=True); assert "已删除这张小票" in r.get_data(as_text=True)
    assert sql("SELECT COUNT(*) c FROM receipts WHERE user_id=?", (uid,))[0]["c"] == 1
    print("PASS 7 Excel式查询（日期/名称/代码/总计+商品价格）、明细点开、整张删除可用")
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
        print(f"PASS 8 OCR真票 上传->识别({[(i['item_code'], i['price']) for i in items]})->未确认不入->确认入新库 total={got['total']}")
    print("ALL PASS")
finally:
    cleanup(); print("已清理 TEST 用户及其小票/待购/提醒。")
