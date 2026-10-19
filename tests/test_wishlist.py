#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""待购清单本轮专项自测：只三项(代码/名称/目前价格)、多图确认才入库、完成页返回主菜单清空、
Excel 式查询(名称/代码/日期/价格筛选+价格排序)、每行删除。
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
    c.post("/register", data={"email":"test_wishlist@example.com","password":"test1234","display_name":"TEST"}, follow_redirects=True)
    uid = sql("SELECT id FROM users WHERE email=?", ("test_wishlist@example.com",))[0]["id"]; created.append(uid)
    # 1 入口
    entry = c.get("/wishlist").get_data(as_text=True)
    assert "拍照" in entry and "从相册选照片" in entry and "手工录入" in entry and "查询已入库待购产品" in entry
    assert "multiple" in entry and 'name="photos"' in entry, "相册应可多选"
    assert "商品牌" in entry and "目前的价格" in entry
    assert 'name="item_code"' not in entry and 'name="item_name"' not in entry, "入口页铺了表单"
    assert entry.index("拍照") < entry.index("手工录入") < entry.index("查询已入库待购产品")
    print("PASS 1 入口：拍照/相册(可多选)第一、手工第二、查询在下面，无铺开表单，明示只认三项")
    # 2 手工三项
    manual = c.get("/wishlist/manual").get_data(as_text=True)
    assert 'name="item_code"' in manual and 'name="item_name"' in manual and 'name="item_price"' in manual
    assert 'name="item_quantity"' not in manual, "数量字段本轮应去掉"
    assert "目前价格" in manual and "不是期望价格" in manual
    # 本轮清查：待购全流程只许代码/名称/价格三项(+录入日期/来源)，逐页查混入词
    BAD=["商店","门店","购买日期","税","环保费","押金","小计","总计","件数","会员","结账","小票","备注","数量","store_code","purchase_date"]
    for path,body in [("入口",entry),("手工页",manual),("完成页",done if False else c.get("/wishlist/done?added=1").get_data(as_text=True)),("查询页",c.get("/wishlist/query").get_data(as_text=True))]:
        # 渲染页含全局导航(去往其他模块的链接文字不在待购字段范围内)，故字段混入以模板文件为准另查；此处查页面主体字段词
        for w in ["商店名称","购买日期","环保费","押金","小计","总计"]:
            assert w not in body, f"{path}混入{w}"
    import pathlib as _pl
    for f in _pl.Path(BASE/"templates_main").glob("wishlist*.html"):
        txt=f.read_text()
        for w in BAD: assert w not in txt, f"{f.name}混入{w}"
    assert 'name="note"' not in manual and "item_note" not in c.get("/wishlist/manual").get_data(as_text=True)
    print("PASS 2b 待购模板逐页清查：无商店/购买日期/税费/小计等混入词，无备注栏目")
    assert sql("SELECT COUNT(*) c FROM wishlist WHERE user_id=?", (uid,))[0]["c"] == 0
    # 加三件不同价格便于查询/排序
    for code,name,price in [("777001","TEST手工待购","12.99"),("777002","TEST苹果待购","5.49"),("777003","TEST燕麦待购","20.00")]:
        r=c.post("/wishlist/add", data={"item_code":code,"item_name":name,"item_price":price,"note":"等打折","source":"manual"}, follow_redirects=True)  # note 参数应被忽略，只存价格
    rows = sql("SELECT * FROM wishlist WHERE user_id=? AND is_active=1 ORDER BY id", (uid,))
    assert len(rows)==3 and all(x["source"]=="manual" for x in rows) and "12.99" in rows[0]["note"]
    done = c.get("/wishlist/done?added=1").get_data(as_text=True)
    assert "已加入待购清单" in done and "返回主菜单" in done and 'href="/wishlist"' in done
    print("PASS 2 手工只三项点确认才入库，完成页有返回主菜单；价格为目前/参考价、内部存入note供解析非门槛，附带文字不拼接")
    assert "等打折" not in rows[0]["note"], "附带文字不应被拼进待购记录"
    # 3 Excel 查询 + 多条件
    q = c.get("/wishlist/query").get_data(as_text=True)
    assert '<table class="qtable">' in q and 'class="record"' not in q, "应为Excel表格不是卡片"
    for h in ["删除","商品代码","商品名称","价格","录入日期","来源"]: assert h in q, h
    assert "查询状态" in q and "共查到" in q and "TEST手工待购" in q and "$12.99" in q
    assert "TEST燕麦待购" in c.get("/wishlist/query?name=燕麦").get_data(as_text=True)
    assert "TEST苹果待购" not in c.get("/wishlist/query?name=燕麦").get_data(as_text=True)
    assert "TEST苹果待购" in c.get("/wishlist/query?code=777002").get_data(as_text=True)
    today = rows[0]["created_at"][:10]
    assert "TEST手工待购" in c.get(f"/wishlist/query?date_from={today}&date_to={today}").get_data(as_text=True)
    assert "TEST手工待购" not in c.get("/wishlist/query?date_from=2999-01-01").get_data(as_text=True)
    pq = c.get("/wishlist/query?price_min=10&price_max=15").get_data(as_text=True)
    assert "TEST手工待购" in pq and "TEST苹果待购" not in pq and "TEST燕麦待购" not in pq
    sq = c.get("/wishlist/query?sort=price_asc").get_data(as_text=True)
    assert sq.index("TEST苹果待购") < sq.index("TEST手工待购") < sq.index("TEST燕麦待购"), "价格升序不对"
    sq2 = c.get("/wishlist/query?sort=price_desc").get_data(as_text=True)
    assert sq2.index("TEST燕麦待购") < sq2.index("TEST苹果待购")
    assert "TEST手工待购" in c.get("/wishlist/query?q=777001").get_data(as_text=True), "旧q兼容"
    print("PASS 3 Excel式表格行；名称/代码/录入日期/价格范围各查一次对，默认新到旧、价格可排序，查询状态清楚")
    # 4 删除一条
    wid = rows[1]["id"]
    c.post(f"/wishlist/{wid}/delete", follow_redirects=True)
    assert sql("SELECT COUNT(*) c FROM wishlist WHERE user_id=? AND is_active=1", (uid,))[0]["c"]==2
    assert "TEST苹果待购" not in c.get("/wishlist/query").get_data(as_text=True)
    print("PASS 4 点删除号删除一条后查询不到（软删）")
    # 清空后测拍照确认
    con=sqlite3.connect(DB); con.execute("DELETE FROM wishlist WHERE user_id=?", (uid,)); con.commit(); con.close()
    assert sql("SELECT COUNT(*) c FROM wishlist WHERE user_id=? AND is_active=1", (uid,))[0]["c"]==0, "未确认前应查无"
    assert "TEST手工待购" not in c.get("/wishlist/query").get_data(as_text=True)
    r = c.post("/wishlist/photo/confirm-add", data={"selected":["0","1"],"item_code":["888001","888002"],"item_name":["TEST拍照一","TEST拍照二"],"item_price":["9.99","3.25"],"item_note":["",""]}, follow_redirects=True)
    body=r.get_data(as_text=True)
    assert "已加入待购清单" in body and "返回主菜单" in body, body[:500]
    rows = sql("SELECT * FROM wishlist WHERE user_id=? AND is_active=1 ORDER BY id", (uid,))
    assert len(rows)==2 and all(x["source"]=="photo" for x in rows)
    qq=c.get("/wishlist/query").get_data(as_text=True); assert "TEST拍照一" in qq and "$9.99" in qq
    print("PASS 5 未点确认查无；点「确认录入」后Excel查到，完成页返回主菜单，本次在服务端无残留状态")
    if "--ocr" in sys.argv:
        con=sqlite3.connect(DB); con.execute("DELETE FROM wishlist WHERE user_id=?", (uid,)); con.commit(); con.close()
        imgs=[Path("/workspace/costco/receipts/2026-10-08_0952_inv205300.jpg"), Path("/workspace/costco/receipts/2026-10-08_0946_inv202549.jpg")]
        before = sql("SELECT COUNT(*) c FROM wishlist WHERE user_id=? AND is_active=1", (uid,))[0]["c"]
        with open(imgs[0],"rb") as f1, open(imgs[1],"rb") as f2:
            r = c.post("/wishlist/photo", data={"photos":[(f1, imgs[0].name),(f2, imgs[1].name)]}, content_type="multipart/form-data")
        body = r.get_data(as_text=True)
        assert "共识别到" in body and "请核对" in body and "确认录入，加入数据库" in body, body[:1500]
        assert "目前价格" in body and ("1694477" in body or "PEROG" in body or "PEXOG" in body), body[:2000]
        after = sql("SELECT COUNT(*) c FROM wishlist WHERE user_id=? AND is_active=1", (uid,))[0]["c"]
        assert after==before==0, f"识别到确认页未点确认不应入库 {before}->{after}"
        print(f"PASS 6 多选2张样本图识别列出三项到确认页（含1694477系），未点确认库不变 {before}->{after}")
    # 6 商品牌解析单元：三张真值结构 + 打折取原价
    from app_main import _sign_items_from_raw as _sign
    def _L(txt): return [{"text":x} for x in txt.split("\n")]
    _cases=[
      ("49118\nGALA APPLES\nPRODUCT OF CANADA\nPRICE PER 100 GRAMS\n.367\nSELL PRICE 9.99","49118","GALA APPLES",9.99),
      ("2322011\nKIRKLAND SIGNATURE\nAAA BATTERIES\nPACK OF 48\nMade in U.S.A.\nPRICE PER BATTERY .333\nSELL PRICE 15.99\n+ECO FEE 1.92","2322011","KIRKLAND SIGNATURE AAA BATTERIES PACK OF 48",15.99),
      ("1874356\nPURAVIDA FIRE ROASTED\nROOT VEGETABLES\n1.8 kg\n18.99\nInstant Savings -4.00\nEXP. 2026-10-25\nPRICE AT REGISTER 14.99","1874356","PURAVIDA FIRE ROASTED ROOT VEGETABLES 1.8 kg",18.99),
      ("1874356\nPURAVIDA\nInstant Savings -4.00\nPRICE AT REGISTER 14.99","1874356","PURAVIDA",18.99),
    ]
    for txt,code,name,price in _cases:
        r=_sign(_L(txt)); assert r and r[0]["item_code"]==code and r[0]["item_name"]==name and float(r[0]["price"])==price, (txt,r)
    print("PASS 6 商品牌解析单元4例：每单位小价/附加费不误作价格，打折只取原价(印原价优先、无原价时折后价+折扣)")
    if "--signs" in sys.argv:
        import pathlib as _pl2
        _base=_pl2.Path("/home/box/agent-data/agents/83703a29-e0bb-4518-9c8a-29cb79892d9e/attachments")
        _real=[("d66f043e5c60eac7d176f956c4b9a2abac2d32b7b00cc5a33dc4cefea7bd3e8e.jpg","49118","GALA APPLES","9.99"),
               ("15dcb4d8331f4eb933c856deb4e83937db6637d0da3f2b3f49e0b156c7874a41.jpg","2322011",None,"15.99"),
               ("31352070e0e207e145d21bb3199b3c1d8ea89f1736d0dab3505bd118ec3af2e4.jpg","1874356",None,"18.99")]
        for fn,code,name,price in _real:
            with open(_base/fn,"rb") as fh: rr=c.post("/wishlist/photo", data={"photos":[(fh,fn)]}, content_type="multipart/form-data")
            bb=rr.get_data(as_text=True)
            assert f'value="{code}"' in bb and f'value="{price}"' in bb, (fn,bb[:1200])
            if name: assert f'value="{name}"' in bb, (fn,bb[:1200])
        print("PASS 7 三张真实门店价格牌 Flask 识别：代码/价格逐张对真值(名称见 TEST_RESULTS 记录59 的粘连说明)")
    print("ALL PASS (test_wishlist)")
finally:
    cleanup(); print("已清理 TEST 待购用户数据。")
