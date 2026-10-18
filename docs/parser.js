// Costco 小票固定版式解析（从 ocr_parser.py 移植，纯前端本地运行）
// 规则依据 RECEIPT_FORMAT_RULES.md：商品区 START/END、行首数字代码、名称0纠O、
// 行尾两位小数价格、负数折扣挂靠上一件、TOTAL NUMBER 件数核对、门店#号、授权行日期、SUBTOTAL/TOTAL标签。
'use strict';
const DATE_RE = /(20\d{2})[/\-](\d{1,2})[/\-](\d{1,2})/g;
function _price(s){ const m=[...s.matchAll(/-?\d{1,4}\.\d{2}/g)]; return m.length? parseFloat(m[m.length-1][0]) : null; }
const UNIT_TOKEN = /^\d+(\.\d+)?(KG|GR|G|ML|L|OZ|LB|X\d+|PK|CT|GRN)$/i;
function cleanName(name){
  let changed=false; const out=[];
  for(const tok of name.split(/(\s+)/)){
    if(!tok||/^\s+$/.test(tok)){ out.push(tok); continue; }
    const parts=[];
    for(const part0 of tok.split('/')){
      const part=part0;
      const letters=[...part].filter(c=>/[A-Za-z]/.test(c)).length;
      const digits=[...part].filter(c=>/\d/.test(c)).length;
      if(part && letters>=2 && digits>=1 && letters>=digits && part.includes('0') && !UNIT_TOKEN.test(part)){
        let np=''; for(let i=0;i<part.length;i++){ np += (part[i]==='0' && i>0 && /[A-Za-z]/.test(part[i-1])) ? 'O' : part[i]; }
        if(np!==part) changed=true; parts.push(np);
      } else parts.push(part);
    }
    out.push(parts.join('/'));
  }
  let n=out.join('');
  n=n.replace(/([A-Za-z])\/(\d+(?:KG|ML|OZ|G|L)\b)/g,'$1 $2');
  n=n.replace(/([A-Za-z]{3})(\d+X\d+)/g,'$1 $2');
  n=n.replace(/([A-Za-z])(\d)(?=\s)/g,'$1 $2');
  n=n.replace(/DOZEGGS/g,'DOZ EGGS');
  n=n.replace(/\s+/g,' ').trim();
  return [n,changed];
}

// --- 名称模糊容错（长期原则：关键数字优先，名称允许错1-2字母）---
// 已知商品词来自历史小票沉淀；后续可由确认入库的商品库扩充。
const KNOWN_PRODUCTS=['CHICKEN STRP','KS BATH','ORGANIC HOMO','CBTTA 9 GRN','PORK BELLY','PORK LOIN','BOUNTY 12X91','FLOUR 10KG','SOFTSOAP','QUICK OATS','PEROGIES','MINI CUKES','GREEK PLAIN','SHALLOTS','MACKEREL','LISTERINE UC','BENCH PANT','TH BELT','TAHARI LEG','PIZZA SINGLE','BUFFALO','MARBLE CHEDD','DOZ EGGS'];
function _lev(a,b){ const m=a.length,n=b.length; if(!m) return n; if(!n) return m; let prev=Array.from({length:n+1},(_,i)=>i); for(let i=1;i<=m;i++){ let cur=[i]; for(let j=1;j<=n;j++){ cur[j]=Math.min(prev[j]+1,cur[j-1]+1,prev[j-1]+(a[i-1]===b[j-1]?0:1)); } prev=cur; } return prev[n]; }
function _sim(a,b){ if(!a||!b) return 0; const d=_lev(a,b); return 1-d/Math.max(a.length,b.length); }
function fuzzyCorrectName(raw){
  let cleaned=String(raw||'').toUpperCase().replace(/[\*\%\#@]+/g,' ').replace(/[^A-Z0-9 ]+/g,' ').replace(/\s+/g,' ').trim();
  if(!cleaned) return {name:cleaned,corrected:false,similarity:0,from:raw};
  let best='',bestSim=0;
  for(const k of KNOWN_PRODUCTS){ const s=Math.max(_sim(cleaned,k), cleaned.length>3?_sim(cleaned.slice(1),k):0, _sim(cleaned.replace(/ /g,''),k.replace(/ /g,''))); if(s>bestSim){bestSim=s;best=k;} // 残缺前缀: CHICKEN ST -> CHICKEN STRP
    if((k.startsWith(cleaned)||cleaned.startsWith(k)) && Math.abs(k.length-cleaned.length)<=4) { if(0.86>bestSim){best=k;bestSim=0.86;} } }
  if(best && bestSim>=0.72 && cleaned!==best) return {name:best,corrected:true,similarity:Math.round(bestSim*100)/100,from:cleaned};
  return {name:cleaned,corrected:false,similarity:Math.round(bestSim*100)/100,from:cleaned};
}
function _deformedPriceToken(tok){ return /^(\d+'\d+|\d{3,4}|\d+\.)$/.test(tok.trim()); }
function _orphanPrice(text){
  const t=text.trim();
  const m=t.match(/^(-?\d{1,4}\.\d{2})\s*(-)?\s*(?:GP|G)?$/);
  if(m){ let v=parseFloat(m[1]); if(m[2]) v=-Math.abs(v); return [v,false,v<0]; }
  const tt=t.replace(/-$/,'');
  if(_deformedPriceToken(tt)) return ['',true,t.endsWith('-')];
  return null;
}
function _correctPriceToken(tok){
  const m=tok.trim().match(/^(\d{1,3})'(\d{2})$/);
  return m? parseFloat(m[1]+'.'+m[2]) : null;
}
function parseReceipt(inputLines){
  // Tesseract 常把小数点认成逗号或带空格: 29,99 / 4 .00 -> 29.99 / 4.00 (仅用于解析, 不改原始文字)
  const lines=inputLines.map(l=>({...l,text:String(l.text).replace(/(\d)\s+\.(\d{2})/g,'$1.$2').replace(/(\d),(\d{2})\b/g,'$1.$2')}));
  const full=lines.map(l=>l.text).join('\n');
  let store='', storeConf=0.5;
  const m1=full.match(/#\s*(\d{3})\b/), m2=full.match(/Whse[:\s]*(\d{3})/i);
  if(m1&&m2&&m1[1]===m2[1]){store=m1[1];storeConf=0.98;} else if(m2){store=m2[1];storeConf=0.9;} else if(m1){store=m1[1];storeConf=0.85;}
  const dates={}; let dateConf=0.5;
  for(const l of lines){ for(const m of l.text.matchAll(DATE_RE)){ if(+m[2]>12||+m[3]>31) continue; const d=`${m[1]}-${String(+m[2]).padStart(2,'0')}-${String(+m[3]).padStart(2,'0')}`; dates[d]=(dates[d]||0)+1; dateConf=Math.max(dateConf,l.conf??0.5); } }
  let purchaseDate = Object.keys(dates).length? Object.entries(dates).sort((a,b)=>b[1]-a[1])[0][0] : '';
  if(dates && Math.max(0,...Object.values(dates))>=2) dateConf=Math.max(dateConf,0.95);
  const auth={};
  for(const l of lines){ if(/\d{1,2}:\d{2}/.test(l.text)){ for(const m of l.text.matchAll(DATE_RE)){ if(+m[2]<=12&&+m[3]<=31){ const d=`${m[1]}-${String(+m[2]).padStart(2,'0')}-${String(+m[3]).padStart(2,'0')}`; auth[d]=(auth[d]||0)+1; } } } }
  if(Object.keys(auth).length){ purchaseDate=Object.entries(auth).sort((a,b)=>b[1]-a[1])[0][0]; dateConf=Math.max(dateConf,0.8); }
  let total=null,totalConf=0.5,subtotal=null;
  // 费用类：ENVIRO FEE / DEPOSIT 无商品代码、不算商品件数。
  // 2026-10-17（本轮）改为按小票顺序挂到所属商品下面，不再全局去重后单独成列：
  // 解析商品区时，费用行紧跟哪件商品就挂到哪件（见下方 attachFee）；此处先只取税。
  let tax=null, taxConf=0.5;
  for(const l of lines){
    const t=l.text, up=t.toUpperCase(), p=_price(t);
    if(/\bTAX\b/.test(up) && !up.includes('NUMBER') && p!==null){ tax=p; taxConf=l.conf??0.5; }
  }
  for(const l of lines){ const t=l.text, up=t.toUpperCase(), p=_price(t); if(p===null) continue;
    let lab=up.split(/\s+/)[0]? up.split(/\s+/)[0].replace(/[^A-Z]/g,'') : ''; lab=lab.replace(/1/g,'T').replace(/0/g,'O');
    if(lab.startsWith('SUBTOTA')||up.includes('SUBTOTAL')) subtotal=p;
    if((lab==='TOTAL'||/\bTOTAL\b/.test(up))&&!up.includes('NUMBER')&&!up.includes('TAX')){ total=p; totalConf=l.conf??0.5; }
    if(up.includes('AMOUNT')&&total===null){ total=p; totalConf=l.conf??0.5; }
  }
  // TOTAL 小数点被 OCR 吃掉 (如 TOTAL 13889): 仅当候选/100 大于小计且不超过小计*1.3 才低置信补回, 不乱猜
  if(total===null && subtotal!==null){
    for(const l of lines){ const up=l.text.toUpperCase(); if(!/\bTOTAL\b/.test(up)||up.includes('NUMBER')||up.includes('TAX')) continue; const m=l.text.match(/(\d{4,6})\s*$/); if(m){ const cand=parseInt(m[1])/100; if(cand>subtotal && cand<subtotal*1.3){ total=cand; totalConf=0.5; break; } } }
  }
  // 总计金额在 AMOUNT/MasterCard 等多行重复出现时互相印证, 提高数字置信 (不改值)
  if(total!==null){ let hits=0; for(const l of lines){ if(_price(l.text)===total) hits++; } if(hits>=2) totalConf=Math.max(totalConf,0.9); }
  let expected=null;
  for(const l of lines){ const n=l.text.toUpperCase().replace(/[^A-Z0-9]/g,'');
    let m=n.match(/(?:T?OTAL|TOTAL)NUMBEROF(?:PRESCANNED)?ITEMS(?:SOLD)?(\d+)/); if(m) expected=parseInt(m[1]);
    let m2=n.match(/ITEMSSOLD(\d+)/); if(m2&&expected===null) expected=parseInt(m2[1]);
    let m3=n.match(/NUMBEROF(?:PRESCANNED)?ITEMS(?:SOLD)?(\d{1,3})/); if(m3&&expected===null) expected=parseInt(m3[1]); // TOTAL 两字被认丢时，NUMBER OF ... ITEMS= N 本身也够定件数
  }
  const mark=t=>t.toUpperCase().replace(/[^A-Z0-9]/g,'');
  let zs=-1, ze=lines.length;
  lines.forEach((l,i)=>{ const n=mark(l.text); if(n.includes('STARTOFPRE')||n.includes('STARTOFITEMS')) zs=i; if((n.includes('ENDOFPRE')||n.includes('ENDOFITEMS'))&&ze===lines.length) ze=i; });
  let itemLines = zs>=0? lines.slice(zs+1,ze) : lines.slice(0,ze);
  if(!itemLines.length) itemLines=lines;
  const items=[]; const skipWords=['TOTAL','SUBTOTAL','TAX','AMOUNT','CHANGE','MASTERCARD','REFERENCE','AUTH','INVOICE','MEMBER'];
  let pending=null;
  // 费用挂靠：lastProduct=最近一件正价商品；费用在它之前出现时先攒着，挂到下一件并注明位置不确定
  let lastProduct=null; const pendingFees=[];
  function _feeFromLine(t,conf){
    const p=_price(t); if(p===null) return null;
    const fname=/ENVIR/i.test(t)?'ENVIRO FEE':'DEPOSIT';
    return {fee_name:fname,amount:p,confidence:conf??0.5,manual:false,kind:'fee'};
  }
  function attachFee(fee){
    if(!fee) return;
    if(lastProduct){
      if(!lastProduct.attached_fees) lastProduct.attached_fees=[];
      // 同一件下面同名同额只留一份（同一张图内 OCR 重复行不重复收）
      if(!lastProduct.attached_fees.some(x=>x.fee_name===fee.fee_name && Math.abs(Number(x.amount)-Number(fee.amount))<0.005)) lastProduct.attached_fees.push(fee);
    } else pendingFees.push(fee);
  }
  function claimPendingFees(product){
    if(!product) return;
    if(!product.attached_fees) product.attached_fees=[];
    for(const f of pendingFees){ product.attached_fees.push({...f,position_note:'位置不确定，先跟在这一件下面',orphan_at_part_start:true}); }
    pendingFees.length=0;
  }
  for(const l of itemLines){
    const t=l.text.trim(); if(!t) continue;
    const op=_orphanPrice(t);
    if(op!==null && !['TOTAL','SUBTOTAL','TAX'].some(w=>t.toUpperCase().includes(w))){
      let filled=false;
      if(items.length && items[items.length-1].price===''){ const it=items[items.length-1]; it.price=op[0]; it.confidence=Math.min(it.confidence,0.6); if(op[2]&&typeof op[0]==='number'){it.price=-Math.abs(op[0]); it.is_discount=true;} filled=true; }
      if(!filled) pending=[op[0],op[1],l.conf??0.5,0];
      continue;
    }
    if(pending!==null){ pending=[pending[0],pending[1],pending[2],pending[3]+1]; if(pending[3]>2) pending=null; }
    if(/ENVIR|EPOSIT|DEP[AEOA0]SIT|DEPOSIT|\bPOSIT\b/i.test(t)){ attachFee(_feeFromLine(t,l.conf)); pending=null; continue; } // 费用不当商品、金额不串给下一件；按顺序挂到上一件商品下面
    if(/^20\d{2}[/\-]\d{1,2}[/\-]/.test(t)) continue; // 底部日期行不是商品
    // 行首杂字符 (Tesseract 常加 £/§/单个数字) 先剥掉; 代码与 **KS 这类符号黏连也要拆
    let tt=t.replace(/^\S{1,3}\s+[^\dA-Za-z]{1,3}\s+(?=\d{3,12}\b)/,'').replace(/^\S{1,3}\s+(?=\d{3,12}\b)/,'').replace(/^[^\dA-Za-z]{1,4}\s+(?=\d{3,12}\b)/,'').replace(/^\d\s+(?=\d{3,12}\b)/,'');
    let code=null,rest=null,qty=1,cap=1.0;
    const mDoz=tt.match(/^(\d{3})([1-9])\s+([A-Za-z].*(?:DOZ|EGGS).+)$/i);
    const mSp=tt.match(/^(\d{3,12})\s+(.+)$/);
    const mSym=tt.match(/^(\d{3,12})[\*\%\#]+([A-Za-z].+)$/);
    const mGl=tt.match(/^(\d{3,12})([A-Za-z\/].+)$/);
    if(mDoz){ code=mDoz[1]; qty=1; rest=mDoz[2]+' '+mDoz[3]; cap=0.5; }
    else if(mSp){ code=mSp[1]; rest=mSp[2]; }
    else if(mSym){ code=mSym[1]; rest=mSym[2]; cap=0.8; }
    else if(mGl){ code=mGl[1]; rest=mGl[2]; cap=0.8; }
    else {
      const m2=t.match(/(\d{3,12})\s*([A-Za-z\/][A-Za-z0-9 \/\'-]*?)\s+(\d{1,4}\.\d{2})/);
      if(m2 && !t.toUpperCase().includes('MEMBER')){
        // 折扣行被 OCR 读歪走兜底分支时（如尾巴 4.00-GP、名称只剩 /残段），不能当正价商品占件数：
        // 按负数折扣伪行推入，后面会挂到上一件（分段时上一件在上一张也能接，见 dedupe 的孤折扣处理）
        const discLike=/^\s*\//.test(m2[2].trim()) || /\d{1,4}\.\d{2}\s*-\s*(GP|G)?(\s|$)/.test(t) || /TPD\//i.test(t) || /^0000\d{5,}/.test(m2[1]);
        if(discLike){ items.push({item_code:m2[1],item_name:'折扣',price:-Math.abs(parseFloat(m2[3])),quantity:1,confidence:Math.min(l.conf??0.5,0.5),is_discount:true,discount:'',discount_code:'',discount_for:'',attached_fees:[]}); }
        else { const [nm]=cleanName(m2[2].trim()); const fz=fuzzyCorrectName(nm); const ni={item_code:m2[1],item_name:fz.name,price:parseFloat(m2[3]),quantity:1,confidence:Math.min(l.conf??0.5,0.6),name_corrected:fz.corrected,name_similarity:fz.similarity,is_discount:false,discount:'',discount_code:'',discount_for:'',attached_fees:[]}; items.push(ni); lastProduct=ni; claimPendingFees(ni); }
      }
      continue;
    }
    if(skipWords.some(s=>t.toUpperCase().includes(s)) && !/^\d{3,12}\s*[A-Z\/]/.test(t)) continue;
    if(code.startsWith('000000') || rest.trim().toUpperCase().startsWith('E800') || /\d{2}:\d{2}/.test(rest)) continue;
    if(/TTAWA|COQUITLAM|STREET|V3B|V\d[A-Z]\d/i.test(rest) || /^\d+\s+[A-Za-z]+\s+(St\.?|Ave\b)/i.test(rest) || /#\s*\d{3}\b/.test(rest)) continue; // 地址行拦截放宽: CHICKEN ST / KS BATH# 这类商品名不能误杀 (名称模糊容错)
    if(code.length>10 && !code.startsWith('0000')) continue;
    let conf=Math.min(l.conf??0.5,cap);
    const prices=[...rest.matchAll(/-?\d{1,4}\.\d{2}/g)].map(x=>x[0]);
    let price=null,deformed=false;
    if(!prices.length){ const toks=rest.trim().split(/\s+/); const corr=toks.length?_correctPriceToken(toks[toks.length-1].replace(/-$/,'')):null; if(corr!==null){ prices.push(String(corr)); conf=Math.min(conf,0.6); rest=toks.slice(0,-1).join(' '); } }
    let name='';
    if(prices.length){ price=parseFloat(prices[0]); name=rest.replace(/-?\d{1,4}\.\d{2}\s*-?\s*(GP|G)?\b.*$/,'').trim().replace(/^[ -]+|[ -]+$/g,''); }
    else {
      const toks=rest.trim().split(/\s+/);
      if(toks.length>=2 && _deformedPriceToken(toks[toks.length-1].replace(/-$/,''))){ deformed=true; name=toks.slice(0,-1).join(' ').trim(); }
      else name=rest.replace(/\s+\d{3}\s*$/,'').trim();
      if(pending!==null && !deformed){ price=pending[0]; deformed=deformed||pending[1]; conf=Math.min(conf,0.6); pending=null; }
      else { if(deformed) pending=null; price=''; }
      if(price==='') conf=Math.min(conf,0.4);
    }
    name=name.replace(/^\//,'折扣 ').trim();
    const isDisc = code.startsWith('000039') || (code.length>=9 && code.startsWith('0000')) || /^(TPD\/|\/|折扣\s)/i.test(name) || /\d\.\d{2}\s*-\s*(GP)?\s*$/.test(t); // 折扣代码是000039xxxx类长码, OCR把9认成5也要认得出
    if(typeof price==='number' && isDisc) price=-Math.abs(price);
    if(typeof price==='number' && /\d\.\d{2}\s*-\s*(GP)?\s*$/.test(t) && price>0) price=-price;
    const [nm0,nameChanged]=cleanName(name.replace(/^[\*\%\#]+/,'').replace(/[\*]+$/,'').trim());
    let fz=fuzzyCorrectName(nm0); let nm=fz.name;
    // 代码末位0其实是名称首字母O被黏进代码 (6950350RGANIC -> 695035 + ORGANIC): 候选更像已知商品才拆, 不乱改
    if(/0$/.test(code||'') && nm0){ const cand=fuzzyCorrectName('O'+nm0); if(cand.similarity>fz.similarity && cand.similarity>=0.9){ code=String(code).slice(0,-1); nm=cand.name; fz={...cand,corrected:true}; } }
    // 名称小错不降低数字置信、不丢行: 数字(代码/价格)置信与名称分开
    if(nm.length<2) conf=Math.min(conf,0.5);
    let df=''; const md=name.match(/\/(\d{3,12})\b/); if(isDisc&&md) df=md[1];
    const _ni={item_code:code,item_name:nm||'（名称没看清）',price:price,quantity:qty,confidence:conf,name_corrected:fz.corrected,name_similarity:fz.similarity,is_discount:!!(isDisc||code.startsWith('000039')),discount_for:df,discount:'',discount_code:'',attached_fees:[]};
    items.push(_ni);
    const _isDiscRow=_ni.is_discount&&typeof _ni.price==='number'&&_ni.price<0;
    if(!_isDiscRow){ lastProduct=_ni; claimPendingFees(_ni); }
  }
  // 商品区之外的费用行（如费用被拍到 END 标记之后）：挂到最后一件，不丢
  {
    const inZone=new Set(itemLines);
    for(const l of lines){ if(inZone.has(l)) continue; const t=String(l.text||''); if(/ENVIR|DEP[AEOA0]SIT|DEPOSIT|\bPOSIT\b/i.test(t)) attachFee(_feeFromLine(t,l.conf)); }
  }
  const merged=[];
  for(const it of items){
    if(it.is_discount && typeof it.price!=='number') continue; // 折扣行金额没认出: 它不是商品, 不能占一件的数(金额会在金额核对里以差额报警)
    const isDiscRow=it.is_discount&&typeof it.price==='number'&&it.price<0;
    if(isDiscRow&&merged.length&&!merged[merged.length-1].is_discount){
      const prev=merged[merged.length-1];
      if(prev.discount===''){ prev.discount=it.price; prev.discount_code=it.item_code; prev.discount_for=it.discount_for||prev.item_code; }
      else { prev.discount=Math.round((parseFloat(prev.discount)+it.price)*100)/100; prev.discount_code=(String(prev.discount_code||'')+'+'+it.item_code).replace(/^\++/,''); }
      prev.confidence=Math.min(prev.confidence,it.confidence);
    } else merged.push(it);
  }
  for(const it of merged){ if(!Array.isArray(it.attached_fees)) it.attached_fees=[]; }
  // 费用按小票顺序摊平（顺序=所属商品在清单中的顺序），供金额核对/入库兼容字段使用
  const fees=[]; const unattached_fees=[];
  for(const it of merged){ for(const f of (it.attached_fees||[])) fees.push({...f,attached_to:it.item_code,attached:true}); }
  for(const f of pendingFees){ fees.push({...f,attached_to:'',attached:false}); unattached_fees.push({...f}); }
  const productCount=merged.filter(it=>!it.is_discount).length;
  // 金额校验（只提示、不静默改价）: 商品价+折扣 与 SUBTOTAL 对照, 差额可能含 ENVIRO/DEPOSIT 等费用
  let itemsSum=0; for(const it of merged){ if(typeof it.price==='number') itemsSum+=it.price; if(it.discount!==''&&typeof it.discount==='number') itemsSum+=it.discount; }
  itemsSum=Math.round(itemsSum*100)/100;
  const amountDiff=(subtotal!==null&&subtotal!==undefined)? Math.round((subtotal-itemsSum)*100)/100 : null;
  const amountMismatch=(amountDiff!==null && Math.abs(amountDiff)>0.05);
  const feesSum=Math.round(fees.reduce((a,f)=>a+(typeof f.amount==='number'?f.amount:0),0)*100)/100;
  const fullSubSum=Math.round((itemsSum+feesSum)*100)/100;
  const fullAmountDiff=(subtotal!==null&&subtotal!==undefined)? Math.round((subtotal-fullSubSum)*100)/100 : amountDiff;
  return {items_sum:itemsSum,fees:fees,unattached_fees:unattached_fees,fees_sum:feesSum,tax:tax,tax_confidence:tax!==null?taxConf:0.3,full_sum:fullSubSum,amount_diff:fullAmountDiff,amount_mismatch:(()=>{ const fc=fullAmountCheck(itemsSum,feesSum,tax,subtotal,total); return fc.level==='warn_large'||fc.level==='mid'; })(),store_code:store,store_confidence:storeConf,purchase_date:purchaseDate,date_confidence:purchaseDate?dateConf:0.3,total:total,total_confidence:total!==null?totalConf:0.3,subtotal:subtotal,items:merged,expected_item_count:expected,product_count:productCount,count_mismatch:expected!==null&&productCount!==expected};
}
if(typeof module!=='undefined'&&module.exports) module.exports={parseReceipt,cleanName,dedupeMergeParts,seamRowMatch,amountCheck,fullAmountCheck,fuzzyCorrectName};

// --- 多张接缝自动去重 + 金额闭环（用户要求：不能让用户手工删接缝重复）---
// 规则：只有“前图末尾与后图开头连续多行顺序重合”才算接缝重复；买两件同款（如两件BOUNTY）
// 本来就会同代码同价分开列，若不在接缝连续段里、或删掉后件数/金额反而对不上，就不删。
function _priceEq(a,b){ return typeof a==='number'&&typeof b==='number'&&Math.abs(a-b)<0.005; }
function _discEq(a,b){ const da=(a&&a.discount!==''&&a.discount!==undefined&&a.discount!==null)?Number(a.discount):null; const db=(b&&b.discount!==''&&b.discount!==undefined&&b.discount!==null)?Number(b.discount):null; return da===null||db===null||Math.abs(da-db)<0.005; }
function _seamNameSim(a,b){
  // 接缝比对时名称常混入价格碎片数字（如 TILAPI 29 858 / 5 DOZ ERGS 19 9）：只取字母词再比，避免碎片拉低相似度
  const clean=x=>String(x||'').toUpperCase().split(/\s+/).filter(tok=>/[A-Z]/.test(tok)).join(' ');
  return Math.max(_sim(String(a||'').toUpperCase(),String(b||'').toUpperCase()), _sim(clean(a),clean(b)));
}
function seamRowMatch(a,b){
  if(!a||!b) return {match:false,strong:false,similarity:0};
  if(a.is_discount||b.is_discount) return {match:false,strong:false,similarity:0};
  if(!_discEq(a,b)) return {match:false,strong:false,similarity:0};
  const ca=String(a.item_code||'').trim(), cb=String(b.item_code||'').trim();
  const sim=_seamNameSim(a.item_name,b.item_name);
  const codeEq=!!ca&&ca===cb;
  if(!_priceEq(a.price,b.price)){
    // 分段拍时同一行在两张图里常被认差几分钱（如 9.69/9.63）：代码相同+名称很像+差<=0.20 只算弱同行，
    // 必须靠成段对齐或件数/金额闭环才删，不凭一行弱匹配乱删
    const bothNum=typeof a.price==='number'&&typeof b.price==='number';
    if(bothNum && codeEq && sim>=0.95) return {match:true,strong:false,similarity:Math.round(sim*100)/100,price_diff:Math.round(Math.abs(a.price-b.price)*100)/100}; // 代码+名称几乎一模一样，价格某位被 OCR 认错也先算弱同行，靠成段+闭环决定删不删
    if(bothNum && codeEq && sim>=0.90 && Math.abs(a.price-b.price)<=0.20) return {match:true,strong:false,similarity:Math.round(sim*100)/100,price_diff:Math.round(Math.abs(a.price-b.price)*100)/100};
    if(!bothNum && codeEq && sim>=0.85 && (a.price===''||b.price==='')) return {match:true,strong:false,similarity:Math.round(sim*100)/100};
    return {match:false,strong:false,similarity:Math.round(sim*100)/100};
  }
  if(codeEq && sim>=0.55) return {match:true,strong:sim>=0.78,similarity:Math.round(sim*100)/100};
  if(!codeEq && ca && cb && sim>=0.88) return {match:true,strong:sim>=0.93,similarity:Math.round(sim*100)/100}; // 代码认错一位，但名称+价格高度一致
  if((!ca||!cb) && sim>=0.92) return {match:true,strong:false,similarity:Math.round(sim*100)/100};
  return {match:false,strong:false,similarity:Math.round(sim*100)/100};
}
function _feasibleOverlaps(A,B){
  // 候选 = {drop, offset, matched, aSkipTail}：从 B 开头共扔掉 drop 行，其中真正对上的 matched 行，
  // B 开头 offset 行是残行/折扣孤行、A 末尾 aSkipTail 行是接缝杂行时也允许对齐（真实分段拍常见）。
  // 是否采用仍由 assemble 后的件数+金额闭环评分决定，并在候选中保留 matched 供评分区分强弱。
  const out=[]; const seen=new Set();
  const maxO=Math.min(3,Math.max(0,B.length-1)), maxT=Math.min(2,Math.max(0,A.length-1));
  for(let o=0;o<=maxO;o++) for(let t=0;t<=maxT;t++){
    const maxK=Math.min(8,A.length-t,B.length-o);
    for(let k=1;k<=maxK;k++){
      let ok=true, strong=true, b=o, matchedN=0;
      // B 段中间夹着的孤折扣行（上一件的折扣在下一张才出现）不挡对齐：跳过它继续比下一行
      while(matchedN<k){
        if(b>=B.length){ ok=false; break; }
        if(B[b].is_discount && typeof B[b].price==='number' && B[b].price<0){ b++; continue; }
        const m=seamRowMatch(A[A.length-t-k+matchedN],B[b]); if(!m.match){ ok=false; break; } if(!m.strong) strong=false;
        b++; matchedN++;
      }
      if(ok && (k>=2 || strong)){
        const cand={drop:b,offset:o,matched:k,aSkipTail:t};
        const key=cand.drop+'|'+cand.offset+'|'+cand.matched+'|'+cand.aSkipTail;
        if(!seen.has(key)){ seen.add(key); out.push(cand); }
      }
    }
  }
  return out;
}
function amountCheck(itemsSum, subtotal, total){
  const target=(subtotal!==null&&subtotal!==undefined)?Number(subtotal):(total!==null&&total!==undefined?Number(total):null);
  const targetLabel=(subtotal!==null&&subtotal!==undefined)?'小票小计 SUBTOTAL':(target!==null?'小票总计 TOTAL':null);
  if(target===null) return {target:null,target_label:targetLabel,diff:null,abs_diff:null,level:'none',message:'小票小计/总计没认出来，没法自动核对金额'};
  const diff=Math.round((target-Number(itemsSum))*100)/100; const ad=Math.abs(diff);
  const largeThreshold=Math.max(3, Math.round(target*0.03*100)/100);
  let level,message;
  if(ad===0){ level='exact'; message='完全对上 ✓ 商品加总和小票印的金额一分不差'; }
  else if((subtotal===null||subtotal===undefined) && diff>=0 && ad>1.00 && ad<=Math.round(target*0.15*100)/100){ level='tax_likely'; message='这是拿总计 TOTAL 比的，总计含税：差额主要是税 + 环保费/押金（本样本税约 2.88、费用 0.17，合计正好约 3.05），不算异常；能认出小计时以小计核对为准'; }
  else if(ad<=1.00){ level='ok_small'; message='差额在 1 元以内，应是环保费 ENVIRO FEE / 押金 DEPOSIT 这类没进商品清单的费用（样本出现过 0.07+0.10=0.17），不用紧张'; }
  else if(ad>largeThreshold){ level='warn_large'; message='差额明显偏大（超过 '+largeThreshold.toFixed(2)+' 元或总额约 3%）：可能是漏了一件、价格认错，或自动去重删多了，请重点核对'; }
  else { level='mid'; message='差额不算小也不算特别大，请扫一眼价格有没有认错一位'; }
  return {target:target,target_label:targetLabel,diff:diff,abs_diff:ad,large_threshold:largeThreshold,level:level,message:message};
}
// 完整金额核对：商品(+折扣) + 费用 + 税 应等于 TOTAL；商品+费用应等于 SUBTOTAL
function fullAmountCheck(itemsSum, feesSum, tax, subtotal, total){
  const items=Number(itemsSum)||0, fees=Number(feesSum)||0, tx=(tax===null||tax===undefined||tax==='')?null:Number(tax);
  const calcSub=Math.round((items+fees)*100)/100;
  if(total!==null && total!==undefined && total!==''){
    const calcTotal=Math.round((calcSub+(tx||0))*100)/100;
    const diff=Math.round((Number(total)-calcTotal)*100)/100, ad=Math.abs(diff);
    const large=Math.max(3, Math.round(Number(total)*0.03*100)/100);
    let level,message;
    if(ad===0){level='exact';message='完全对上 ✓ 商品 + 费用 + 税 = 小票总计';}
    else if(tx===null && diff>0 && ad<=Math.round(Number(total)*0.15*100)/100){level='tax_likely';message='税 TAX 还没认出来：差额多半是税 + 费用，请核对税那一栏';}
    else if(ad<=1.00){level='ok_small';message='差额在 1 元以内，请扫一眼费用/税有没有漏填';}
    else if(ad>large){level='warn_large';message='差额明显偏大：可能漏了一件、价格认错，或费用/税没填，请重点核对';}
    else {level='mid';message='差额不算小，请扫一眼价格、费用和税有没有认错一位';}
    return {target:Number(total),target_label:'小票总计 TOTAL',diff,abs_diff:ad,level,message,calc_subtotal:calcSub,calc_total:calcTotal,items_sum:items,fees_sum:fees,tax:tx,formula:`商品 $${items.toFixed(2)} + 费用 $${fees.toFixed(2)} + 税 $${(tx||0).toFixed(2)} = $${calcTotal.toFixed(2)}`};
  }
  if(subtotal!==null && subtotal!==undefined && subtotal!==''){
    const diff=Math.round((Number(subtotal)-calcSub)*100)/100, ad=Math.abs(diff);
    const large=Math.max(3, Math.round(Number(subtotal)*0.03*100)/100);
    let level,message;
    if(ad===0){level='exact';message='完全对上 ✓ 商品 + 费用 = 小票小计（总计还要再加税）';}
    else if(ad<=1.00){level='ok_small';message='差额在 1 元以内，应是费用还没认全，请扫一眼';}
    else if(ad>large){level='warn_large';message='差额明显偏大：可能漏了一件或价格认错，请重点核对';}
    else {level='mid';message='差额不算小，请扫一眼';}
    return {target:Number(subtotal),target_label:'小票小计 SUBTOTAL',diff,abs_diff:ad,level,message,calc_subtotal:calcSub,calc_total:null,items_sum:items,fees_sum:fees,tax:tx,formula:`商品 $${items.toFixed(2)} + 费用 $${fees.toFixed(2)} = $${calcSub.toFixed(2)}（小计口径，未加税）`};
  }
  return {target:null,target_label:null,diff:null,abs_diff:null,level:'none',message:'小票小计/总计没认出来，没法自动核对金额',calc_subtotal:calcSub,calc_total:null,items_sum:items,fees_sum:fees,tax:tx,formula:`商品 $${items.toFixed(2)} + 费用 $${fees.toFixed(2)} + 税 $${(tx||0).toFixed(2)}`};
}
function _pickVoted(parts, get, confGet){
  // 同一张票分几张拍，同一字段可能被某一张认错：多张一致的值优先（互相印证），
  // 票数相同时用最早出现的那张，避免后一张的错值盖掉前一张、也避免第一张错了就锁死。
  const seen=new Map();
  (parts||[]).forEach((r,idx)=>{ const v=get(r); if(v===null||v===undefined||v==='') return; const k=String(v); if(!seen.has(k)) seen.set(k,{value:v,count:0,first:idx,conf:confGet?confGet(r):0.5}); seen.get(k).count++; });
  let best=null; for(const e of seen.values()){ if(!best || e.count>best.count || (e.count===best.count && e.first<best.first)) best=e; }
  return best?{value:best.value,conf:best.conf}:null;
}
function dedupeMergeParts(parts){
  parts=(parts||[]).filter(Boolean);
  // 头部字段按多张互相印证选值（原逻辑第一张有值就锁死：第一张门店认错时，后面认对了也救不回来）
  const _sv=_pickVoted(parts,r=>r.store_code,r=>r.store_confidence??0.5);
  const _dv=_pickVoted(parts,r=>r.purchase_date,r=>r.date_confidence??0.5);
  const _tv=_pickVoted(parts,r=>r.total,r=>r.total_confidence??0.5);
  const _sbv=_pickVoted(parts,r=>r.subtotal);
  const _ev=_pickVoted(parts,r=>r.expected_item_count);
  const _txv=_pickVoted(parts,r=>r.tax,r=>r.tax_confidence??0.5);
  let store=_sv?_sv.value:'',storeConf=_sv?_sv.conf:0.3,date=_dv?_dv.value:'',dateConf=_dv?_dv.conf:0.3,total=_tv?_tv.value:null,totalConf=_tv?_tv.conf:0.3,subtotal=_sbv?_sbv.value:null,expected=_ev?_ev.value:null;
  let taxMerged=_txv?_txv.value:null, taxConfM=_txv?_txv.conf:0.3;
  // 费用不再跨张按“名称+金额”全局去重（两件商品各有一笔同额押金会被误并成一笔）；
  // 费用跟着各自商品走，接缝重复行的费用在 assemble 里转挂到留下的那件。
  const partUnattached=parts.map(r=>{
    if(Array.isArray(r.unattached_fees) && r.unattached_fees.length) return r.unattached_fees.map(f=>({...f}));
    // 旧数据/手工构造 part：fees 里没有挂到任何商品的，当作未挂靠费用保留
    const attachedKeys=new Set(); for(const it of (r.items||[])) for(const f of (it.attached_fees||[])) attachedKeys.add(String(f.fee_name)+'|'+Number(f.amount).toFixed(2));
    return (r.fees||[]).filter(f=>!f.attached && !attachedKeys.has(String(f.fee_name)+'|'+Number(f.amount).toFixed(2))).map(f=>({...f}));
  });
  const _copyItem=it=>({...it,attached_fees:(it.attached_fees||[]).map(f=>({...f}))});
  const partItems=parts.map(r=>(r.items||[]).map(_copyItem));
  function assemble(ks){
    const items=[], removed=[], seams=[];
    const unattached=[]; for(const lst of partUnattached) for(const f of lst) unattached.push({...f});
    for(let i=0;i<partItems.length;i++){
      const B=partItems[i];
      if(i===0){ for(const it of B) items.push(_copyItem(it)); continue; }
      const cand=ks[i-1]||{drop:0,offset:0,matched:0,aSkipTail:0};
      const k=(typeof cand==='number')?cand:(cand.drop||0);
      const off=(typeof cand==='number')?0:(cand.offset||0), matchedN=(typeof cand==='number')?k:(cand.matched||0), aTail=(typeof cand==='number')?0:(cand.aSkipTail||0);
      for(let j=0;j<k;j++){
        const rem=_copyItem(B[j]); removed.push({...rem,_seam_from_part:i+1});
        // 接缝被删的那份上若有这边没有的折扣/费用，转挂到留下的同一件，不跟着重复行一起丢
        let kept=null;
        if(j>=off && j<off+matchedN) kept=items[items.length-aTail-matchedN+(j-off)]||null;
        if(!kept && !(rem.is_discount && typeof rem.price==='number' && rem.price<0)){
          // B 开头被跳过的残行：在已合并末尾几行里找同一件，找到才转挂它的折扣/费用
          for(let q=items.length-1;q>=Math.max(0,items.length-6);q--){ if(seamRowMatch(items[q],rem).match){ kept=items[q]; break; } }
        }
        if(rem.is_discount && typeof rem.price==='number' && rem.price<0){
          // 下一张开头孤折扣行属于上一件：上一件还没有这笔折扣才挂，已有同额不重复挂
          let prevProd=null; for(let q=items.length-1;q>=0;q--){ if(!items[q].is_discount){ prevProd=items[q]; break; } }
          if(prevProd && (prevProd.discount===''||prevProd.discount===undefined||prevProd.discount===null)) { prevProd.discount=rem.price; prevProd.discount_code=rem.item_code; prevProd.discount_for=rem.discount_for||prevProd.item_code; }
          continue;
        }
        if(kept){
          if((kept.discount===''||kept.discount===undefined||kept.discount===null) && rem.discount!=='' && rem.discount!==undefined && rem.discount!==null){ kept.discount=rem.discount; kept.discount_code=rem.discount_code; kept.discount_for=rem.discount_for; }
          for(const f of (rem.attached_fees||[])){ if(!kept.attached_fees.some(x=>x.fee_name===f.fee_name && Math.abs(Number(x.amount)-Number(f.amount))<0.005)) kept.attached_fees.push({...f}); }
        }
      }
      if(k) seams.push({part:i+1,overlap:matchedN,dropped:k});
      for(const it of B.slice(k)){
        const isDiscRow=it.is_discount && typeof it.price==='number' && it.price<0;
        if(isDiscRow && items.length && !items[items.length-1].is_discount){
          const prev=items[items.length-1];
          if(prev.discount===''||prev.discount===undefined||prev.discount===null){ prev.discount=it.price; prev.discount_code=it.item_code; prev.discount_for=it.discount_for||prev.item_code; }
          else prev.discount=Math.round((parseFloat(prev.discount)+it.price)*100)/100;
          continue;
        }
        const ni=_copyItem(it);
        // 下一张开头先出现费用、后出现商品时，parser 把费用暂挂在该张第一件上（orphan_at_part_start）；
        // 合并时它实际属于上一张最后一件，转挂过去，顺序才跟小票一致
        if(items.length && ni.attached_fees && ni.attached_fees.length){
          const orphans=ni.attached_fees.filter(f=>f.orphan_at_part_start);
          if(orphans.length){
            let prevProd=null; for(let q=items.length-1;q>=0;q--){ if(!items[q].is_discount){ prevProd=items[q]; break; } }
            if(prevProd){ for(const f of orphans){ if(!prevProd.attached_fees.some(x=>x.fee_name===f.fee_name && Math.abs(Number(x.amount)-Number(f.amount))<0.005)) prevProd.attached_fees.push({...f,position_note:'按顺序跟在上一件下面'}); } ni.attached_fees=ni.attached_fees.filter(f=>!f.orphan_at_part_start); }
          }
        }
        items.push(ni);
      }
    }
    return {items,removed,seams,unattached};
  }
  function stats(items,unattached){
    const pc=items.filter(it=>!it.is_discount).length;
    let s=0; for(const it of items){ if(typeof it.price==='number') s+=it.price; if(it.discount!==''&&typeof it.discount==='number') s+=it.discount; }
    let feeSum=0; for(const it of items) for(const f of (it.attached_fees||[])) feeSum+=Number(f.amount)||0;
    for(const f of (unattached||[])) feeSum+=Number(f.amount)||0;
    const fs=Math.round(feeSum*100)/100;
    return {pc,sum:Math.round(s*100)/100,fees_sum:fs,full_sum:Math.round((s+fs)*100)/100};
  }
  // 枚举每道接缝的重叠长度，用件数+小计金额闭环选最优（不同重叠长度都试）
  let combos=[[]];
  const ZERO={drop:0,offset:0,matched:0,aSkipTail:0};
  for(let i=1;i<partItems.length;i++){
    const opts=[ZERO,..._feasibleOverlaps(partItems[i-1],partItems[i])];
    const next=[]; for(const c of combos) for(const k of opts) next.push([...c,k]); combos=next;
  }
  const evidence = expected!==null || subtotal!==null;
  let best=null;
  for(const ks of combos){
    const a=assemble(ks); const st=stats(a.items,a.unattached); const overlapTotal=ks.reduce((x,y)=>x+(typeof y==='number'?y:(y.drop||0)),0);
    const cand={ks,...a,...st,overlapTotal,
      countMismatch:expected!==null?Math.abs(st.pc-expected):null,
      amountDiff:(subtotal!==null)?Math.round((subtotal-st.full_sum)*100)/100:null};
    cand.score = evidence ? ((cand.countMismatch||0)*100 + (cand.amountDiff!==null?Math.abs(cand.amountDiff):0)) : 0;
    cand.effectiveOverlap = ks.reduce((s,k)=>s+(((typeof k==='number'?k:(k.matched||0))>=2)?(typeof k==='number'?k:(k.matched||0)):0),0);
    if(!best) best=cand;
    else if(evidence){ if(cand.score<best.score-0.001 || (Math.abs(cand.score-best.score)<=0.001 && cand.overlapTotal>best.overlapTotal)) best=cand; }
    else { if(cand.effectiveOverlap>best.effectiveOverlap) best=cand; }
  }
  const items=best?best.items:[], removed=best?best.removed:[];
  const st=stats(items,best?best.unattached:[]);
  const acFull=fullAmountCheck(st.sum, st.fees_sum, taxMerged, subtotal, total);
  const ac=acFull;
  const feesFlat=[]; for(const it of items) for(const f of (it.attached_fees||[])) feesFlat.push({...f,attached_to:it.item_code,attached:true}); for(const f of ((best&&best.unattached)||[])) feesFlat.push({...f,attached_to:'',attached:false});
  return {items_sum:st.sum,fees:feesFlat,unattached_fees:(best&&best.unattached)||[],fees_sum:st.fees_sum,tax:taxMerged,tax_confidence:taxConfM,full_sum:st.full_sum,amount_diff:acFull.diff,amount_mismatch:acFull.level==='warn_large'||acFull.level==='mid',amount_check:acFull,legacy_amount_check:amountCheck(st.sum, subtotal, total),
    store_code:store,store_confidence:storeConf,purchase_date:date,date_confidence:dateConf,
    total:total,total_confidence:totalConf,subtotal:subtotal,items:items,
    expected_item_count:expected,product_count:st.pc,count_mismatch:expected!==null&&st.pc!==expected,
    auto_removed_items:removed,auto_removed_count:removed.length,seam_overlaps:best?best.seams:[],parts_count:parts.length,
    missing_count:(expected!==null&&st.pc<expected)?(expected-st.pc):0,extra_count:(expected!==null&&st.pc>expected)?(st.pc-expected):0};
}
