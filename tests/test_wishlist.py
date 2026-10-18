#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""待购清单按整体框架重做后的专项自测（TEST 账号，测完清理）。
运行: .venv/bin/python tests/test_wishlist.py [--ocr]"""
import sqlite3, sys
from pathlib import Path
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
import app_main
app_main.init_db()
DB = BASE / "data" / "costco_app.db"
def sql(q, a=()):
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row; r = con.execute(q, a).fetchall(); con.close(); return r
created=[]
def cleanup():
    con=sqlite3.connect(DB)
    for uid in created:
        con.execute("DELETE FROM wishlist WHERE user_id=?", (uid,)); con.execute("DELETE FROM users WHERE id=?", (uid,))
    con.commit(); con.close()
try:
    c = app_main.app.test_client()
    r = c.post("/register", data={"email":"test_wishlist@example.com","password":"test1234","display_name":"TEST"}, follow_redirects=True)
    uid = sql("SELECT id FROM users WHERE email=?", ("test_wishlist@example.com",))[0]["id"]; created.append(uid)
    # 1 入口页：只有两行大入口+查询入口，无铺开的输入框、无商品列表
    entry = c.get("/wishlist").get_data(as_text=True)
    assert "拍照" in entry and "从相册选照片" in entry and "手工录入" in entry and "查询已入库待购产品" in entry, entry[:800]
    assert 'name="item_code"' not in entry and 'name="item_name"' not in entry and 'name="q"' not in entry, "入口页铺了表单"
    assert entry.index("拍照") < entry.index("手工录入") < entry.index("查询已入库待购产品"), "顺序不对：应拍照第一、手工第二、查询在下面"
    print("PASS 1 待购入口第一屏顺序与干净程度（拍照/相册、手工入口、查询入口，无铺开表单）")
    # 2 手工下一层填写并加入
    manual = c.get("/wishlist/manual").get_data(as_text=True)
    assert 'name="item_code"' in manual and 'inputmode="numeric"' in manual and 'inputmode="decimal"' in manual
    assert sql("SELECT COUNT(*) c FROM wishlist WHERE user_id=?", (uid,))[0]["c"] == 0, "未点加入前库里不应有"
    c.post("/wishlist/add", data={"item_code":"777001","item_name":"TEST手工待购","item_price":"12.99","item_quantity":"2","note":"等打折","source":"manual"}, follow_redirects=True)
    rows = sql("SELECT * FROM wishlist WHERE user_id=? AND is_active=1", (uid,))
    assert len(rows)==1 and rows[0]["source"]=="manual" and "12.99" in rows[0]["note"], dict(rows[0])
    print("PASS 2 手工下一层填（代码/名称/价格/数量/备注）点加入才入库，source=manual，价格拼入备注非门槛字段")
    # 3 查询+显示字段
    q = c.get("/wishlist/query?q=777001").get_data(as_text=True)
    assert "TEST手工待购" in q and "手工" in q and rows[0]["created_at"] in q
    assert "TEST手工待购" not in c.get("/wishlist/query?q=不存在XYZ").get_data(as_text=True)
    print("PASS 3 按代码/名称查询，列表含代码/名称/加入时间/来源")
    # 4 删除
    wid = rows[0]["id"]
    c.post(f"/wishlist/{wid}/delete", follow_redirects=True)
    assert sql("SELECT COUNT(*) c FROM wishlist WHERE user_id=? AND is_active=1", (uid,))[0]["c"]==0
    assert "TEST手工待购" not in c.get("/wishlist/query").get_data(as_text=True)
    print("PASS 4 删除一条后查询不到（软删 is_active=0）")
    # 5 拍照确认才入库（直接测批量确认端点：未提交时库为空是构造前提；--ocr 时另走真实识别）
    assert sql("SELECT COUNT(*) c FROM wishlist WHERE user_id=? AND is_active=1", (uid,))[0]["c"]==0
    r = c.post("/wishlist/photo/confirm-add", data={"selected":["0","1"],"item_code":["888001","888002"],"item_name":["TEST拍照一","TEST拍照二"],"item_price":["9.99",""],"item_note":["",""]}, follow_redirects=True)
    rows = sql("SELECT * FROM wishlist WHERE user_id=? AND is_active=1 ORDER BY id", (uid,))
    assert len(rows)==2 and all(x["source"]=="photo" for x in rows), [dict(x) for x in rows]
    print("PASS 5 拍照确认页点「加入待购清单」批量入库，source=photo；未点加入前库为空已在步骤2/5前置断言")
    if "--ocr" in sys.argv:
        img = Path("/workspace/costco/receipts/2026-10-08_0952_inv205300.jpg")
        before = sql("SELECT COUNT(*) c FROM wishlist WHERE user_id=? AND is_active=1", (uid,))[0]["c"]
        with open(img,"rb") as fh:
            r = c.post("/wishlist/photo", data={"receipt":(fh, img.name)}, content_type="multipart/form-data")
        body = r.get_data(as_text=True)
        assert "加入待购清单" in body and ("1694477" in body or "PEROG" in body or "PEXOG" in body), body[:1500]
        after = sql("SELECT COUNT(*) c FROM wishlist WHERE user_id=? AND is_active=1", (uid,))[0]["c"]
        assert after==before, "识别到确认页但未点加入时不应入库"
        print(f"PASS 6 真票拍照识别到确认页（未点加入库不变 {before}->{after}），确认页内容节选含代码/名称")
    print("ALL PASS (test_wishlist)")
finally:
    cleanup(); print("已清理 TEST 待购用户数据。")
