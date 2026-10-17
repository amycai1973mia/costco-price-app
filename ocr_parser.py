"""本地 OCR + Costco 小票解析。主引擎 RapidOCR(onnx, 本地), 备用 Tesseract。"""
import cv2, numpy as np, re, os, json
from pathlib import Path

_reader = None
def _rapid():
    global _reader
    if _reader is None:
        from rapidocr_onnxruntime import RapidOCR
        _reader = RapidOCR()
    return _reader

def preprocess(src, out_path):
    """自动裁剪小票区域 -> 灰度 -> CLAHE 增强。返回处理后图片路径。"""
    img = cv2.imread(str(src))
    if img is None:
        raise ValueError("图片读不了，请重新拍照")
    h, w = img.shape[:2]
    gray0 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray0, (9,9), 0)
    _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_OTSU)
    cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    x,y,ww,hh = 0,0,w,h
    if cnts:
        c = max(cnts, key=cv2.contourArea)
        bx,by,bw,bh = cv2.boundingRect(c)
        if bw < 0.65*w and bw > 0.2*w:  # 可信的小票轮廓
            x,y,ww,hh = bx,by,bw,bh
        else:  # 轮廓过大(背景干扰)时用中间区域兜底(样本实测位置)
            x,y,ww,hh = int(w*0.26), 0, int(w*0.55), h
    pad_x, pad_y = 60, 20
    x=max(0,x-pad_x); y=max(0,y-pad_y); ww=min(w-x, ww+2*pad_x); hh=min(h-y, hh+2*pad_y)
    crop = img[y:y+hh, x:x+ww]
    scale = 1200 / crop.shape[1]
    crop = cv2.resize(crop, (1200, int(crop.shape[0]*scale)))
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    g = cv2.createCLAHE(clipLimit=2.0).apply(g)
    # 轻微锐化
    g = cv2.addWeighted(g, 1.5, cv2.GaussianBlur(g,(0,0),3), -0.5, 0)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), g)
    return str(out_path)

def ocr_lines(image_path):
    """返回按行分组的 [{'text':str,'conf':float,'y':int}]"""
    eng = _rapid()
    result, _ = eng(str(image_path))
    tokens=[]
    if result:
        for box, text, conf in result:
            try: c=float(conf)
            except: c=0.5
            tokens.append({"x": float(box[0][0]), "y": float(box[0][1]), "text": str(text).strip(), "conf": c})
    if not tokens:  # 备用 tesseract
        return _tesseract_lines(image_path)
    tokens.sort(key=lambda t:(t["y"], t["x"]))
    lines=[]
    for t in tokens:
        # 锚点固定(不漂移)，容差18px，避免相邻两行商品被并成一行(样本实测教训)
        if lines and abs(t["y"]-lines[-1]["y"]) <= 18:
            lines[-1]["tokens"].append(t)
        else:
            lines.append({"y": t["y"], "tokens":[t]})
    out=[]
    for ln in lines:
        toks=sorted(ln["tokens"], key=lambda t:t["x"])
        out.append({"text":" ".join(t["text"] for t in toks), "conf": round(min(t["conf"] for t in toks),3), "y": int(ln["y"])})
    return out

def _tesseract_lines(image_path):
    try:
        import pytesseract
        txt = pytesseract.image_to_string(cv2.imread(str(image_path)), config="--psm 6")
        return [{"text":l, "conf":0.5, "y":i*30} for i,l in enumerate(txt.splitlines()) if l.strip()]
    except Exception:
        return []

PRICE_RE = re.compile(r'(-?\d{1,4}\.\d{2})\s*(?:GP|G)?\s*$')
DATE_RE = re.compile(r'(20\d{2})[/\-](\d{1,2})[/\-](\d{1,2})')

def _price(s):
    m = re.findall(r'-?\d{1,4}\.\d{2}', s)
    return float(m[-1]) if m else None

def parse_receipt(lines):
    full = "\n".join(l["text"] for l in lines)
    # 门店代码: 优先 #255，其次 Whse:255，两者一致高置信
    store, store_conf = "", 0.5
    m1 = re.search(r'#\s*(\d{3})\b', full)
    m2 = re.search(r'Whse[:\s]*(\d{3})', full, re.I)
    if m1 and m2 and m1.group(1)==m2.group(1):
        store, store_conf = m1.group(1), 0.98
    elif m2:
        store, store_conf = m2.group(1), 0.9
    elif m1:
        store, store_conf = m1.group(1), 0.85
    # 日期: 取出现次数最多的日期
    dates={}
    date_conf=0.5
    for l in lines:
        for m in DATE_RE.finditer(l["text"]):
            d=f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            # 过滤明显错误如月份>12
            if int(m.group(2))>12 or int(m.group(3))>31: continue
            dates[d]=dates.get(d,0)+1
            date_conf=max(date_conf, l["conf"])
    purchase_date = max(dates, key=dates.get) if dates else ""
    if dates and max(dates.values())>=2: date_conf=max(date_conf,0.95)
    # 总计/小计
    total=None; total_conf=0.5; subtotal=None
    for l in lines:
        t=l["text"]; up=t.upper()
        p=_price(t)
        if p is None: continue
        if "SUBTOTAL" in up: subtotal=p
        if re.search(r'\bTOTAL\b', up) and "NUMBER" not in up and "TAX" not in up:
            total=p; total_conf=l["conf"]
        if "AMOUNT" in up and total is None:
            total=p; total_conf=l["conf"]
    # 商品行: 行首数字代码 + 名称 + 价格；也兼容商品代码被并到上一行(如会员行)的情况
    items=[]
    skip_words=("TOTAL","SUBTOTAL","TAX","AMOUNT","CHANGE","MASTERCARD","REFERENCE","AUTH","INVOICE","MEMBER")
    for l in lines:
        t=l["text"].strip()
        m=re.match(r'^(\d{5,12})\s+(.+)$', t)
        if not m:
            # 行内嵌商品模式: ... 1694477 PEROGIES 16.99
            m2=re.search(r'(\d{7})\s+([A-Za-z0-9 ]+?)\s+(\d{1,4}\.\d{2})', t)
            if m2 and "MEMBER" not in t.upper().split(m2.group(1))[0][-10:]:
                pass
            if m2:
                items.append({"item_code":m2.group(1),"item_name":m2.group(2).strip(),"price":float(m2.group(3)),"quantity":1,"confidence":min(l["conf"],0.6),"is_discount":False})
            continue
        if any(s in t.upper() for s in skip_words) and not re.match(r'^\d{5,12}\s+[A-Z]', t):
            continue
        code, rest=m.group(1), m.group(2)
        if code.startswith("000000") or rest.strip().upper().startswith("E800") or re.search(r'\d{2}:\d{2}', rest):
            continue  # 支付授权码/时间行不是商品(样本实测误报)
        prices=re.findall(r'-?\d{1,4}\.\d{2}', rest)
        if not prices:
            # 有代码和名称但价格没识别出来(如 9.69 被识别成 696): 仍列出, 价格留空低置信让用户填
            name=re.sub(r'\s+\d{3}\s*$','',rest).strip()
            items.append({"item_code":code,"item_name":name,"price":"","quantity":1,"confidence":0.4,"is_discount":False})
            continue
        p=float(prices[0])  # 取第一个价格, 避免下一行折扣价被并进来时取错
        name=re.sub(r'-?\d{1,4}\.\d{2}\s*-?\s*(GP|G)?\b.*$','',rest).strip(" -")
        name=re.sub(r'^/','折扣 ',name).strip()
        if re.search(r'\d\.\d{2}\s*-\s*(GP)?\s*$', t) and p>0: p=-p
        if code.startswith("000039"): p=-abs(p)
        conf=l["conf"]
        if len(name)<2: conf=min(conf,0.5)
        items.append({"item_code":code,"item_name":name or "（名称没看清，请填写）","price":p,"quantity":1,"confidence":conf,"is_discount":bool(code.startswith("000039") or p<0)})
    # 无价格的费用行 ENVIRO FEE / DEPOSIT 单独一行时，其价格常在同行已包含；此处不强行造
    return {"store_code":store,"store_confidence":store_conf,"purchase_date":purchase_date,"date_confidence":date_conf if purchase_date else 0.3,
            "total":total,"total_confidence":total_conf if total is not None else 0.3,"subtotal":subtotal,"items":items,"raw_lines":lines}

def recognize(src, work_dir):
    processed=os.path.join(work_dir,"processed.jpg")
    preprocess(src, processed)
    lines=ocr_lines(processed)
    parsed=parse_receipt(lines)
    parsed["processed_image"]=processed
    return parsed
