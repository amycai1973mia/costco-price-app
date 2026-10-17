"""三引擎同批样本对比: RapidOCR / PaddleOCR(PP-OCRv5 mobile) / Tesseract.js(另跑Node)
用法(项目venv): .venv/bin/python tests/compare_engines.py rapid
用法(paddle venv): /tmp/paddle-venv/bin/python tests/compare_engines.py paddle
都用同一预处理 ocr_parser.preprocess + 同一 parse_receipt, 输出 /tmp/ocr_compare/<engine>.json
"""
import sys, json, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ocr_parser import preprocess, parse_receipt

SAMPLES=[
 ("S1_1item","/workspace/costco/receipts/2026-10-08_0952_inv205300.jpg"),
 ("S2_11item","/workspace/costco/receipts/2026-10-08_0946_inv202549.jpg"),
 ("S3_8item","/home/box/agent-data/agents/83703a29-e0bb-4518-9c8a-29cb79892d9e/attachments/d0c53bd2345660cb967e74057dcf2a493e33211df12c2f4404055a146ae436d0.jpg"),
 ("S4_13item","/home/box/agent-data/agents/83703a29-e0bb-4518-9c8a-29cb79892d9e/attachments/080df8a01428087498e3457b301de52960e62cc61aaa0938b8a19563f5d91614.jpg"),
 ("S5_5item","/home/box/agent-data/agents/83703a29-e0bb-4518-9c8a-29cb79892d9e/attachments/0088f27aa2d1795da0d2c1bffb572635bd319679870019f121feae596171c2e9.jpg"),
]
TRUTH={
 "S1_1item":{"codes":["1694477"],"prices":[16.99],"date":"2026-10-08","total":16.99,"exp":1},
 "S2_11item":{"codes":["1412124","4335823","1981124","1990653","2334477","2392786","1983952","1154953","695035","628368","31098"],"prices":[11.99,18.99,12.97,19.99,29.99,18.49,29.99,15.99,9.69,15.99,24.34],"date":"2026-10-08","total":193.02,"exp":11},
 "S3_8item":{"codes":["5220987","695035","30859","1717599","1717599","669","21354","199965"],"prices":[9.49,9.69,6.99,32.49,32.49,19.99,29.85,9.49],"date":"2026-10-03","total":138.89,"exp":8},
 "S4_13item":{"codes":["1717599","1717599","366500","199965","22389","28849","695035","25771","7199639","30859","2392786","879639","1774521"],"prices":[32.49,32.49,14.99,9.79,19.81,12.81,9.69,3.79,24.99,6.99,17.99,6.99,11.49],"date":None,"total":None,"exp":13},
 "S5_5item":{"codes":["326031","6262016","695035","30859","31574"],"prices":[16.49,23.99,9.49,6.99,33.78],"date":"2026-09-08","total":93.79,"exp":5},
}
def score(parsed, truth):
    codes=[it['item_code'] for it in parsed['items'] if not it.get('is_discount')]
    # 价格按代码对应真值比 (同代码多件逐个)
    from collections import Counter
    tc=Counter(truth['codes']); gotc=Counter(codes)
    code_ok=sum(min(tc[k],gotc[k]) for k in tc)
    # price: 按顺序与真值同代码配对粗计: 建真值 code->prices list
    truth_map={}
    for c,p in zip(truth['codes'],truth['prices']): truth_map.setdefault(c,[]).append(p)
    got_map={}
    for it in parsed['items']:
        if not it.get('is_discount'): got_map.setdefault(it['item_code'],[]).append(it['price'])
    price_ok=0
    for c,ps in truth_map.items():
        gps=got_map.get(c,[])
        for p in ps:
            if p in gps: price_ok+=1; gps.remove(p)
    return {"got":parsed['product_count'],"exp":truth['exp'],"code_ok":code_ok,"price_ok":price_ok,
            "date_ok": (truth['date'] is None or parsed['purchase_date']==truth['date']),
            "total_ok": (truth['total'] is None or parsed['total']==truth['total']),
            "store":parsed['store_code'],"date":parsed['purchase_date'],"total":parsed['total'],
            "items":[{"code":it['item_code'],"name":it['item_name'],"price":it['price']} for it in parsed['items'] if not it.get('is_discount')]}

def rapid_lines(path):
    from ocr_parser import ocr_lines
    return ocr_lines(path)

_paddle=None
def paddle_lines(path):
    global _paddle
    if _paddle is None:
        from paddleocr import PaddleOCR
        _paddle=PaddleOCR(lang='en', text_detection_model_name='PP-OCRv5_mobile_det', text_recognition_model_name='en_PP-OCRv5_mobile_rec', use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False, enable_mkldnn=False)
    res=_paddle.predict(path)
    toks=[]
    for r in res:
        texts=r['rec_texts']; scores=r['rec_scores']; polys=r['rec_polys']
        for txt,sc,poly in zip(texts,scores,polys):
            xs=[float(p[0]) for p in poly]; ys=[float(p[1]) for p in poly]
            toks.append({"x":min(xs),"y":min(ys),"yc":sum(ys)/len(ys),"text":str(txt).strip(),"conf":float(sc)})
    toks.sort(key=lambda t:(t['yc'],t['x']))
    lines=[]
    for t in toks:
        if lines and abs(t['yc']-lines[-1]['yc'])<=30:
            lines[-1]['toks'].append(t)
        else:
            lines.append({"yc":t['yc'],"toks":[t]})
    out=[]
    for ln in lines:
        tk=sorted(ln['toks'],key=lambda x:x['x'])
        out.append({"text":" ".join(x['text'] for x in tk),"conf":round(min(x['conf'] for x in tk),3),"y":int(ln['yc'])})
    return out

def main():
    engine=sys.argv[1]
    results={}
    for sid,path in SAMPLES:
        work=f"/tmp/ocr_compare/{sid}"
        os.makedirs(work,exist_ok=True)
        proc=os.path.join(work,"processed.jpg")
        if not os.path.exists(proc):
            preprocess(path, proc)
        lines= rapid_lines(proc) if engine=='rapid' else paddle_lines(proc)
        parsed=parse_receipt(lines)
        truth=TRUTH[sid]
        sc=score(parsed,truth)
        results[sid]={"score":sc,"lines":lines}
        print(sid, engine, sc)
    json.dump(results, open(f"/tmp/ocr_compare/{engine}.json","w"), ensure_ascii=False, indent=1)
if __name__=="__main__": main()
