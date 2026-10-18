# Costco 小票 App — 本地数据库说明（DATABASE）

> 建立日期：2026-10-18（America/Vancouver）
> 状态：2026-10-18 已在此库上建成**本地先行版主程序** `app_main.py`（注册/登录、小票确认入库、待购、历史查询、后台打折导入、三类提醒、运营后台，详见本文第 6 节与 TEST_RESULTS 记录55）。线上网页版（docs/，GitHub Pages）逻辑未改，仍用浏览器 IndexedDB；旧电脑版 Flask 原型仍用旧库 `app.py`。

## 1. 两个数据库文件的区别（别弄混）

| 文件 | 是什么 | 内容 | 本次是否动它 |
|------|--------|------|--------------|
| `data/costco.db` | 早期电脑版 Flask 原型专用旧库 | 仅 `receipts`、`receipt_items` 两张简单表，已有 2 条 2026-10-17 实测入库小票 | **不动、不覆盖** |
| `data/costco_app.db` | 本次按总体框架新建的正式结构库（本地） | 下列 8 张表，目前为空库 | 新建 |

两个文件都在 `data/` 目录，已被 `.gitignore` 的 `data/` 规则排除，**不会提交到公开 GitHub**。可提交的是建库脚本 `create_database.py` 和本文档。

## 2. 怎么建 / 怎么重建

```bash
cd /workspace/costco-price-app
python3 create_database.py            # 建库 + 插入 TEST 示例自检（查出后回滚，保持空库）
python3 create_database.py --no-test  # 只建结构
```

脚本可重复运行（全部 `IF NOT EXISTS`），重复运行不会删已有数据。验证方法见 TEST_RESULTS.md 记录54。

## 3. 表一览（各表干什么）

| 表 | 用途 |
|----|------|
| `users` | 用户与运营后台基础：邮箱/账号、密码哈希（`password_hash`，只存哈希不存明文）、注册时间（`created_at`）、订阅状态（`subscription_status/plan/expires_at`）、密码重置令牌哈希与过期、`role`（`user` 普通用户 / `admin` 运营者）。**代码里不硬编码任何账号密码**，运营者账号以后走正式初始化/注册流程并设 `role='admin'`。 |
| `stores` | 门店：门店代码 `store_code`（如 255）、城市、省份。 |
| `receipts` | 已入库小票主表：用户、门店代码、购买日期、小计、费用合计 `fees_total`、税 `tax`、总计、件数、入库时间。 |
| `receipt_items` | 小票商品明细：小票 id、商品代码、名称、价格、折扣 `discount`、环保费 `enviro_fee`、押金 `deposit`、手填标记 `is_manual`、行顺序 `line_order`（按小票顺序保存；折扣/费用跟在所属商品的字段上，与核对页顺序一致）。 |
| `wishlist` | 待购/未来想买清单：用户、商品代码、名称、备注 `note`、来源 `source`（`photo` 拍照 / `history` 从已购记录提取 / `manual` 手工）、加入时间、是否已提醒 `is_alerted`。**不设期望价格门槛**：Costco 折扣通常 3–5 元，出现打折就提醒（用户 2026-10-18 拍板）。 |
| `deals` | **后台**打折商品库：商品代码、名称、原价、折后价、省了多少 `savings`、省份、门店、开始/结束日期、收集日期、来源批次。由 Bot 每天收集导入；**不直接全量展示给客户**，客户只收到与自己待购/已购相关的提醒。 |
| `deal_import_batches` | 打折导入批次：导入日期、来源、条数，便于追溯每天导入了什么。 |
| `alerts` | 提醒：用户、类型（`wishlist_deal` 待购打折 / `price_adjust_30d` 30天内价保 / `restock_over30d` 超30天补货）、关联商品/小票/待购/打折、触发日期、是否已发送。 |

## 4. 历史购买查询（不另建历史表）

历史购买查询直接基于 `receipts + receipt_items`，不再建重复表。示例（把 `:uid` 换成用户 id）：

```sql
-- 按时间查：某用户最近一段时间的购买（汇总到小票）
SELECT id, purchase_date, store_code, total FROM receipts
WHERE user_id = :uid AND purchase_date BETWEEN '2026/09/01' AND '2026/10/18'
ORDER BY purchase_date DESC;

-- 按商品名称查（模糊）
SELECT r.purchase_date, r.store_code, i.item_code, i.item_name, i.price
FROM receipt_items i JOIN receipts r ON r.id = i.receipt_id
WHERE r.user_id = :uid AND i.item_name LIKE '%BOUNTY%'
ORDER BY r.purchase_date DESC;

-- 按商品代码查 + 汇总（买过几次、上次多少钱、平均价）
SELECT i.item_code, i.item_name, COUNT(*) AS 买过次数,
       MIN(r.purchase_date) AS 第一次, MAX(r.purchase_date) AS 最近一次,
       (SELECT price FROM receipt_items x JOIN receipts y ON y.id = x.receipt_id
        WHERE x.item_code = i.item_code ORDER BY y.purchase_date DESC LIMIT 1) AS 上次价格
FROM receipt_items i JOIN receipts r ON r.id = i.receipt_id
WHERE r.user_id = :uid AND i.item_code = '1234567'
GROUP BY i.item_code, i.item_name;
```

待购清单同样可查（如 `SELECT * FROM wishlist WHERE user_id=:uid AND is_active=1`）；待购与打折匹配、已购与打折的 30 天规则，都以商品代码 `item_code` 关联 `deals.item_code` 为主、名称为辅。

## 5. 尚未开发（如实标注）

本地先行版已做（见第 6 节）：注册/登录、待购三种录入、后台打折 CSV/JSON 导入、代码匹配三类提醒、历史查询界面、运营后台用户/订阅/管理员设临时密码。
**仍未做**：打折数据每天/每周 Bot 自动收集（现为管理员手动导入）、订阅收费支付、自助改密与邮件密码重置（本地版由管理员设临时密码）、正式手机 App、云端部署（Google Cloud / Azure / AWS 待定）、提醒推送（现为站内提醒页）。详见 PROGRESS.md。

## 6. 怎么启动正式程序（本地先行版）

入口是新文件 `app_main.py`（不要用旧 `app.py`，那是旧库原型）：

```bash
cd /workspace/costco-price-app
./run_main.sh
# 或: .venv/bin/python app_main.py
```

浏览器打开 **http://127.0.0.1:5004**（端口可用环境变量 COSTCO_MAIN_PORT 改）。先注册一个普通账号即可使用。

创建运营者(admin)账号（二选一，密码都不写进代码/仓库）：
- 交互：`.venv/bin/python init_admin.py`，按提示输邮箱和密码；
- 或首次启动前设环境变量 `COSTCO_ADMIN_EMAIL` + `COSTCO_ADMIN_PASSWORD`（库中无管理员时自动创建）。

打折示例数据：`sample_data/sample_deals.csv`（**明确为示例**，含真实样本小票的 3 个商品代码便于测试对比），在运营后台粘贴/上传导入，导入后自动为全体用户生成提醒；用户也可在「我的提醒」页点「检查最新打折提醒」。自测脚本：`.venv/bin/python tests/test_main_app.py --ocr`（TEST 账号，测完自动清理）。
