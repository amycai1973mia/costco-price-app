// 自动接缝去重 + 金额闭环专项（node，不跑 OCR）
// 场景A: 两段有2行连续重叠 -> 自动去掉2行, 件数/金额对上
// 场景B: 买两件同款BOUNTY同代码同价分开列(不在接缝连续段) -> 不误删
// 场景C: 两段无重叠(漏拍中间) -> 不删任何行, missing_count 提示差几件
// 场景D: 接缝单行弱重合但件数/金额不支持 -> 不删; 单行强重合且件数支持 -> 删
// 场景E: 名称错1-2字母、代码认错一位的接缝重合 -> 仍判同一行
const {dedupeMergeParts, amountCheck}=require('../docs/parser.js');
let fail=0; const ck=(name,cond,extra)=>{ console.log((cond?'PASS ':'FAIL ')+name+(extra?' | '+extra:'')); if(!cond) fail++; };
const it=(code,name,price,disc)=>({item_code:code,item_name:name,price:price,quantity:1,confidence:0.9,is_discount:false,discount:disc||'',discount_code:''});
const part=(items,extra)=>({store_code:'255',purchase_date:'2026-10-08',total:null,subtotal:null,expected_item_count:null,items,...(extra||{})});
// A
const A1=part([it('111','BOUNTY 12X91',16.99),it('222','FLOUR 10KG',9.99),it('333','MINI CUKES',5.49),it('444','DOZ EGGS',7.99)]);
const A2=part([it('333','MINI CUKES',5.49),it('444','DOZ EGGS',7.99),it('555','PORK LOIN',24.34)],{subtotal:64.80,expected_item_count:5,total:64.80});
let r=dedupeMergeParts([A1,A2]);
ck('A 自动去掉2行接缝重复', r.auto_removed_count===2, 'removed='+r.auto_removed_count);
ck('A 商品不重不漏5件', r.product_count===5 && r.items.map(x=>x.item_code).join(',')==='111,222,333,444,555', r.items.map(x=>x.item_code).join(','));
ck('A 件数核对通过', r.count_mismatch===false);
ck('A 金额闭环', Math.abs(r.items_sum-64.80)<0.01 && r.amount_check.level!=='warn_large', 'sum='+r.items_sum);
// B 两件BOUNTY: 同一张内相邻两件 + 第二张开头不是连续重叠段
const B1=part([it('111','BOUNTY 12X91',16.99),it('111','BOUNTY 12X91',16.99),it('222','FLOUR 10KG',9.99)]);
const B2=part([it('333','MINI CUKES',5.49)],{subtotal:49.46,expected_item_count:4});
r=dedupeMergeParts([B1,B2]);
ck('B 买两件同款不误删', r.auto_removed_count===0 && r.product_count===4 && r.items.filter(x=>x.item_code==='111').length===2, 'removed='+r.auto_removed_count+' n='+r.product_count);
// B2 接缝恰在两件BOUNTY之间(第一张末=BOUNTY, 第二张首=第二件BOUNTY): 件数/金额支持保留 -> 不删
const B21=part([it('111','BOUNTY 12X91',16.99)]);
const B22=part([it('111','BOUNTY 12X91',16.99),it('222','FLOUR 10KG',9.99)],{subtotal:43.97,expected_item_count:3});
r=dedupeMergeParts([B21,B22]);
ck('B2 接缝单件同款靠件数/金额保住不删', r.auto_removed_count===0 && r.product_count===3, 'removed='+r.auto_removed_count+' n='+r.product_count);
// C 无重叠漏拍
const C1=part([it('111','BOUNTY 12X91',16.99),it('222','FLOUR 10KG',9.99)]);
const C2=part([it('555','PORK LOIN',24.34)],{subtotal:80,expected_item_count:5});
r=dedupeMergeParts([C1,C2]);
ck('C 无重叠不乱删', r.auto_removed_count===0 && r.product_count===3, 'removed='+r.auto_removed_count);
ck('C 件数差提示缺2件', r.missing_count===2 && r.count_mismatch===true, 'missing='+r.missing_count);
// D 单行强重合+件数支持删
const D1=part([it('111','BOUNTY 12X91',16.99),it('222','FLOUR 10KG',9.99)]);
const D2=part([it('222','FLOUR 10KG',9.99),it('333','MINI CUKES',5.49)],{subtotal:32.47,expected_item_count:3});
r=dedupeMergeParts([D1,D2]);
ck('D 单行强重合且闭环支持才删1行', r.auto_removed_count===1 && r.product_count===3, 'removed='+r.auto_removed_count);
// E 名称错字母/代码错一位
const E1=part([it('111','BOUNTY 12X91',16.99),it('333','MINI CUKES',5.49),it('444','DOZ EGGS',7.99)]);
const E2=part([it('333','MINI dUKES',5.49),it('449','DOZ EGGS',7.99),it('555','PORK LOIN',24.34)],{subtotal:54.81,expected_item_count:4});
r=dedupeMergeParts([E1,E2]);
ck('E 名称错字母+代码错一位仍去重2行', r.auto_removed_count===2 && r.product_count===4, 'removed='+r.auto_removed_count+' codes='+r.items.map(x=>x.item_code).join(','));
// 金额阈值
ck('金额 0.17 小差=环保费/押金', amountCheck(100,100.17,null).level==='ok_small');
ck('金额 差10元=醒目大差', amountCheck(90,100,null).level==='warn_large', amountCheck(90,100,null).message);
ck('金额 大差阈值=max(3,3%)', amountCheck(0,200,null).large_threshold===6);
ck('金额 只有总计时税差不误报大差', amountCheck(90.74,null,93.79).level==='tax_likely', amountCheck(90.74,null,93.79).message);
ck('金额 加总超过总计仍报大差', amountCheck(110,null,93.79).level==='warn_large');
console.log(fail?('FAILURES='+fail):'ALL PASS'); process.exit(fail?1:0);
