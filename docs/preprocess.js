// 网页版预处理（纯 canvas, 不引入 OpenCV.js 以免页面太重）
// 思路对应电脑版 ocr_parser.py: 找小票轮廓 -> 裁剪/透视拉正 -> 放大 -> 灰度+对比, 另备一份二值化供二次识别。
'use strict';
function _otsu(hist,total){ let sum=0; for(let i=0;i<256;i++) sum+=i*hist[i]; let sumB=0,wB=0,max=-1,thr=127; for(let i=0;i<256;i++){ wB+=hist[i]; if(!wB) continue; const wF=total-wB; if(!wF) break; sumB+=i*hist[i]; const mB=sumB/wB,mF=(sum-sumB)/wF; const between=wB*wF*(mB-mF)*(mB-mF); if(between>max){max=between;thr=i;} } return thr; }
function _grayData(canvas){ const ctx=canvas.getContext('2d',{willReadFrequently:true}); const d=ctx.getImageData(0,0,canvas.width,canvas.height); const g=new Uint8Array(canvas.width*canvas.height); for(let i=0,p=0;i<d.data.length;i+=4,p++) g[p]=Math.round(0.299*d.data[i]+0.587*d.data[i+1]+0.114*d.data[i+2]); return g; }
function detectReceiptShape(gray,w,h){
  // Otsu 亮区中找最大连通区 = 小票纸面 (地毯亮斑是小块, 不会连成最大块)
  const hist=new Array(256).fill(0); for(const v of gray) hist[v]++;
  const thr=_otsu(hist,gray.length);
  const bright=new Uint8Array(w*h); for(let i=0;i<gray.length;i++) bright[i]=gray[i]>thr?1:0;
  const labels=new Int32Array(w*h); let next=0; let best={label:-1,area:0,x0:0,y0:0,x1:0,y1:0};
  const stack=[];
  for(let s=0;s<w*h;s++){
    if(!bright[s]||labels[s]) continue;
    next++; let area=0,x0=w,y0=h,x1=0,y1=0; stack.length=0; stack.push(s); labels[s]=next;
    while(stack.length){ const cur=stack.pop(); area++; const cx=cur%w, cy=(cur/w)|0; if(cx<x0)x0=cx; if(cx>x1)x1=cx; if(cy<y0)y0=cy; if(cy>y1)y1=cy;
      const nb=[cx>0?cur-1:-1,cx<w-1?cur+1:-1,cy>0?cur-w:-1,cy<h-1?cur+w:-1];
      for(const nbIdx of nb){ if(nbIdx>=0&&bright[nbIdx]&&!labels[nbIdx]){ labels[nbIdx]=next; stack.push(nbIdx); } } }
    if(area>best.area) best={label:next,area,x0,y0,x1,y1};
  }
  if(best.label<0||best.area<w*h*0.12||(best.y1-best.y0)<h*0.35||(best.x1-best.x0)<w*0.2) return null;
  function edge(yFrom,yTo,fromLeft){ const vals=[]; for(let y=yFrom;y<yTo;y++){ if(fromLeft){ for(let x=best.x0;x<=best.x1;x++) if(labels[y*w+x]===best.label){vals.push(x);break;} } else { for(let x=best.x1;x>=best.x0;x--) if(labels[y*w+x]===best.label){vals.push(x);break;} } } if(!vals.length) return fromLeft?best.x0:best.x1; vals.sort((a,b)=>a-b); return vals[Math.floor(vals.length/2)]; }
  const band=Math.max(4,Math.round((best.y1-best.y0)*0.04));
  const tl={x:edge(best.y0,Math.min(best.y0+band,h),true),y:best.y0};
  const tr={x:edge(best.y0,Math.min(best.y0+band,h),false),y:best.y0};
  const bl={x:edge(Math.max(best.y1-band,0),best.y1,true),y:best.y1};
  const br={x:edge(Math.max(best.y1-band,0),best.y1,false),y:best.y1};
  const topW=tr.x-tl.x, botW=br.x-bl.x;
  if(topW<w*0.15||botW<w*0.15||Math.abs(topW-botW)>w*0.35) return {box:{x:best.x0,y:best.y0,w:best.x1-best.x0,h:best.y1-best.y0}};
  return {quad:[tl,tr,br,bl]};
}
function _homographyDstToSrc(quad,outW,outH){
  // 解 dst(输出矩形) -> src(四边形) 单应矩阵 (3x3, h33=1)
  const dst=[[0,0],[outW,0],[outW,outH],[0,outH]];
  const A=[],b=[];
  for(let i=0;i<4;i++){ const [x,y]=dst[i], {x:u,y:v}=quad[i];
    A.push([x,y,1,0,0,0,-u*x,-u*y]); b.push(u);
    A.push([0,0,0,x,y,1,-v*x,-v*y]); b.push(v); }
  // 高斯消元
  const n=8; for(let c=0,r=0;c<n&&r<n;c++,r++){ let piv=r; for(let i=r;i<n;i++) if(Math.abs(A[i][c])>Math.abs(A[piv][c])) piv=i; if(Math.abs(A[piv][c])<1e-10){c--; continue;} [A[r],A[piv]]=[A[piv],A[r]]; [b[r],b[piv]]=[b[piv],b[r]]; for(let i=0;i<n;i++){ if(i!==r&&A[i][c]){ const f=A[i][c]/A[r][c]; for(let j=c;j<n;j++) A[i][j]-=f*A[r][j]; b[i]-=f*b[r]; } } }
  const h=new Array(8); for(let i=0;i<n;i++){ let piv=-1; for(let c=0;c<n;c++) if(Math.abs(A[i][c])>1e-9){piv=c;break;} h[piv]= piv>=0? b[i]/A[i][piv]:0; }
  return h;
}
async function preprocessReceipt(file){
  let bmp=null;
  try{ bmp=await createImageBitmap(file,{imageOrientation:'from-image'}); }catch(e){ try{ bmp=await createImageBitmap(file); }catch(e2){} }
  let srcCanvas;
  if(bmp){ srcCanvas=document.createElement('canvas'); const scale=Math.min(1,2000/bmp.width); srcCanvas.width=Math.round(bmp.width*scale); srcCanvas.height=Math.round(bmp.height*scale); srcCanvas.getContext('2d').drawImage(bmp,0,0,srcCanvas.width,srcCanvas.height); }
  else { const url=URL.createObjectURL(file); const img=new Image(); await new Promise((res,rej)=>{img.onload=res;img.onerror=rej;img.src=url;}); srcCanvas=document.createElement('canvas'); const scale=Math.min(1,2000/img.naturalWidth); srcCanvas.width=Math.round(img.naturalWidth*scale); srcCanvas.height=Math.round(img.naturalHeight*scale); srcCanvas.getContext('2d').drawImage(img,0,0,srcCanvas.width,srcCanvas.height); URL.revokeObjectURL(url); }
  const W=srcCanvas.width,H=srcCanvas.height;
  // detection 缩小图
  const smallScale=Math.min(1,500/W); const sw=Math.max(50,Math.round(W*smallScale)), sh=Math.max(50,Math.round(H*smallScale));
  const small=document.createElement('canvas'); small.width=sw; small.height=sh; small.getContext('2d').drawImage(srcCanvas,0,0,sw,sh);
  const graySmall=_grayData(small);
  const det2=detectReceiptShape(graySmall,sw,sh);
  let quad=null, box=null;
  if(det2&&det2.quad){ const kx=W/sw, ky=H/sh; quad=det2.quad.map(p=>({x:p.x*kx,y:p.y*ky})); }
  else if(det2&&det2.box){ const kx=W/sw, ky=H/sh; box={x:det2.box.x*kx,y:det2.box.y*ky,w:det2.box.w*kx,h:det2.box.h*ky}; }
  // 源灰度
  const srcGray=_grayData(srcCanvas);
  const outW=1400;
  let outH, sample;
  if(quad){
    const leftH=Math.hypot(quad[3].x-quad[0].x,quad[3].y-quad[0].y), rightH=Math.hypot(quad[2].x-quad[1].x,quad[2].y-quad[1].y);
    const topW=Math.hypot(quad[1].x-quad[0].x,quad[1].y-quad[0].y);
    outH=Math.round(outW*((leftH+rightH)/2)/topW); outH=Math.max(600,Math.min(4800,outH));
    const hmat=_homographyDstToSrc(quad,outW,outH);
    sample=(ox,oy)=>{ const den=hmat[6]*ox+hmat[7]*oy+1; const sx=(hmat[0]*ox+hmat[1]*oy+hmat[2])/den, sy=(hmat[3]*ox+hmat[4]*oy+hmat[5])/den; const ix=Math.round(sx),iy=Math.round(sy); if(ix<0||iy<0||ix>=W||iy>=H) return 255; return srcGray[iy*W+ix]; };
  } else {
    const bx=box?Math.max(0,box.x-20):0, by=box?Math.max(0,box.y-20):0, bw=box?Math.min(W-bx,box.w+40):W, bh=box?Math.min(H-by,box.h+40):H;
    outH=Math.round(outW*bh/bw); outH=Math.max(400,Math.min(4800,outH));
    sample=(ox,oy)=>{ const ix=Math.round(bx+ox/outW*bw), iy=Math.round(by+oy/outH*bh); return srcGray[Math.min(H-1,iy)*W+Math.min(W-1,ix)]; };
  }
  const out=new Uint8Array(outW*outH);
  for(let y=0;y<outH;y++) for(let x=0;x<outW;x++) out[y*outW+x]=sample(x,y);
  // 对比拉伸 (2%-98% 分位)
  const hist=new Array(256).fill(0); for(const v of out) hist[v]++;
  let lo=0,hi=255,cum=0; const total=out.length; for(let i=0;i<256;i++){cum+=hist[i]; if(cum>total*0.02){lo=i;break;}} cum=0; for(let i=255;i>=0;i--){cum+=hist[i]; if(cum>total*0.02){hi=i;break;}}
  const grayCanvas=document.createElement('canvas'); grayCanvas.width=outW; grayCanvas.height=outH; const gctx=grayCanvas.getContext('2d'); const gi=gctx.createImageData(outW,outH);
  const stretched=new Uint8Array(out.length);
  for(let i=0,p=0;i<out.length;i++,p+=4){ let v=Math.round((out[i]-lo)*255/Math.max(1,hi-lo)); v=v<0?0:v>255?255:v; stretched[i]=v; gi.data[p]=gi.data[p+1]=gi.data[p+2]=v; gi.data[p+3]=255; }
  gctx.putImageData(gi,0,0);
  // 二值版 (二次识别用)
  const hist2=new Array(256).fill(0); for(const v of stretched) hist2[v]++; const thr=_otsu(hist2,stretched.length);
  const otsuCanvas=document.createElement('canvas'); otsuCanvas.width=outW; otsuCanvas.height=outH; const octx=otsuCanvas.getContext('2d'); const oi=octx.createImageData(outW,outH);
  for(let i=0,p=0;i<stretched.length;i++,p+=4){ const v=stretched[i]>thr?255:0; oi.data[p]=oi.data[p+1]=oi.data[p+2]=v; oi.data[p+3]=255; }
  octx.putImageData(oi,0,0);
  if(typeof window!=='undefined') window.__lastPrepDebug={quad,box,outW,outH,srcW:W,srcH:H};
  return {grayCanvas,otsuCanvas,method:quad?'自动裁剪+拉正':'自动裁剪（未拉正）',found:!!(quad||box)};
}
function scoreParsed(r){
  let s=0; if(!r) return -99;
  s+=r.product_count*2;
  if(r.expected_item_count!==null&&r.expected_item_count!==undefined&&!r.count_mismatch) s+=6;
  if(r.total!==null&&r.total!==undefined) s+=3;
  if(r.store_code) s+=2; if(r.purchase_date) s+=2; if(r.subtotal!==null&&r.subtotal!==undefined) s+=2;
  if(r.amount_diff!==null&&r.amount_diff!==undefined){ if(Math.abs(r.amount_diff)<=0.25) s+=3; else if(Math.abs(r.amount_diff)>1) s-=3; }
  for(const it of r.items) if(it.price==='') s-=1;
  return s;
}
