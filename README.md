# Costco 小票助手 — 第一步 MVP 原型

简体中文、大字大按钮、三步完成：**拍照上传 → 核对修改 → 确认导入**。专为不熟悉手机操作的用户设计，步骤尽量少。

## 手机网页试用（GitHub Pages）

打开：**https://amycai1973mia.github.io/costco-price-app/**

纯前端试用版（`docs/`）：在手机浏览器里用 Tesseract.js 本地识别，照片不上传服务器；能看门店/日期/总计/商品/折扣/件数核对，带 ⚠ 标记。本版只试识别，不改、不导入数据库。拍的时候请让小票占满画面、拍正、光线亮。网页版 OCR 弱于本地 RapidOCR 版，效果以人工核对为准。

## 怎么启动

在本项目文件夹里运行（一台电脑上打开）：

```bash
cd /workspace/costco-price-app
./run.sh
```

然后在浏览器打开：**http://127.0.0.1:5003**

> 首次在新电脑上用，需要先装环境：`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`，并安装 Tesseract 作备用 OCR（`sudo apt install tesseract-ocr`）。本机已经装好，可直接 `./run.sh`。

## 怎么用（三步）

1. **第 1 步**：点红色大按钮「拍小票 / 选照片」，选一张 Costco 小票照片，等十几秒识别。
2. **第 2 步**：看确认页。对照小票照片核对商店代码、日期、总计和每一行商品。黄色底色 = 识别没把握，请重点看。错了直接点格子改；不要的行勾选「不要这一行」。
3. **第 3 步**：点绿色大按钮「确认无误，导入」。只有点了这一步，数据才存进数据库；不点就不会存。

点首页「查看已导入的小票」可以看已经存好的记录。

## 技术说明

- **界面/后端**：Python + Flask，单文件后端 `app.py`，模板在 `templates/`，大字体样式在 `static/style.css`。
- **数据库**：SQLite 文件 `data/costco.db`，两张表：
  - `receipts`：小票（商店代码、购买日期、总计、图片名、导入时间）
  - `receipt_items`：商品（商品代码、名称、价格、数量，关联小票）
- **识别（全本地，不用付费 API、不用 API key）**：
  - 先自动找小票位置并裁剪、放大、灰度 + 对比度增强、锐化（OpenCV，见 `ocr_parser.py` 的 `preprocess`）。
  - 主 OCR：RapidOCR（onnxruntime，本地模型）。实测它比 Tesseract 更适合这两张样本，所以作主引擎。
  - 备用 OCR：Tesseract（装了才启用，`pytesseract` 调用）。
  - 解析规则（正则）：商店代码取 `#255` 并与 `Whse:255` 互相印证；日期取出现最多的 `YYYY/MM/DD`；商品行取行首数字代码 + 名称 + 第一个价格，`000039…` 开头判为折扣行记负数；有代码无价格的行不丢弃，价格留空并标低置信，提醒用户照小票填写。
  - **低置信提醒**：每个字段/每行都带置信度，低于 0.85 在确认页用黄底 +「⚠ 请重点核对」标出，这是保证最终准确的关键——机器先挑出没把握的地方，人只重点看这些。
- **可选第二引擎 PaddleOCR（双保险）**：数字实测比 Rapid 略准（见 `OCR方案对比.md`）。装法：`.venv/bin/pip install -r requirements-paddle.txt`（体积大，可不装；没装自动只用 Rapid）。 Rapid 结果缺价格/总计或件数对不上时才会跑 Paddle 补价互证，确认页会显示引擎来源；设 `COSTCO_DISABLE_PADDLE=1` 可关。
- **测试脚本**：`.venv/bin/python tests/run_ocr_test.py` 可对两张真实样本重跑识别并打印结果。

## 已知不足（实测，见项目根目录 TEST_RESULTS.md）

- 商品名个别字母会看错（如 PEROGIES → PEX0GIES、字母 O 看成数字 0），需用户在确认页改。
- 个别价格没识别出（如 ORGANIC HOMO 的 9.69 被看成 696、PORK LOIN 的 24.34 与名称分行），已用「价格留空 + 黄色警告」兜底，但仍需人工填。
- 无商品代码的费用行（ENVIRO FEE 0.07、DEPOSIT 0.10）目前不会自动入商品清单。
- 小票拍得太斜、反光、字被手写涂改遮住时准确率会下降；请尽量放平、拍正。
- 目前是本机原型：没有登录功能，没有手机 App 包装，同一台电脑浏览器打开使用。

## 文件一览

| 文件 | 作用 |
|---|---|
| `app.py` | Flask 后端：上传、确认、导入、记录列表 |
| `ocr_parser.py` | 图片预处理 + OCR + 小票字段解析 |
| `templates/` | 首页 / 确认页 / 已导入列表（简体中文大字界面） |
| `data/costco.db` | SQLite 数据库（确认后才写入） |
| `uploads/` | 用户上传的小票照片 |
| `tests/run_ocr_test.py` | 两张真实样本的识别复测脚本 |
