// 新小票 (2026-09-08, 5件) 关键行回归: **KS BATH** 符号行、行首杂字、名称模糊纠正、数字优先
const assert=require('assert');
const {parseReceipt}=require('../docs/parser.js');
const lines=[
 'Port Coquitlam #255','***START OF PRE-SCANNED ITEMS***',
 '8 326031 CHICKEN ST 16.49','5 6262016 %#xKS BAT» 23.99 GP','695035 ORGANIGZHOMO 9.49','ENVIRO FEE C 0.07','DEPOSIT CL 0.10','30859 CBTTA 9 GRN 6.99','31574 PORK BELLY 33.78',
 '***END OF PRE-SCANNED ITEMS***','TOTAL NUMBER OF PRE-SCANNED ITEMS= 5','SUBTOTAL 90.91','TAX 2.88','AUTH #: 2004Z 2026/09/08 09:37:33','AMOUNT: $93.79','MasterCard 93.79'
].map(s=>({text:s,conf:0.59}));
const r=parseReceipt(lines);
assert.strictEqual(r.store_code,'255'); assert.strictEqual(r.purchase_date,'2026-09-08');
assert.strictEqual(r.product_count,5); assert.strictEqual(r.count_mismatch,false);
assert.deepStrictEqual(r.items.map(i=>i.item_code),['326031','6262016','695035','30859','31574']);
assert.deepStrictEqual(r.items.map(i=>i.price),[16.49,23.99,9.49,6.99,33.78]);
assert.strictEqual(r.items[0].item_name,'CHICKEN STRP'); assert.strictEqual(r.items[1].item_name,'KS BATH');
assert.strictEqual(r.subtotal,90.91); assert.strictEqual(r.items_sum,90.74); assert.strictEqual(r.amount_diff,0.17);
console.log('test_new_receipt_js: PASS 5/5 codes+prices, names corrected:',r.items.map(i=>i.item_name).join(' | '));
