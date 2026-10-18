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
// F 费用挂靠+接缝转挂（2026-10-17 本轮：费用跟商品走，不单独成列、不跨张按同额合并）
const {parseReceipt}=require('../docs/parser.js');
const L=t=>({text:t,conf:0.9});
const fr=parseReceipt(['695035 ORGANIC HOMO 9.49','ENVIRO FEE C 0.07','DEPOSIT CL 0.10','30859 CBTTA 9 GRN 6.99'].map(L));
ck('F 费用挂在所属商品下面', fr.items[0].attached_fees.length===2 && fr.items[1].attached_fees.length===0 && Math.abs(fr.fees_sum-0.17)<0.001, JSON.stringify(fr.items.map(i=>i.attached_fees.length)));
const Fa=parseReceipt(['111 AITEM 10.00','695035 ORGANIC HOMO 9.49'].map(L));
const Fb=parseReceipt(['695035 ORGANIC HOMO 9.49','ENVIRO FEE C 0.07','30859 CBTTA 9 GRN 6.99','SUBTOTAL 26.55'].map(L));
r=dedupeMergeParts([Fa,Fb]);
ck('F 接缝重复行的费用转挂到留下的那件', r.auto_removed_count===1 && r.items[1].attached_fees.length===1 && Math.abs(r.fees_sum-0.07)<0.001, 'fees_sum='+r.fees_sum);
const Fc1=parseReceipt(['111 AITEM 10.00','DEPOSIT CL 0.10'].map(L));
const Fc2=parseReceipt(['222 BITEM 20.00','DEPOSIT CL 0.10'].map(L));
r=dedupeMergeParts([Fc1,Fc2]);
ck('F 两件各一笔同额押金不误并', Math.abs(r.fees_sum-0.20)<0.001 && r.items.every(i=>i.attached_fees.length===1), 'fees_sum='+r.fees_sum);
// G 头部多张印证：第一张门店认错、后两张认对，应选认对的
const gp=(store,items)=>({store_code:store,purchase_date:'',total:null,subtotal:null,expected_item_count:null,items});
r=dedupeMergeParts([gp('370',[it('1','A',1)]),gp('255',[it('2','B',2)]),gp('255',[it('3','C',3)])]);
ck('G 门店多张印证纠正第一张错值', r.store_code==='255', 'store='+r.store_code);
// H 多张合并新修：下段开头孤折扣行不挡对齐；同行价格认差几分仍成段去重；下段开头残行可跳过对齐
const Hd1=part([it('111','AITEM',10.00),it('222','PORK LOIN',24.34)]);
const Hd2raw=parseReceipt(['0000390228 / 222 4.00-','222 PORK LOIN 24.34','333 MINI CUKES 5.49','SUBTOTAL 39.83'].map(L));
// Hd2raw 首行应是孤折扣伪行，第二行才是 PORK
r=dedupeMergeParts([Hd1,Hd2raw]);
ck('H 下段开头孤折扣不挡接缝去重', r.auto_removed_count>=1 && r.items.filter(x=>x.item_code==='222').length===1, 'removed='+r.auto_removed_count+' codes='+r.items.map(x=>x.item_code).join(','));
const Hp1=part([it('111','AITEM',10.00),it('695035','ORGANIC HOMO',9.69),it('628368','LISTERINE UC',15.99)]);
const Hp2=part([it('695035','ORGANIC HOMO',9.63),it('628368','LISTERINE UC',15.99),it('31098','PORK LOIN',24.34)],{subtotal:59.67,expected_item_count:4});
r=dedupeMergeParts([Hp1,Hp2]);
ck('H 接缝价格认差0.06成段去重', r.auto_removed_count===2 && r.product_count===4, 'removed='+r.auto_removed_count+' n='+r.product_count);
const Hf1=part([it('111','AITEM',10.00),it('695035','ORGANIC HOMO',9.69),it('628368','LISTERINE UC',15.99)]);
const Hf2=part([it('999999','NMARCLE LACLU',19.77),it('695035','ORGANIC HOMO',9.69),it('628368','LISTERINE UC',15.99),it('31098','PORK LOIN',24.34)],{subtotal:59.67,expected_item_count:4});
r=dedupeMergeParts([Hf1,Hf2]);
ck('H 下段开头残行跳过后去重', r.auto_removed_count===3 && r.product_count===4 && !r.items.some(x=>x.item_code==='999999'), 'removed='+r.auto_removed_count+' codes='+r.items.map(x=>x.item_code).join(','));
// I 中间夹孤折扣 + 价格首位认错（真实 early 票接缝形态）
const I1=part([it('111','AITEM',10.00),it('669','5 DOZ EGGS',19.99),{...it('21354','TILAPIA',29.85),discount:-5.00},it('199965','FLOUR 10KG',5.49)]);
const I2raw=parseReceipt(['669 5 DOZ ERGS 19.9','21354 TILAPT 29.85','0000393343 /MULTIPLE 5.00-','199965 FLOUR 10KG 9.49','SUBTOTAL 60.33'].map(L));
r=dedupeMergeParts([I1,I2raw]);
ck('I 接缝夹折扣+价格认错仍去重', r.product_count===4 && r.items.filter(x=>x.item_code==='199965').length===1, 'n='+r.product_count+' codes='+r.items.map(x=>x.item_code).join(','));
console.log(fail?('FAILURES='+fail):'ALL PASS'); process.exit(fail?1:0);
