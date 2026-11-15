const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync('src/web/static/app.js', 'utf8');
function setup(fetch) {
  let blob;
  const context = { Blob, TextEncoder, URL: {createObjectURL(b) {blob=b; return 'blob:test';}, revokeObjectURL() {}},
    document: {createElement() {return {click(){},remove(){}};},body:{appendChild(){}}},
    showToast(){}, track(){}, setTimeout(){}, fetch };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('  function parseIsoDate'), source.indexOf('  function fetchOshiSummary')),context);
  return {context, blob:()=>blob};
}
test('single, bulk and changed release dates retain product identity', async()=>{
  const {context:c,blob} = setup();
  const a={item_id:'a',oshi_id:19,title:'日本語の長い商品名'.repeat(20),sales_date_iso:'2026-11-20',sales_date_precision:'day',url:'https://books.rakuten.co.jp/a'};
  const b={...a,item_id:'b'};
  c.downloadIcsCards([a,b],'test');
  let text=await blob().text();
  const unfolded=text.replace(/\r\n /g,'');
  const uids=unfolded.match(/UID:[^\r]+/g);
  assert.equal(new Set(uids).size,2);
  text.split('\r\n').forEach(line=>assert.ok(Buffer.byteLength(line)<=75));
  c.downloadIcsCards([{...a,sales_date_iso:'2026-11-21'}],'test');
  assert.equal((await blob().text()).replace(/\r\n /g,'').match(/UID:[^\r]+/)[0],uids[0]);
});
test('calendar reads all pages',async()=>{
  let calls=0;
  const {context:c}=setup(async url=>({ok:true,json:async()=>++calls===1?{items:Array(60).fill({}),total:65,truncated:true,next_offset:60}:{items:Array(5).fill({}),total:65,truncated:false,next_offset:65}}));
  const result=await c.fetchCalendarMonth(19,2026,11);
  assert.equal(result.items.length,65);
  assert.equal(calls,2);
});
test('failed second page rejects instead of silently exporting partial month',async()=>{
  let calls=0;
  const {context:c}=setup(async()=>++calls===1?{ok:true,json:async()=>({items:[{}],truncated:true,next_offset:1})}:{ok:false});
  await assert.rejects(()=>c.fetchCalendarMonth(19,2026,11));
});
