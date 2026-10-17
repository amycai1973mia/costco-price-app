// 用 Python 版保存的 raw_lines 喂给 JS 版 parser，对照两边结果（不跑浏览器 OCR）
const fs=require('fs'), path=require('path');
const {parseReceipt}=require('../docs/parser.js');
const dir='/workspace/costco-price-app/data/pending';
let files=fs.readdirSync(dir).filter(f=>f.endsWith('.json'));
// 选有代表性的：件数核对成功/商品多
let cases=[];
for(const f of files){ try{ const d=JSON.parse(fs.readFileSync(path.join(dir,f),'utf8')); if(d.raw_lines&&d.raw_lines.length>10) cases.push([f,d]); }catch(e){} }
cases.sort((a,b)=>(b[1].items?.length||0)-(a[1].items?.length||0));
cases=cases.slice(0,6);
for(const [f,d] of cases){
  const r=parseReceipt(d.raw_lines.map(l=>({text:l.text,conf:l.conf})));
  console.log('='.repeat(60)); console.log(f, `py_items=${d.items?.length} py_store=${d.store_code} py_date=${d.purchase_date} py_total=${d.total} py_expected=${d.expected_item_count}`);
  console.log(`JS store=${r.store_code} date=${r.purchase_date} total=${r.total} subtotal=${r.subtotal} expected=${r.expected_item_count} product=${r.product_count} mismatch=${r.count_mismatch} items=${r.items.length}`);
  for(const it of r.items) console.log(`  ${it.item_code} | ${it.item_name} | ${it.price} | disc=${it.discount||''} conf=${it.confidence}`);
}
