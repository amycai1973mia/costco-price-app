# Costco 小票 App · 产品方案

> 版本：v0.2（2026-10-17）· 作者：Amy Cai
> 本版新增内容：**感兴趣清单（Wishlist）**、**价保／补货两种提醒规则引擎**、**按省份／门店划分的打折商品数据库**、**本地查询不耗 token 的架构**，以及配套的数据模型、MVP 路线和待确认问题。
> 现有原型：`/workspace/costco/costco.db`（SQLite）已有 2 张小票、12 条购买明细、4 个想买商品，以及 161 条比价记录；`sale_items.json` 是一次抓取的打折清单，共 225 件（Port Coquitlam #255，10/13–10/25）。本方案里的数据结构就是在这个原型的基础上扩充出来的。

---

## 1. 产品定位

一句话：**拍下 Costco 小票，App 帮你记账、盯价格，该去做价格调整或者该补货的时候提醒你。**

| 用户痛点 | App 的解法 |
|---|---|
| 买完东西降价了却不知道，错过 30 天价保 | 购买记录和打折库自动比对，降价就推送"去做价格调整" |
| 常买的消耗品不知道什么时候便宜 | 超过 30 天后再打折，推送"可以补货了" |
| 想买的东西想等打折再买，但记不住 | 感兴趣清单，一打折就提醒 |
| 每周的优惠册太长，不想自己翻 | 按省份和门店整理好打折库，只推送和我有关的商品 |

目标用户：加拿大 Costco 会员，MVP 先做 BC 省（Port Coquitlam #255）。

---

## 2. 核心功能

### 2.1 小票识别与购买记录（已有原型）
- 拍照或上传小票，OCR 识别出门店、日期、时间、小票号，以及每行商品的**商品代码（item number）**、名称、单价、数量和即时折扣（instant savings）。
- 入库到 `receipts` 和 `receipt_items` 两张表。**商品代码是三个库联动的主键**。
- OCR 只在上传小票时调用一次 AI（或者用端侧 OCR），之后的查询都不再调用。

### 2.2 感兴趣清单（Wishlist／关注清单）【新增】
- 用户把以后想买的商品加进清单，打折时再买。
- 添加方式：
  1. 在打折库里浏览时点"☆关注"；
  2. 在历史购买记录里点"以后再买"；
  3. 手动输入商品代码或名称（名称会模糊匹配到商品主数据）；
  4. 扫商品价签上的条码或编号。
- 每条记录可以设置：**目标价**（可不填，不填时只要打折就提醒）、**最低折扣额或折扣率**、关注的门店或省份、备注、有效期（例如"圣诞前要买"）。
- 状态：`active`（关注中）、`bought`（已购买，买入时自动关联小票）、`paused`、`expired`。
- 加入清单的商品**买入后**，清单项自动转为 `bought`，同时进入 30 天价保监控（见 3.2）。

### 2.3 打折商品库浏览
- 按"我的门店"展示本周有效的打折商品，可以按分类、折扣额、到期日筛选。
- ⭐ 标记"我买过"或"在我清单里"的商品（原型 `build.py` 已经实现了这个标记）。

### 2.4 提醒中心
- 汇总所有提醒：价保、补货、清单命中、即将到期。
- 每条提醒有操作：价保提醒"已办理／忽略"，补货和清单提醒"已加入购物清单／忽略／不再提醒此商品"。
- 已办理的价保会记录退款金额，累计显示"App 帮你省了 $xx"。

---

## 3. 提醒规则引擎【新增】

### 3.1 总体逻辑
三个库按 **商品代码 + 门店（或省份）+ 优惠有效期** 联动匹配：

```
            ┌──────────────┐
            │ 打折商品库    │  (每周或每天导入一批，约 200–300 条)
            │ promotions   │
            └──────┬───────┘
                   │ item_number + 门店/省份 + 优惠期 覆盖今天
       ┌───────────┼───────────────┐
       ▼                           ▼
┌──────────────┐           ┌──────────────┐
│ 购买记录      │           │ 感兴趣清单    │
│ receipt_items│           │ wishlist     │
└──────┬───────┘           └──────┬───────┘
       │ 按购买天数分流             │
  ≤30天 → 价保提醒            命中 → 清单提醒
  >30天 → 补货提醒
       └───────────┬───────────────┘
                   ▼
            ┌──────────────┐
            │ 提醒表 alerts │ → 推送 / App 内提醒 / 邮件
            └──────────────┘
```

### 3.2 规则一：30 天内降价 → 价格调整提醒（Price Adjustment）
Costco 加拿大的价保政策：购买后 30 天内，如果同一商品在门店降价（包括优惠册的即时折扣），会员带着小票或会员卡记录到会员服务台，可以退还差价。具体例外以门店实际执行为准（App 内需要提示），常见的有：汽油、烟酒、部分特殊订单商品；同一张优惠券有限购数量；线上订单要走 costco.ca 客服。

| 项目 | 规则 |
|---|---|
| 触发条件 | `receipt_items.item_number = promotions.item_number`，促销门店等于购买门店（或促销按省份或区域生效，且购买门店在该范围内），并且 **折后价 < 实付单价**。实付单价 = 小票单价 − 小票上已享受的即时折扣（避免把已经享受过的折扣重复算一次） |
| 时间窗口 | 促销生效期与 **[购买日, 购买日+30 天]** 有重叠，并且今天 ≤ min(促销结束日, 购买日+30) |
| 可退金额 | `(实付单价 − 折后价) × 数量`，取上限或扣除限购部分后的金额；低于阈值（默认 $1，可设置）不提醒 |
| 提醒时机 | ① 新打折数据入库后**立即**提醒；② 截止日前 3 天和前 1 天**再提醒一次**（截止日 = min(促销结束日, 购买日+30)）；③ 截止日过后自动标记为 `expired` |
| 提醒内容 | "你 10/08 在 Port Coquitlam 买的 QUICK OATS 实付 $11.99，现在特价 $8.99，可以退 $3.00。请在 10/25 前带小票（#202549）去会员服务台。" 附上小票图片和促销来源链接 |
| 优先级 | 高（真金白银，而且有截止日） |
| 去重 | 同一 `receipt_item_id + promotion_id` 只生成一条提醒；同一商品价格再降，生成新提醒，并说明"比上次又便宜 $x" |

### 3.3 规则二：超过 30 天再打折 → 补货提醒（Repurchase）
| 项目 | 规则 |
|---|---|
| 触发条件 | 用户**买过**该商品，并且最近一次购买距今 > 30 天，同时该商品在"我的门店"（或省份）有有效促销 |
| 降噪 | ① 只对"买过 ≥1 次"的商品提醒，可设置为"买过 ≥2 次才算常买"；② 用户可以按商品选择"不再提醒"；③ 参考购买周期：如果历史平均复购间隔是 N 天，距上次购买 < 0.5N 的降级为 App 内低优先级，不推送 |
| 提醒时机 | 新促销入库后，汇总进**每周一次的"补货摘要"**（默认周一早上，或者在用户设定的购物日前一天）；不逐条推送，避免打扰 |
| 提醒内容 | "你常买的 KIRKLAND AAA 电池（上次 9/02，$15.99）本周特价 $11.99，优惠到 10/25。" |
| 优先级 | 中 |

### 3.4 规则三：感兴趣清单命中
| 项目 | 规则 |
|---|---|
| 触发条件 | `wishlist.status = active`，`item_number` 匹配到有效促销，门店或省份匹配，并且满足用户设的条件：折后价 ≤ 目标价，或折扣额 ≥ 阈值，或"任意折扣" |
| 提醒时机 | 入库后即时推送；到期前 2 天如果还没买，再提醒一次 |
| 买入后 | 下次小票里出现该商品时，自动把清单项转为 `bought`，并进入规则一的 30 天价保监控 |
| 优先级 | 中高（用户主动关注的商品） |

### 3.5 规则优先级与冲突
- 同一商品可能同时满足多条规则，例如 30 天内刚买过、同时又在清单里。这时**只发优先级最高的一条**：价保 > 清单 > 补货。
- 每个用户每天最多推送 N 条（默认 5 条），其余进 App 内提醒中心。
- 静默时段：默认 21:00–08:00（America/Vancouver）不推送。

### 3.6 提醒方式
| 渠道 | 用途 |
|---|---|
| App 推送（APNs/FCM） | 价保、清单命中的即时提醒 |
| App 内提醒中心 | 全部提醒，可筛选、标记处理 |
| 每周摘要（推送或邮件） | 补货提醒，以及本周和我相关的打折汇总 |
| 日历提醒（可选） | 价保截止日加进系统日历 |

### 3.7 引擎运行方式
- **事件驱动**：① 打折数据导入完成；② 新小票入库（新买的商品要立刻和当前在售促销比对，有时结账时没享受到当期折扣）；③ 清单新增或修改。三种事件都会触发一次增量匹配。
- **定时任务**：每天 08:00 跑一次截止日检查（价保倒计时提醒，把过期提醒标为 `expired`）。
- 匹配是**纯 SQL**（见 5.4），不调用 AI。

---

## 4. 打折商品数据库（按省份／门店）【新增】

### 4.1 层级划分
```
国家 (CA)
 └─ 优惠区域 region_group（Costco 加拿大优惠册按区域分发：West = BC/AB/SK/MB；Ontario；Quebec；Atlantic）
     └─ 省份 province（BC、AB、SK、MB、ON、QC……）
         └─ 门店 warehouse（如 #255 Port Coquitlam、#54 Burnaby……）
```
- **区域或全省统一的优惠**（例如月度优惠册的即时折扣）：促销记录到 `region_group` 或 `province` 一级，匹配时向下覆盖辖区内所有门店。
- **门店独有的价格**（清仓价，例如 .97 结尾，以及单店降价）：记录到 `warehouse_id` 一级。
- 匹配时取"最具体的一条"：门店级 > 省级 > 区域级。

### 4.2 数据来源方案对比
每次约 200–300 个打折商品（实测：10/13–10/18 这一期 Port Coquitlam 一共 225 件）。

| 方案 | 做法 | 优点 | 缺点／风险 | 建议 |
|---|---|---|---|---|
| A. 人工／半自动导入 | 运营或用户本人每周下载优惠册或页面，用脚本解析后导入，人工抽检 | 准确，合规风险最低，可以马上开始 | 每周要花人工（约 30–60 分钟） | **MVP 首选** |
| B. AI 工具辅助抽取（如 Grok） | 把优惠册图片或网页交给 AI，一次性结构化输出 JSON（商品代码、价格、起止日期），再走校验流程入库 | 能处理图片和不规则排版，开发量小 | 每次运行都要消耗 token（但**每周或每天只跑 1 次**，成本可控）；可能"幻觉"出错误价格，必须校验 | 和 A 结合，作为解析工具 |
| C. 程序自动爬取 | 定时脚本抓取官网或第三方汇总页面并解析 | 全自动，可以每天更新 | **合规风险最高**（见 4.3）；页面改版就会失效；可能被封 | 只在获得授权或使用公开 API 时采用 |
| D. 用户众包 | 用户在门店拍价签上传（门店独有清仓价的唯一可靠来源） | 能覆盖门店级的价格 | 冷启动难，需要审核 | 第二阶段 |
| E. 数据合作／授权 | 和优惠汇总网站谈数据授权 | 稳定、合法 | 需要商务谈判，可能要付费 | 规模化阶段 |

**推荐路径**：MVP 用 A+B（半自动：AI 一周抽取一次，脚本校验，人工确认后入库）→ 验证需求后上 D 和 E → 只在授权范围内做 C。

### 4.3 合规注意事项
1. **Costco 官网（costco.ca）的使用条款**一般禁止用机器人、爬虫等自动化手段抓取内容。上线前必须细读当前版本的条款和 robots.txt，默认**不对官网做自动化爬取**。用户自己登录后的会员数据（例如线上订单）只能由用户本人授权导入。
2. **第三方优惠网站**（例如 cocowest.ca、smartcanucks、Reddit 上用户整理的帖子）的文字和图片版权属于作者。产品**只存事实数据**（商品代码、价格、日期），**不转载图片和原文**，并标注来源。商用之前要取得授权，或改用合作方式。Reddit 的数据访问要遵守它的 API 条款。
3. **商标**：App 名称和界面不要让人误以为是 Costco 官方产品，需要注明"非 Costco 官方应用"。
4. **抓取礼仪**（如果获得授权再做 C）：遵守 robots.txt，限速（例如 ≥5 秒一次请求），标明 User-Agent，只在低峰时段运行，有缓存的就不重复请求。
5. **价格准确性免责**：提醒里注明"以门店实际价格为准"，并给出来源和抓取时间。
6. **用户隐私**：小票包含会员消费记录，默认**只存在本机**；云同步需要用户主动开启并加密。符合加拿大 PIPEDA，以及 BC 省 PIPA 的要求。

### 4.4 更新频率
| 数据类型 | 频率 | 说明 |
|---|---|---|
| 月度优惠册（区域级即时折扣） | 每期 1 次（约每 3–4 周），新一期开始前 1–2 天导入 | 主体数据，约 200–300 条 |
| 周末或特别促销（Weekend / Hot Buys） | 每周 1–2 次（周四、周五） | 增量 |
| 门店级降价和清仓价 | 每天 1 次（众包或授权数据） | 第二阶段 |
| 过期清理 | 每天 1 次（定时任务） | 把 `end_date < 今天` 的促销标记为 `expired`，不删除，保留作价格历史 |

### 4.5 去重与生效／过期
- **业务唯一键**：`(item_number, scope_type, scope_id, start_date, end_date, sale_price)`。
  - 再次导入同一条促销：**upsert**，只更新 `last_seen_at` 和来源，不产生新记录，也不重复提醒。
  - 同一商品同一期出现不同价格：保留两条并标记 `conflict=1`，由人工核对；提醒时取官方来源，没有官方来源就取多数来源的价格。
- **多个来源合并**：同一条促销，`promotion_sources` 子表记录每个来源（官方优惠券页、第三方网站、用户上传），每个来源有一个可信度等级（官方 > 授权合作 > 多人确认 > 单一第三方 > AI 抽取未核验）。
- **生效判断**：`start_date ≤ 今天 ≤ end_date`，并且 `status='active'`。日期一律按门店本地时区（BC 为 America/Vancouver）。
- **缺少起止日期**：第三方数据只写了"到某日为止"的，`start_date` 取抓取日期，并标记 `start_inferred=1`；连结束日期都没有的不入库，或者默认 7 天有效并标为低可信度。
- **原价推算**：如果来源只给了"折后价 + 立减额"，就用 原价 = 折后价 + 立减额（原型 `build.py` 就是这么算的），并标记 `regular_inferred=1`。

### 4.6 导入流水线
```
来源（优惠册 PDF 或图片 / 网页 / 用户上传）
   → ① 抽取：脚本解析，或 AI 一次性结构化（每期只跑一次）
   → ② 校验：商品代码格式（数字，4–7 位）；折后价 + 立减额 ≈ 原价（误差 ±$0.02）；
             日期合法，且 end ≥ start；折扣率在 0–80% 之间；和上期同一商品的价格对比，差异过大要人工确认
   → ③ 标准化：门店和省份映射到 scope；名称清洗；关联商品主数据（products）
   → ④ upsert 入库 promotions + promotion_sources，写入 import_batches 批次日志
   → ⑤ 触发提醒引擎增量匹配
```

---

## 5. 技术架构：本地查询，不耗 token【新增，核心原则】

### 5.1 原则
> **AI 和爬虫只负责定期把打折数据"搬运"进数据库；用户的日常查询、清单匹配、30 天价保提醒，全部在数据库里用 SQL 完成，不调用 AI，不消耗 token。**

| 环节 | 是否调用 AI | 频率 | 成本 |
|---|---|---|---|
| 小票 OCR 识别 | 是（或端侧 OCR，不耗 token） | 每张小票 1 次 | 低 |
| 打折数据抽取入库 | 是（可选，方案 B） | 每周或每天 1 次，全体用户共享 | 极低（不随用户数增长） |
| 浏览打折库、搜索 | **否**，SQL | 随时 | 0 |
| 清单匹配、价保匹配、补货匹配 | **否**，SQL | 每次导入或新小票 | 0 |
| 提醒推送 | **否** | 定时 | 0 |
| （可选）自然语言问答，例如"我这个月在 Costco 花了多少" | 是，按需 | 用户主动发起 | 按次计费，可以设为高级功能 |

**好处**：成本几乎固定，不随查询次数增长；查询是毫秒级；可以离线使用；隐私数据（小票）不用发给 AI。

### 5.2 部署形态
```
┌─────────────── 云端（轻量） ───────────────┐
│ 打折数据导入任务（定时）                    │
│   AI 抽取 / 解析脚本 → 校验 → promotions DB │
│ 对外只提供：按 region/province/warehouse    │
│ 增量下发促销数据（JSON，几十 KB）            │
└──────────────────┬─────────────────────────┘
                   │ 每天同步一次（按 updated_at 增量）
┌──────────────────▼─────────────────────────┐
│ 手机本地 SQLite                              │
│  receipts / receipt_items（只在本机）        │
│  wishlist / alerts（只在本机）               │
│  promotions（只同步"我的门店"所在区域）       │
│  本地规则引擎（SQL）→ 本地通知                │
└─────────────────────────────────────────────┘
```
- 促销数据是**公共数据**，云端统一处理一次，全体用户共享。
- 小票和清单是**私有数据**，默认只存在本机，匹配也在本机做，服务器看不到用户买了什么。
- 本地推送用系统的本地通知；需要即时推送时，云端只发一个不带个人信息的"有新数据"通知，手机收到后在本地匹配。

### 5.3 技术选型（建议）
- 客户端：Flutter 或 React Native + SQLite；OCR 用 iOS Vision 或 Google ML Kit 端侧识别，识别不了的再交给云端 AI。
- 云端：一个定时任务（cron 或 serverless）+ Postgres 或 SQLite + 静态 JSON 增量文件（放 CDN）。
- 原型阶段：沿用现在的 `/workspace/costco/costco.db` 和 Python 脚本。

### 5.4 核心匹配 SQL（示意）
```sql
-- 价保：30 天内买的、现在更便宜的
SELECT ri.id AS receipt_item_id, p.id AS promotion_id,
       ri.item_number, ri.item_name, r.purchase_date, r.invoice_number,
       (ri.price - ri.instant_savings/ri.quantity) AS paid_unit,
       p.sale_price,
       ((ri.price - ri.instant_savings/ri.quantity) - p.sale_price) * ri.quantity AS refund,
       MIN(p.end_date, date(r.purchase_date, '+30 day')) AS deadline
FROM receipt_items ri
JOIN receipts r      ON r.id = ri.receipt_id
JOIN promotions p    ON p.item_number = ri.item_number AND p.status = 'active'
JOIN warehouses w    ON w.id = r.warehouse_id
WHERE (   (p.scope_type='warehouse' AND p.scope_id = w.id)
       OR (p.scope_type='province'  AND p.scope_id = w.province)
       OR (p.scope_type='region'    AND p.scope_id = w.region_group))
  AND p.start_date <= date(r.purchase_date, '+30 day')
  AND p.end_date   >= r.purchase_date
  AND date('now','localtime') <= MIN(p.end_date, date(r.purchase_date, '+30 day'))
  AND p.sale_price < (ri.price - ri.instant_savings/ri.quantity) - 0.005
  AND NOT EXISTS (SELECT 1 FROM alerts a
                  WHERE a.type='price_adjustment'
                    AND a.receipt_item_id = ri.id AND a.promotion_id = p.id);

-- 补货：最近一次购买 > 30 天、当前在打折
SELECT x.item_number, x.last_date, p.id, p.sale_price, p.end_date
FROM (SELECT item_number, MAX(r.purchase_date) AS last_date
      FROM receipt_items ri JOIN receipts r ON r.id = ri.receipt_id
      GROUP BY item_number) x
JOIN promotions p ON p.item_number = x.item_number AND p.status='active'
WHERE x.last_date < date('now','localtime','-30 day')
  AND date('now','localtime') BETWEEN p.start_date AND p.end_date;

-- 清单命中
SELECT wl.id, p.id, p.sale_price FROM wishlist wl
JOIN promotions p ON p.item_number = wl.item_number AND p.status='active'
WHERE wl.status='active'
  AND date('now','localtime') BETWEEN p.start_date AND p.end_date
  AND (wl.target_price IS NULL OR p.sale_price <= wl.target_price)
  AND (wl.min_discount IS NULL OR p.discount_amount >= wl.min_discount);
```

---

## 6. 数据模型

### 6.1 现有表（原型，保留并扩充）
- `receipts`(id, purchase_date, purchase_time, warehouse → **改为 warehouse_id**, invoice_number, receipt_total, image_path, created_at)
- `items` → **改名为 `receipt_items`**(id, receipt_id, item_number, item_name, price, quantity, instant_savings)
- `price_checks`：原型里的比价日志，迁移到 `promotions` 和 `alerts` 之后可以只作为审计日志保留

### 6.2 新增：门店与商品主数据
```sql
CREATE TABLE warehouses (
  id            TEXT PRIMARY KEY,        -- '255'
  name          TEXT,                    -- 'Port Coquitlam'
  province      TEXT NOT NULL,           -- 'BC'
  region_group  TEXT NOT NULL,           -- 'WEST'
  timezone      TEXT DEFAULT 'America/Vancouver'
);
CREATE TABLE products (
  item_number   TEXT PRIMARY KEY,        -- Costco 商品代码
  name_en       TEXT, name_zh TEXT, category TEXT,
  last_regular_price REAL, updated_at TEXT
);
```

### 6.3 新增：感兴趣清单 `wishlist`（扩充原型的同名表）
```sql
CREATE TABLE wishlist (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  item_number    TEXT,                   -- 可空：只填了名称时先模糊匹配
  item_name      TEXT NOT NULL,
  regular_price  REAL,                   -- 加入时的参考原价
  target_price   REAL,                   -- 目标价（可空）
  min_discount   REAL,                   -- 最低立减额（可空）
  scope_type     TEXT DEFAULT 'warehouse',  -- warehouse|province|region
  scope_id       TEXT,                   -- 默认为"我的门店"
  status         TEXT DEFAULT 'active',  -- active|bought|paused|expired
  source         TEXT,                   -- deal_browse|history|manual|scan
  want_by        TEXT,                   -- 期望购买截止日（可空）
  notes          TEXT,
  bought_receipt_item_id INTEGER REFERENCES receipt_items(id),
  added_at       TEXT DEFAULT (datetime('now','localtime')),
  updated_at     TEXT
);
CREATE INDEX idx_wishlist_item ON wishlist(item_number, status);
```

### 6.4 新增：打折商品表 `promotions`（deals）
```sql
CREATE TABLE promotions (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  item_number      TEXT NOT NULL,        -- 商品代码
  item_name        TEXT NOT NULL,        -- 名称
  regular_price    REAL,                 -- 原价
  sale_price       REAL NOT NULL,        -- 折后价
  discount_amount  REAL,                 -- 折扣额（立减）
  discount_pct     REAL,                 -- 折扣率（导入时计算）
  promo_type       TEXT,                 -- instant_savings|clearance|weekend|online
  limit_qty        INTEGER,              -- 限购
  province         TEXT,                 -- 省份（冗余，方便查询）
  warehouse_id     TEXT,                 -- 门店（门店级促销才填）
  scope_type       TEXT NOT NULL,        -- region|province|warehouse
  scope_id         TEXT NOT NULL,        -- 'WEST' | 'BC' | '255'
  start_date       TEXT NOT NULL,        -- 优惠开始（门店本地日期）
  end_date         TEXT NOT NULL,        -- 优惠结束（含当天）
  start_inferred   INTEGER DEFAULT 0,
  regular_inferred INTEGER DEFAULT 0,
  confidence       INTEGER DEFAULT 2,    -- 1 低 … 5 官方
  conflict         INTEGER DEFAULT 0,
  status           TEXT DEFAULT 'active',-- active|expired|retracted
  import_batch_id  INTEGER REFERENCES import_batches(id),
  first_seen_at    TEXT, last_seen_at TEXT,
  UNIQUE(item_number, scope_type, scope_id, start_date, end_date, sale_price)
);
CREATE INDEX idx_promo_match ON promotions(item_number, status, end_date);
CREATE INDEX idx_promo_scope ON promotions(scope_type, scope_id, end_date);

CREATE TABLE promotion_sources (
  promotion_id INTEGER REFERENCES promotions(id),
  source_type  TEXT,     -- official|partner|community|user_upload|ai_extract
  source_name  TEXT, source_url TEXT, captured_at TEXT,
  PRIMARY KEY (promotion_id, source_url)
);
CREATE TABLE import_batches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_at TEXT, method TEXT,             -- manual|ai|crawler|crowd
  scope_id TEXT, rows_in INTEGER, rows_new INTEGER, rows_updated INTEGER,
  rows_rejected INTEGER, notes TEXT
);
```

### 6.5 新增：提醒表 `alerts`
```sql
CREATE TABLE alerts (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  type             TEXT NOT NULL,   -- price_adjustment|repurchase|wishlist_hit|deadline_reminder
  priority         INTEGER,         -- 1 高 / 2 中 / 3 低
  item_number      TEXT NOT NULL,
  promotion_id     INTEGER REFERENCES promotions(id),
  receipt_item_id  INTEGER REFERENCES receipt_items(id),  -- 价保和补货用
  wishlist_id      INTEGER REFERENCES wishlist(id),       -- 清单命中用
  paid_price       REAL,            -- 实付单价（价保）
  sale_price       REAL,
  est_saving       REAL,            -- 可退或可省金额
  deadline         TEXT,            -- 价保截止日 / 促销结束日
  channel          TEXT,            -- push|in_app|digest|email
  status           TEXT DEFAULT 'pending', -- pending|sent|done|dismissed|expired
  next_remind_at   TEXT,            -- 下次再提醒（截止前 3 天 / 1 天）
  created_at       TEXT DEFAULT (datetime('now','localtime')),
  sent_at          TEXT, resolved_at TEXT,
  actual_refund    REAL,            -- 用户回填的实际退款
  UNIQUE(type, promotion_id, receipt_item_id, wishlist_id)
);
CREATE TABLE alert_mutes (           -- "不再提醒此商品"
  item_number TEXT, type TEXT, muted_at TEXT, PRIMARY KEY(item_number, type)
);
```

### 6.6 三库联动关系
```
receipts 1─* receipt_items *─1 products 1─* promotions *─1 warehouses
                    │                 1               (scope 覆盖)
                    │                 │
                    │                 *
                    │             wishlist
                    └──────┬──────────┘
                           ▼
                        alerts（记录"哪条购买或清单 × 哪条促销"触发了什么提醒）
```
- **连接键**：`item_number`（商品代码）。
- **空间维度**：购买门店或清单关注范围 ⊂ 促销的 scope（门店 / 省 / 区域）。
- **时间维度**：价保看 [购买日, 购买日+30] 与 [start_date, end_date] 是否重叠；补货和清单只看今天是否在促销期内。
- **状态闭环**：清单商品买入后 → `wishlist.status=bought` → 小票商品进入价保监控 → 30 天后转入补货监控。

---

## 7. MVP 路线

| 阶段 | 时间（建议） | 范围 | 打折数据方式 | 交付 |
|---|---|---|---|---|
| **M0 原型验证**（进行中） | 已开始 – 10 月底 | 1 位用户（我），1 家门店 Port Coquitlam #255 | 半自动：脚本加 AI 抽取第三方汇总，人工核对 | 现有 costco.db 加上 6 章的新表；跑通价保、补货、清单三条规则；每日扫描报告（已有 price_scan_*.json） |
| **M1 MVP** | 4–6 周 | **只做 BC 省**（Lower Mainland 的几家门店），小范围内测 20–50 人 | **人工或半自动导入**（方案 A+B），每期优惠册导入一次，周末促销补导 | 拍小票入库、感兴趣清单、打折库浏览、三类提醒、本地 SQLite、本地通知 |
| **M2 西部区域** | +1–2 个月 | BC、AB、SK、MB（共用 West 优惠册，边际成本低） | 半自动加用户众包门店价签 | 门店级清仓价、每周补货摘要、"帮你省了 $xx" 统计 |
| **M3 全国** | 视验证结果 | ON、QC、Atlantic | 谈数据授权，或在授权范围内自动化抓取 | 多区域、多语言（中、英、法）、云同步（可选） |

MVP 成功指标：价保提醒的点击率和办理率；每位用户每月平均通过价保追回的金额；清单命中后的购买转化率；打折数据的准确率（抽检 ≥98%）。

---

## 8. 待确认问题

| # | 问题 | 选项 | 当前倾向 |
|---|---|---|---|
| 1 | 先覆盖 BC 省还是全国？ | ① 只做 BC ② West 四省 ③ 全国 | ① BC 起步，因为和 AB/SK/MB 共用优惠册，扩到 ② 成本很低 |
| 2 | 打折数据先人工或半自动导入，还是直接自动爬取？ | ① 人工 ② 半自动（AI 抽取 + 人工确认） ③ 全自动爬取 | ② 半自动；③ 等合规确认或拿到授权再做 |
| 3 | 更新频率：每周还是每天？ | 每周 1–2 次 / 每天 1 次 | MVP 每周（跟优惠册和周末促销走）；门店级数据上线后改每天 |
| 4 | 数据来源能否商用？ | 官网 / 第三方网站 / 众包 / 授权 | 需要逐一确认条款，优先众包和授权 |
| 5 | 是否支持门店级价格（清仓价）？ | MVP 做 / 后做 | 后做（M2，靠众包） |
| 6 | 价保的例外与规则细节（限购、线上订单、是否要求原小票） | — | 需要去会员服务台实地确认后写进 App 提示 |
| 7 | 补货提醒的门槛：买过 1 次还是 2 次？ | 1 次 / 2 次 / 用户自选 | 默认 1 次，可在设置里改 |
| 8 | 价保最低提醒金额 | $0.50 / $1 / $2 | $1 |
| 9 | 小票数据只存本机，还是可以云同步？ | 只本机 / 可选云同步 | MVP 只存本机 |
| 10 | AI 用哪家，成本上限是多少？ | Grok 等 | 只用于每期抽取和 OCR 兜底，设定每月 token 预算 |
| 11 | 提醒渠道：推送 / 邮件 / 日历 | — | 推送 + App 内提醒中心，每周摘要可选邮件 |
| 12 | App 名称与"非官方"声明 | — | 名称避开 Costco 商标 |
