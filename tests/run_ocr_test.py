"""对两张真实样本跑识别，输出 JSON 供人工核对。用法: .venv/bin/python tests/run_ocr_test.py"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from ocr_parser import recognize
samples=[
 "/workspace/costco/receipts/2026-10-08_0952_inv205300.jpg",
 "/workspace/costco/receipts/2026-10-08_0946_inv202549.jpg",
]
for s in samples:
    out=f"/tmp/test_{Path(s).stem}"
    r=recognize(s, out)
    print("="*60); print(s)
    print(f"门店={r['store_code']} (置信{r['store_confidence']}) 日期={r['purchase_date']} (置信{r['date_confidence']}) 总计={r['total']} 小计={r['subtotal']}")
    for it in r["items"]: print(it)
