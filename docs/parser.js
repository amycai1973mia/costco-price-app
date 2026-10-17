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
  for(const k of KNOWN_PRODUCTS){ const s=Math.max(_sim(cleaned,k), cleaned.length>3?_sim(cleaned.slice(1),k):0); if(s>bestSim){bestSim=s;best=k;} // 残缺前缀: CHICKEN ST -> CHICKEN STRP
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
  for(const l of lines){ const t=l.text, up=t.toUpperCase(), p=_price(t); if(p===null) continue;
    let lab=up.split(/\s+/)[0]? up.split(/\s+/)[0].replace(/[^A-Z]/g,'') : ''; lab=lab.replace(/1/g,'T').replace(/0/g,'O');
    if(lab.startsWith('SUBTOTA')||up.includes('SUBTOTAL')) subtotal=p;
    if((lab==='TOTAL'||/\bTOTAL\b/.test(up))&&!up.includes('NUMBER')&&!up.includes('TAX')){ total=p; totalConf=l.conf??0.5; }
    if(up.includes('AMOUNT')&&total===null){ total=p; totalConf=l.conf??0.5; }
  }
  // 总计金额在 AMOUNT/MasterCard 等多行重复出现时互相印证, 提高数字置信 (不改值)
  if(total!==null){ let hits=0; for(const l of lines){ if(_price(l.text)===total) hits++; } if(hits>=2) totalConf=Math.max(totalConf,0.9); }
  let expected=null;
  for(const l of lines){ const n=l.text.toUpperCase().replace(/[^A-Z0-9]/g,'');
    let m=n.match(/(?:T?OTAL|TOTAL)NUMBEROF(?:PRESCANNED)?ITEMS(?:SOLD)?(\d+)/); if(m) expected=parseInt(m[1]);
    let m2=n.match(/ITEMSSOLD(\d+)/); if(m2&&expected===null) expected=parseInt(m2[1]);
  }
  const mark=t=>t.toUpperCase().replace(/[^A-Z0-9]/g,'');
  let zs=-1, ze=lines.length;
  lines.forEach((l,i)=>{ const n=mark(l.text); if(n.includes('STARTOFPRE')||n.includes('STARTOFITEMS')) zs=i; if((n.includes('ENDOFPRE')||n.includes('ENDOFITEMS'))&&ze===lines.length) ze=i; });
  let itemLines = zs>=0? lines.slice(zs+1,ze) : lines.slice(0,ze);
  if(!itemLines.length) itemLines=lines;
  const items=[]; const skipWords=['TOTAL','SUBTOTAL','TAX','AMOUNT','CHANGE','MASTERCARD','REFERENCE','AUTH','INVOICE','MEMBER'];
  let pending=null;
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
    if(/ENVIRO|EPOSIT|DEPOSIT/i.test(t)){ pending=null; continue; }
    if(/^20\d{2}[/\-]\d{1,2}[/\-]/.test(t)) continue; // 底部日期行不是商品
    // 行首杂字符 (Tesseract 常加 £/§/单个数字) 先剥掉; 代码与 **KS 这类符号黏连也要拆
    let tt=t.replace(/^\S{1,3}\s+(?=\d{3,12}\b)/,'').replace(/^[^\dA-Za-z]{1,4}\s+(?=\d{3,12}\b)/,'').replace(/^\d\s+(?=\d{3,12}\b)/,'');
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
      if(m2 && !t.toUpperCase().includes('MEMBER')){ const [nm]=cleanName(m2[2].trim()); const fz=fuzzyCorrectName(nm); items.push({item_code:m2[1],item_name:fz.name,price:parseFloat(m2[3]),quantity:1,confidence:Math.min(l.conf??0.5,0.6),name_corrected:fz.corrected,name_similarity:fz.similarity,is_discount:false,discount:'',discount_code:'',discount_for:''}); }
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
    const isDisc = code.startsWith('000039') || /^(TPD\/|\/|折扣\s)/i.test(name) || /\d\.\d{2}\s*-\s*(GP)?\s*$/.test(t);
    if(typeof price==='number' && isDisc) price=-Math.abs(price);
    if(typeof price==='number' && /\d\.\d{2}\s*-\s*(GP)?\s*$/.test(t) && price>0) price=-price;
    const [nm0,nameChanged]=cleanName(name.replace(/^[\*\%\#]+/,'').replace(/[\*]+$/,'').trim());
    const fz=fuzzyCorrectName(nm0); const nm=fz.name;
    // 名称小错不降低数字置信、不丢行: 数字(代码/价格)置信与名称分开
    if(nm.length<2) conf=Math.min(conf,0.5);
    let df=''; const md=name.match(/\/(\d{3,12})\b/); if(isDisc&&md) df=md[1];
    items.push({item_code:code,item_name:nm||'（名称没看清）',price:price,quantity:qty,confidence:conf,name_corrected:fz.corrected,name_similarity:fz.similarity,is_discount:!!((isDisc&&typeof price==='number'&&price<0)||code.startsWith('000039')),discount_for:df,discount:'',discount_code:''});
  }
  const merged=[];
  for(const it of items){
    const isDiscRow=it.is_discount&&typeof it.price==='number'&&it.price<0;
    if(isDiscRow&&merged.length&&!merged[merged.length-1].is_discount){
      const prev=merged[merged.length-1];
      if(prev.discount===''){ prev.discount=it.price; prev.discount_code=it.item_code; prev.discount_for=it.discount_for||prev.item_code; }
      else { prev.discount=Math.round((parseFloat(prev.discount)+it.price)*100)/100; prev.discount_code=(String(prev.discount_code||'')+'+'+it.item_code).replace(/^\++/,''); }
      prev.confidence=Math.min(prev.confidence,it.confidence);
    } else merged.push(it);
  }
  const productCount=merged.filter(it=>!it.is_discount).length;
  // 金额校验（只提示、不静默改价）: 商品价+折扣 与 SUBTOTAL 对照, 差额可能含 ENVIRO/DEPOSIT 等费用
  let itemsSum=0; for(const it of merged){ if(typeof it.price==='number') itemsSum+=it.price; if(it.discount!==''&&typeof it.discount==='number') itemsSum+=it.discount; }
  itemsSum=Math.round(itemsSum*100)/100;
  const amountDiff=(subtotal!==null&&subtotal!==undefined)? Math.round((subtotal-itemsSum)*100)/100 : null;
  const amountMismatch=(amountDiff!==null && Math.abs(amountDiff)>0.05);
  return {items_sum:itemsSum,amount_diff:amountDiff,amount_mismatch:amountMismatch,store_code:store,store_confidence:storeConf,purchase_date:purchaseDate,date_confidence:purchaseDate?dateConf:0.3,total:total,total_confidence:total!==null?totalConf:0.3,subtotal:subtotal,items:merged,expected_item_count:expected,product_count:productCount,count_mismatch:expected!==null&&productCount!==expected};
}
if(typeof module!=='undefined'&&module.exports) module.exports={parseReceipt,cleanName};
