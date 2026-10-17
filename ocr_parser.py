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


# --- 名称纠错: 只改名称, 不动代码/价格 ---
_UNIT_TOKEN = re.compile(r'^\d+(\.\d+)?(KG|GR|G|ML|L|OZ|LB|X\d+|PK|CT|GRN)$', re.I)
def clean_name(name):
    """把名称里字母夹着的 0 纠为 O (P0RK->PORK, HOM0->HOMO, FL0UR->FLOUR)。
    纯数字/计量单位 token (10KG, 12X91) 不动, 避免过度纠错。"""
    out=[]
    changed=False
    for tok in re.split(r'(\s+)', name):
        if not tok or tok.isspace():
            out.append(tok); continue
        # 按 / 切开分别判断, 如 FL0UR/10KG -> FLOUR/10KG, TPD/1717599 不动数字段
        parts=[]
        for part in tok.split('/'):
            letters=sum(c.isalpha() for c in part); digits=sum(c.isdigit() for c in part)
            if part and letters>=2 and digits>=1 and letters>=digits and '0' in part and not _UNIT_TOKEN.match(part):
                new=''.join('O' if (c=='0' and i>0 and part[i-1].isalpha()) else c for i,c in enumerate(part))
                if new!=part: changed=True
                parts.append(new)
            else:
                parts.append(part)
        out.append('/'.join(parts))
    n=''.join(out)
    # FLOUR/10KG -> FLOUR 10KG (尺寸前的斜杠变空格); TPD/1717599 保持原样
    n2=re.sub(r'([A-Za-z])/(\d+(?:KG|ML|OZ|G|L)\b)', r'\1 \2', n)
    # BOUNTY12X91 -> BOUNTY 12X91 (长字母后紧跟规格数字时补空格, 纯名称更好读)
    n2=re.sub(r'([A-Za-z]{3})(\d+X\d+)', r'\1 \2', n2)
    n2=re.sub(r'([A-Za-z])(\d)(?=\s)', r'\1 \2', n2)  # CBTTA9 GRN -> CBTTA 9 GRN
    n2=n2.replace('DOZEGGS','DOZ EGGS')
    n2=re.sub(r'\s+', ' ', n2).strip()
    return n2, changed

def _deformed_price_token(tok):
    """价格被认变形: 66'9 / 669 / 9. 这类不自动猜价 (66'9 猜 6.99 还是 6.69 不确定), 只认出'这里本应是价格'。"""
    return bool(re.match(r"^(\d+'\d+|\d{3,4}|\d+\.)$", tok.strip()))

_ORPHAN_PRICE = re.compile(r"^(-?\d{1,4}\.\d{2})\s*-?\s*(?:GP|G)?$|^(\d+'\d+|\d{3,4}|\d+\.)\s*-?$")
def _orphan_price(text):
    """整行只有一个价格(或变形价格): 返回 (price或'' , 是否变形, 是否负) / None"""
    t=text.strip()
    m=re.match(r"^(-?\d{1,4}\.\d{2})\s*(-)?\s*(?:GP|G)?$", t)
    if m:
        v=float(m.group(1)); 
        if m.group(2): v=-abs(v)
        return (v, False, v<0)
    if _deformed_price_token(t.rstrip('-')):
        return ("", True, t.endswith('-'))
    return None

def _correct_price_token(tok):
    """价格小数点被认成 ' 且格式为 1-3位'2位 (如 6'99) 时按末尾两位小数纠正; 66'9/669 歧义大不在此纠正。"""
    m=re.match(r"^(\d{1,3})'(\d{2})$", tok.strip())
    return float(f"{m.group(1)}.{m.group(2)}") if m else None

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
    # 版式自纠: 日期优先取授权/交易行 (含 YYYY/MM/DD HH:MM 的那一行)
    auth_dates={}
    for l in lines:
        if re.search(r'\d{1,2}:\d{2}', l["text"]):
            for m in DATE_RE.finditer(l["text"]):
                if int(m.group(2))<=12 and int(m.group(3))<=31:
                    d=f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                    auth_dates[d]=auth_dates.get(d,0)+1
    if auth_dates:
        purchase_date=max(auth_dates, key=auth_dates.get); date_conf=max(date_conf,0.8)
    # 总计/小计
    total=None; total_conf=0.5; subtotal=None
    for l in lines:
        t=l["text"]; up=t.upper()
        p=_price(t)
        if p is None: continue
        # 版式自纠: 标签拼歪也认 (1OTAL/T0TAL/SUBTOTA...)
        lab=re.sub(r'[^A-Z]','',up.split()[0]) if up.split() else ""
        lab=lab.replace('1','T').replace('0','O')
        if lab.startswith("SUBTOTA") or "SUBTOTAL" in up: subtotal=p
        if (lab=="TOTAL" or re.search(r'\bTOTAL\b', up)) and "NUMBER" not in up and "TAX" not in up:
            total=p; total_conf=l["conf"]
        if "AMOUNT" in up and total is None:
            total=p; total_conf=l["conf"]
    # 版式自纠: 底部 TOTAL NUMBER OF ... ITEMS= 件数 (OCR 可能漏首字母/认歪)
    expected_item_count=None
    for l in lines:
        _n=re.sub(r'[^A-Z0-9]','',l["text"].upper())
        _m=re.search(r'(?:T?OTAL|TOTAL)NUMBEROF(?:PRESCANNED)?ITEMS(?:SOLD)?(\d+)', _n)
        if _m: expected_item_count=int(_m.group(1))
        _m2=re.search(r'ITEMSSOLD(\d+)', _n)
        if _m2 and expected_item_count is None: expected_item_count=int(_m2.group(1))
    # 商品行: 行首数字代码 + 名称 + 价格
    # 规则改版(2026-10-17 复测后):
    #  1) 代码与名称黏连也要拆 (199965FL0UR..., 2043841TPD/..., 366500SOFTSOAP...), 不再要求代码后有空格
    #  2) 短代码+数量黏连 (669 5 DOZ EGGS 被认成 6695) 窄规则拆分, 低置信标黄
    #  3) 价格变形 (66'9 / 669) 不猜价: 保留整行, 价格留空低置信, 绝不静默丢行
    #  4) 价格单独成行 (与商品行被拆成两行) 前后合并, 含折扣行 0000393343 /MULTIPLE + 5.00-
    #  5) 名称 0->O 纠错只作用于名称 (见 clean_name)
    # 版式自纠: 只在 START/END OF PRE-SCANNED ITEMS 之间抓商品 (两标记都认到时严格执行;
    # 只认到 END 时截到 END 为止; 都认不到时回退全页, 避免普通小票被误杀)
    def _mark(t): return re.sub(r'[^A-Z0-9]','',t.upper())
    _zs=-1; _ze=len(lines)
    for _i,_l in enumerate(lines):
        _n=_mark(_l["text"])
        if "STARTOFPRE" in _n or "STARTOFITEMS" in _n: _zs=_i
        if ("ENDOFPRE" in _n or "ENDOFITEMS" in _n) and _ze==len(lines): _ze=_i
    item_lines=lines[_zs+1:_ze] if _zs>=0 else lines[:_ze]
    if not item_lines: item_lines=lines
    items=[]
    skip_words=("TOTAL","SUBTOTAL","TAX","AMOUNT","CHANGE","MASTERCARD","REFERENCE","AUTH","INVOICE","MEMBER")
    pending=None  # (price, deformed, conf, age) 来自上一行的孤儿价格
    for l in item_lines:
        t=l["text"].strip()
        if not t: continue
        # --- 孤儿价格行: 先填给上一条缺价商品, 否则暂存给下一条 ---
        op=_orphan_price(t)
        if op is not None and not any(w in t.upper() for w in ("TOTAL","SUBTOTAL","TAX")):
            filled=False
            if items and items[-1].get("price")=="" :
                items[-1]["price"]=op[0]
                items[-1]["confidence"]=min(items[-1]["confidence"], 0.6)
                if op[2] and isinstance(op[0], (int,float)): items[-1]["price"]=-abs(op[0]); items[-1]["is_discount"]=True
                filled=True
            if not filled:
                pending=(op[0], op[1], l["conf"], 0)
            continue
        if pending is not None:
            pending=(pending[0], pending[1], pending[2], pending[3]+1)
            if pending[3]>2: pending=None
        if re.search(r'ENVIRO|EPOSIT|DEPOSIT', t.upper()):
            pending=None; continue  # 费用行(无代码)已知不收录, 且其孤儿价不能串给下一商品
        # --- 拆代码+名称 ---
        code=None; rest=None; qty=1; split_conf_cap=1.0; special=""
        m_doz=re.match(r'^(\d{3})([1-9])\s+([A-Za-z].*(?:DOZ|EGGS).+)$', t, re.I)
        m_sp=re.match(r'^(\d{3,12})\s+(.+)$', t)
        m_sym=re.match(r'^(\d{3,12})[\*%#]+([A-Za-z].+)$', t)
        m_gl=re.match(r'^(\d{3,12})([A-Za-z/].+)$', t)
        if m_doz:
            # 5 是名称里的 "5 DOZ" 不是购买数量: 代码=669, 数量仍=1, 名称补回 "5 DOZ EGGS"
            code, qty, rest = m_doz.group(1), 1, m_doz.group(2)+" "+m_doz.group(3)
            split_conf_cap=0.5; special="doz"
        elif m_sp:
            code, rest = m_sp.group(1), m_sp.group(2)
        elif m_sym:
            code, rest = m_sym.group(1), m_sym.group(2); split_conf_cap=0.8; special="symbol"
        elif m_gl:
            code, rest = m_gl.group(1), m_gl.group(2)
            split_conf_cap=0.8; special="glued"
        else:
            # 行内嵌商品模式: ... 1694477 PEROGIES 16.99 (含黏连回退)
            m2=re.search(r'(\d{3,12})\s*([A-Za-z/][A-Za-z0-9 /\'-]*?)\s+(\d{1,4}\.\d{2})', t)
            if m2 and "MEMBER" not in t.upper():
                nm, changed = clean_name(m2.group(2).strip())
                items.append({"item_code":m2.group(1),"item_name":nm,"price":float(m2.group(3)),"quantity":1,"confidence":min(l["conf"],0.6),"is_discount":False})
            continue
        if any(s in t.upper() for s in skip_words) and not re.match(r'^\d{3,12}\s*[A-Z/]', t):
            continue
        if code.startswith("000000") or rest.strip().upper().startswith("E800") or re.search(r'\d{2}:\d{2}', rest):
            continue  # 支付授权码/时间行不是商品(样本实测误报)
        if re.search(r'TTAWA|COQUITLAM|\bST\.?\b|STREET|\bAVE\b|V3B|V\d[A-Z]\d', rest.upper()) or '#' in rest:
            continue  # 地址行 (2370 Ottawa St. #255) 不是商品, 短代码规则误抓后在此拦下
        if len(code)>10 and not code.startswith("0000"):
            continue  # 超长数字多半是会员/发票号误入
        conf=min(l["conf"], split_conf_cap)
        # --- 价格: 正常价优先; 行尾变形价则留空保留行; 都没有则用孤儿价/留空 ---
        prices=re.findall(r'-?\d{1,4}\.\d{2}', rest)
        price=None; deformed=False
        _corr=None
        if not prices:
            _toks0=rest.strip().split()
            if _toks0: _corr=_correct_price_token(_toks0[-1].rstrip('-'))
            if _corr is not None:
                prices=[str(_corr)]; conf=min(conf,0.6)
                rest=' '.join(_toks0[:-1])
        if prices:
            price=float(prices[0])  # 取第一个价格, 避免下一行折扣价被并进来时取错
            name=re.sub(r'-?\d{1,4}\.\d{2}\s*-?\s*(GP|G)?\b.*$','',rest).strip(" -")
        else:
            toks=rest.strip().split()
            if toks and _deformed_price_token(toks[-1].rstrip('-')) and len(toks)>=2:
                deformed=True
                name=' '.join(toks[:-1]).strip()
            else:
                name=re.sub(r'\s+\d{3}\s*$','',rest).strip()
            if pending is not None and not deformed:
                price=pending[0]; deformed=deformed or pending[1]
                conf=min(conf, 0.6)
                pending=None
            else:
                if deformed: pending=None  # 本行自带变形价, 孤儿价多半是费用行, 不能串入
                price=""
            if price=="":
                conf=min(conf, 0.4)
        name=re.sub(r'^[*%#]+','',name).rstrip('*').strip()
        name=re.sub(r'^/','折扣 ',name).strip()
        # --- 折扣判定: 000039* 代码 / TPD 或 / 开头 / 价格带负号尾巴 ---
        is_disc = code.startswith("000039") or bool(re.match(r'^(TPD/|/|折扣\s)', name.upper())) or bool(re.search(r'\d\.\d{2}\s*-\s*(GP)?\s*$', t))
        if isinstance(price,(int,float)) and is_disc:
            price=-abs(price)
        if isinstance(price,(int,float)) and re.search(r'\d\.\d{2}\s*-\s*(GP)?\s*$', t) and price>0:
            price=-price
        nm, name_changed = clean_name(name)
        if name_changed: conf=min(conf, 0.84)
        if len(nm)<2: conf=min(conf,0.5)
        _df=""
        _md=re.search(r'/(\d{3,12})\b', name)
        if is_disc and _md: _df=_md.group(1)
        elif is_disc and name.upper().startswith("TPD"): _df=""
        items.append({"item_code":code,"item_name":nm or "（名称没看清，请填写）","price":price,"quantity":qty,"confidence":conf,"is_discount":bool(is_disc and isinstance(price,(int,float)) and price<0 or code.startswith("000039")),"discount_for":_df,"discount":"","discount_code":""})
    # 版式自纠: 负金额/折扣行挂到紧邻的上一件商品, 不再当独立商品
    # (折扣无上一件时保留独立行, 宁可标出也不丢数据)
    merged=[]
    for it in items:
        is_disc_row = it.get("is_discount") and isinstance(it.get("price"),(int,float)) and it["price"]<0
        if is_disc_row and merged and not merged[-1].get("is_discount"):
            prev=merged[-1]
            if prev.get("discount")=="":
                prev["discount"]=it["price"]; prev["discount_code"]=it["item_code"]
                prev["discount_for"]=it.get("discount_for") or prev["item_code"]
            else:
                # 同一件多行折扣: 累加金额, 代码拼接保留
                prev["discount"]=round(float(prev["discount"])+it["price"],2)
                prev["discount_code"]=(str(prev.get("discount_code",""))+"+"+it["item_code"]).strip("+")
            prev["confidence"]=min(prev["confidence"], it["confidence"])
        else:
            merged.append(it)
    items=merged
    product_count=sum(1 for it in items if not it.get("is_discount"))
    count_mismatch = expected_item_count is not None and product_count!=expected_item_count
    # 无价格的费用行 ENVIRO FEE / DEPOSIT 单独一行时，其价格常在同行已包含；此处不强行造
    return {"store_code":store,"store_confidence":store_conf,"purchase_date":purchase_date,"date_confidence":date_conf if purchase_date else 0.3,
            "total":total,"total_confidence":total_conf if total is not None else 0.3,"subtotal":subtotal,"items":items,"raw_lines":lines,"expected_item_count":expected_item_count,"product_count":product_count,"count_mismatch":count_mismatch}

def recognize(src, work_dir):
    processed=os.path.join(work_dir,"processed.jpg")
    preprocess(src, processed)
    lines=ocr_lines(processed)
    parsed=parse_receipt(lines)
    parsed["processed_image"]=processed
    return parsed
