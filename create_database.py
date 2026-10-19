#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Costco 小票 App — 本地数据库建库脚本（仅建结构，不开发业务功能）

数据库文件：data/costco_app.db（SQLite，新库）
旧库区别：data/costco.db 是早期电脑版 Flask 原型专用（仅 receipts/receipt_items
两张简单表，已有 2 条实测小票记录），本脚本不碰它、不覆盖它。

特点：
- 可重复运行：全部使用 CREATE TABLE/INDEX IF NOT EXISTS，重复运行不会删数据。
- 不硬编码任何账号/密码；运营者账号以后通过正式注册/初始化流程创建，
  并用 role='admin' 区分。密码只存哈希（password_hash），绝不存明文。
- 运行后会做一次自检：开启事务插入一条标注 TEST 的示例数据 -> 查出验证 -> 回滚，
  因此验证完仍是空库（示例数据不保留），详见 DATABASE.md。

用法：
    python3 create_database.py              # 建库/补齐结构 + 自检（默认）
    python3 create_database.py --no-test    # 只建库，不跑自检
    python3 create_database.py --db 路径    # 指定其他 db 路径（测试用）
"""
import argparse
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
DEFAULT_DB = BASE / "data" / "costco_app.db"

SCHEMA = r"""
-- ============ 用户 / 运营后台 ============
-- role: user=普通用户, admin=运营者（后台管理）。不要在代码里写死账号密码。
-- password_hash: 只存密码哈希占位/正式哈希，绝不存明文。
-- subscription_*: 订阅状态预留（free/trial/active/expired/cancelled），由后台管理。
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    username TEXT UNIQUE,
    display_name TEXT,
    password_hash TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user','admin')),
    subscription_status TEXT NOT NULL DEFAULT 'free'
        CHECK (subscription_status IN ('free','trial','active','expired','cancelled')),
    subscription_plan TEXT,
    subscription_expires_at TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    password_reset_token_hash TEXT,
    password_reset_expires_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_login_at TEXT
);

-- ============ 门店 ============
CREATE TABLE IF NOT EXISTS stores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_code TEXT NOT NULL UNIQUE,   -- Costco 门店代码，如 255
    city TEXT,
    province TEXT,                      -- 如 BC
    country TEXT NOT NULL DEFAULT 'Canada',
    store_name TEXT,
    address TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============ 已入库小票（历史购买库的主表） ============
-- 历史查询基于 receipts + receipt_items，不另建重复历史表（查询示例见 DATABASE.md）。
CREATE TABLE IF NOT EXISTS receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    store_id INTEGER REFERENCES stores(id),
    store_code TEXT,                    -- 冗余保存小票上印的门店代码，门店表缺失时也能查
    purchase_date TEXT,                 -- YYYY/MM/DD 或 YYYY-MM-DD，沿用小票日期
    subtotal REAL,                      -- 商品小计（已含折扣口径由录入端保证）
    fees_total REAL NOT NULL DEFAULT 0, -- 环保费+押金等费用合计
    tax REAL NOT NULL DEFAULT 0,
    total REAL,
    item_count INTEGER,
    invoice_no TEXT,                  -- 发票/交易号（如小票可得，防重判重用）
    image_path TEXT,
    source TEXT NOT NULL DEFAULT 'receipt_scan',
    imported_at TEXT NOT NULL DEFAULT (datetime('now')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============ 小票商品明细（按小票顺序保存） ============
-- line_order: 在这张小票上的行顺序；折扣/环保费/押金跟在所属商品上，
-- 与核对页“商品一行、折扣/费用红字小行紧跟其下、顺序同小票”一致。
CREATE TABLE IF NOT EXISTS receipt_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    item_code TEXT,
    item_name TEXT,
    price REAL,
    discount REAL NOT NULL DEFAULT 0,    -- 折扣金额，存负数（如 -6.50）或 0
    enviro_fee REAL NOT NULL DEFAULT 0,  -- 环保费 ENVIRO FEE
    deposit REAL NOT NULL DEFAULT 0,     -- 押金 DEPOSIT
    quantity INTEGER NOT NULL DEFAULT 1,
    is_manual INTEGER NOT NULL DEFAULT 0, -- 1=用户手工加行（手填标记）
    line_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============ 待购 / 未来想买清单 ============
-- source: photo=拍照录入, history=从已购记录提取, manual=手工录入
-- Costco 折扣通常 3-5 元，不设期望价格门槛：出现打折就提醒（用户 2026-10-18 拍板）。
CREATE TABLE IF NOT EXISTS wishlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    item_code TEXT,
    item_name TEXT,
    note TEXT,                           -- 期望/备注（不是价格门槛）
    source TEXT NOT NULL DEFAULT 'manual'
        CHECK (source IN ('photo','history','manual')),
    source_receipt_item_id INTEGER REFERENCES receipt_items(id),
    is_active INTEGER NOT NULL DEFAULT 1,
    is_alerted INTEGER NOT NULL DEFAULT 0, -- 是否已提醒
    last_alerted_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============ 后台打折导入批次 ============
CREATE TABLE IF NOT EXISTS deal_import_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_date TEXT NOT NULL DEFAULT (datetime('now')), -- 导入日期/时间
    collected_date TEXT,                                  -- 收集日期
    source TEXT,                                          -- 如 bot_daily / manual / grok
    item_count INTEGER NOT NULL DEFAULT 0,                -- 本批次条数
    status TEXT NOT NULL DEFAULT 'completed',
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============ 后台打折商品库（不直接全量展示给客户） ============
-- 由 Bot 每天收集导入（频率正式定版待用户确认）；客户只看与自己相关的匹配提醒。
CREATE TABLE IF NOT EXISTS deals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER REFERENCES deal_import_batches(id),
    item_code TEXT,
    item_name TEXT,
    original_price REAL,
    sale_price REAL,
    savings REAL,                        -- 省了多少（原价-折后价）
    province TEXT,
    store_id INTEGER REFERENCES stores(id),
    store_code TEXT,
    start_date TEXT,
    end_date TEXT,
    collected_at TEXT,                   -- 收集日期/时间
    source TEXT,                         -- 来源批次/渠道说明
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============ 提醒 ============
-- alert_type: wishlist_deal=待购打折, price_adjust_30d=30天内价保, restock_over30d=超30天补货
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    alert_type TEXT NOT NULL
        CHECK (alert_type IN ('wishlist_deal','price_adjust_30d','restock_over30d')),
    item_code TEXT,
    item_name TEXT,
    receipt_id INTEGER REFERENCES receipts(id),
    wishlist_id INTEGER REFERENCES wishlist(id),
    deal_id INTEGER REFERENCES deals(id),
    message TEXT,
    triggered_at TEXT NOT NULL DEFAULT (datetime('now')),
    is_sent INTEGER NOT NULL DEFAULT 0,
    sent_at TEXT,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_receipts_user_date ON receipts(user_id, purchase_date);
CREATE INDEX IF NOT EXISTS idx_receipts_store_code ON receipts(store_code);
CREATE INDEX IF NOT EXISTS idx_items_receipt ON receipt_items(receipt_id, line_order);
CREATE INDEX IF NOT EXISTS idx_items_code ON receipt_items(item_code);
CREATE INDEX IF NOT EXISTS idx_items_name ON receipt_items(item_name);
CREATE INDEX IF NOT EXISTS idx_wishlist_user ON wishlist(user_id, is_active);
CREATE INDEX IF NOT EXISTS idx_wishlist_code ON wishlist(item_code);
CREATE INDEX IF NOT EXISTS idx_deals_code ON deals(item_code);
CREATE INDEX IF NOT EXISTS idx_deals_dates ON deals(start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_deals_province_store ON deals(province, store_code);
CREATE INDEX IF NOT EXISTS idx_alerts_user ON alerts(user_id, is_sent, triggered_at);
-- 同一用户同一商品只保留一条在用的待购（软删除/停用不受此限）
CREATE UNIQUE INDEX IF NOT EXISTS uq_wishlist_user_code_active
    ON wishlist(user_id, item_code) WHERE is_active = 1 AND item_code IS NOT NULL;
"""

EXPECTED_TABLES = [
    "users", "stores", "receipts", "receipt_items",
    "wishlist", "deal_import_batches", "deals", "alerts",
]


def create(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    con.commit()
    return con


def list_tables(con: sqlite3.Connection):
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def self_test(con: sqlite3.Connection) -> None:
    """插入一条标注 TEST 的示例数据并查出，随后回滚，保持空库。"""
    print("自检：插入 TEST 示例数据（验证后回滚，不保留）...")
    try:
        con.execute("BEGIN")
        cur = con.execute(
            "INSERT INTO users(email, username, password_hash, role) VALUES(?,?,?,?)",
            ("test@example.invalid", "TEST_USER", "TEST_PLACEHOLDER_HASH_NOT_A_REAL_PASSWORD", "user"),
        )
        uid = cur.lastrowid
        cur = con.execute(
            "INSERT INTO receipts(user_id, store_code, purchase_date, subtotal, fees_total, tax, total, item_count) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (uid, "TEST255", "2026/10/18", 16.99, 0.17, 0.0, 17.16, 1),
        )
        rid = cur.lastrowid
        con.execute(
            "INSERT INTO receipt_items(receipt_id, item_code, item_name, price, discount, enviro_fee, deposit, is_manual, line_order) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (rid, "TEST1694477", "TEST PEROGIES", 16.99, 0, 0.07, 0.10, 0, 1),
        )
        con.execute(
            "INSERT INTO wishlist(user_id, item_code, item_name, source, note) VALUES(?,?,?,?,?)",
            (uid, "TEST1694477", "TEST PEROGIES", "manual", "TEST 示例，可清理"),
        )
        row = con.execute(
            "SELECT r.store_code, r.purchase_date, i.item_code, i.item_name, i.price "
            "FROM receipts r JOIN receipt_items i ON i.receipt_id = r.id WHERE r.id = ?",
            (rid,),
        ).fetchone()
        w = con.execute("SELECT item_code, source FROM wishlist WHERE user_id=?", (uid,)).fetchone()
        assert row == ("TEST255", "2026/10/18", "TEST1694477", "TEST PEROGIES", 16.99), row
        assert w == ("TEST1694477", "manual"), w
        print(f"  查出示例小票明细：{row}")
        print(f"  查出示例待购：{w}")
    finally:
        con.rollback()
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in EXPECTED_TABLES}
    assert all(v == 0 for v in counts.values()), counts
    print(f"  回滚后各表条数（应全为 0）：{counts}")


def main() -> int:
    ap = argparse.ArgumentParser(description="建立 Costco 小票 App 本地 SQLite 数据库（仅结构）")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="数据库文件路径")
    ap.add_argument("--no-test", action="store_true", help="只建库，不跑插入自检")
    args = ap.parse_args()

    db_path = Path(args.db)
    con = create(db_path)
    tables = list_tables(con)
    missing = [t for t in EXPECTED_TABLES if t not in tables]
    print(f"数据库文件：{db_path}")
    print(f"已建表（{len(tables)}）：{', '.join(tables)}")
    if missing:
        print(f"缺表：{missing}", file=sys.stderr)
        return 1
    if not args.no_test:
        self_test(con)
    con.close()
    print("完成：结构已建好（可重复运行，不会覆盖旧库 data/costco.db）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
