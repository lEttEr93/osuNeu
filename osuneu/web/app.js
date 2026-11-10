const $ = id => document.getElementById(id);
if(new URLSearchParams(location.search).has('desktop')){document.documentElement.dataset.desktop='true';$('saveStatus').textContent='自动保存在桌面应用';}
const state = {maps:[], map:null, time:0, playing:false, rate:1, start:0, end:0, view:0, span:10000, annotations:[], tags:new Set(), editing:null, confidence:2, checked:false, annotator:'', mods:'NM'};
let audioURL=null, lastFrame=performance.now(), drag=null;
const colors=['#c4f277','#ff8fbd','#80caff','#cab0ff','#ffcc80','#7fdfcf'];
const tagNames = new Map([['jump','跳 / jump'],['stream','串 / stream'],['tech','tech'],['alt','alt'],['precision','precision'],['reading','reading'],['uncertain','不确定']]);
const sessionKey='osuneu.session.v1';
function loadSession(){try{const s=JSON.parse(localStorage.getItem(sessionKey)||'{}');if(typeof s.annotator==='string')state.annotator=s.annotator.slice(0,40);if(typeof s.mods==='string')state.mods=s.mods;}catch{}}
function saveSession(){try{localStorage.setItem(sessionKey,JSON.stringify({annotator:state.annotator,mods:state.mods}));}catch{}}
function fmt(ms){ms=Math.max(0,Math.round(ms));return `${String(Math.floor(ms/60000)).padStart(2,'0')}:${String(Math.floor(ms/1000)%60).padStart(2,'0')}.${String(ms%1000).padStart(3,'0')}`;}
function parseTime(value){const p=value.trim().split(':');if(p.length>2||p.some(v=>v===''||!Number.isFinite(Number(v))))return NaN;return p.length===2?(Number(p[0])*60+Number(p[1]))*1000:Number(p[0])*1000;}
const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
const duration=()=>state.map?.duration||10000;
function status(text){$('status').textContent=text;}
function storageKey(){return `osuneu.annotations.v1.${state.map.id}`;}
function persist(){try{localStorage.setItem(storageKey(),JSON.stringify({durationMs:duration(),annotations:state.annotations}));$('saveStatus').textContent=document.documentElement.dataset.desktop?'已自动保存在桌面应用':'已自动保存在当前浏览器';}catch{$('saveStatus').textContent='自动保存失败，请导出 JSON';}}
function seek(ms){state.time=clamp(ms,0,duration());const a=$('audio');if(a.src&&Number.isFinite(a.duration))a.currentTime=Math.min(state.time/1000,a.duration);updateTime();}
function updateTime(){$('time').value=fmt(state.time);$('total').textContent=`/ ${fmt(duration())}`;}
function pause(){state.playing=false;$('audio').pause();$('play').textContent='▶ 播放';}
async function play(){if(!state.map)return;if(state.time>=duration())seek(0);state.playing=true;lastFrame=performance.now();$('play').textContent='Ⅱ 暂停';const a=$('audio');if(a.src&&state.time/1000<a.duration){a.playbackRate=state.rate;try{await a.play();}catch{status('音频无法播放，仍可进行无声预览');}}}
function setAudio(url){const a=$('audio');a.pause();a.removeAttribute('src');a.load();if(url){a.src=url;a.load();}a.onloadedmetadata=()=>{if(state.map){state.map.duration=Math.max(state.map.duration,a.duration*1000);seek(state.time);updatePan();}};}
function updateSelection(){const valid=state.end>state.start;const count=state.map?.objects.filter(o=>o.time>=state.start&&o.time<=state.end).length||0;$('start').value=fmt(state.start);$('end').value=fmt(state.end);$('selectionInfo').textContent=valid?`${((state.end-state.start)/1000).toFixed(3)} 秒 · ${count} 个物件起点`:'先选择一个时间区间';}
function renderTags(){const root=$('tags');root.replaceChildren();for(const [id,label] of tagNames){const b=document.createElement('button');b.textContent=label;b.className=state.tags.has(id)?'active':'';b.setAttribute('aria-pressed',state.tags.has(id));b.onclick=()=>{state.tags.has(id)?state.tags.delete(id):state.tags.add(id);renderTags();};root.append(b);}}
function cancelEdit(){state.editing=null;state.tags.clear();state.confidence=2;state.checked=false;$('note').value='';$('confidence').value='2';$('checked').checked=false;$('save').textContent='保存标注';$('cancel').hidden=true;renderTags();renderAnnotations();}
function editAnnotation(a){state.start=a.startMs;state.end=a.endMs;state.tags=new Set(a.labels);state.confidence=Number(a.confidence)||2;state.checked=!!a.checked;state.editing=a.id;$('note').value=a.note||'';$('confidence').value=String(state.confidence);$('checked').checked=state.checked;$('save').textContent='更新标注';$('cancel').hidden=false;seek(a.startMs);ensureVisible();updateSelection();renderTags();renderAnnotations();}
function renderAnnotations(){const root=$('annotations');root.replaceChildren();$('count').textContent=state.annotations.length;if(!state.annotations.length){const p=document.createElement('p');p.className='hint';p.textContent='还没有标注。选中区间后添加第一条。';root.append(p);return;}for(const a of [...state.annotations].sort((a,b)=>a.startMs-b.startMs)){const card=document.createElement('div');card.className='annotation'+(a.id===state.editing?' editing':'');const range=document.createElement('div');range.className='range';range.textContent=`${fmt(a.startMs)} → ${fmt(a.endMs)}`;const labels=document.createElement('div');labels.className='labels';labels.textContent=a.labels.length?a.labels.map(v=>tagNames.get(v)||v).join(' · '):'（无标签 · 已检查）';const meta=document.createElement('div');meta.className='meta';const badge=document.createElement('span');badge.className='badge';badge.textContent=`${(state.map?.objects||[]).filter(o=>o.time>=a.startMs&&o.time<=a.endMs).length} 物件 · 确信度 ${a.confidence||2}`;const ok=document.createElement('span');ok.className='badge'+(a.checked?' checked':'');ok.textContent=a.checked?'已完整检查':'未勾选检查';meta.append(badge,ok);card.append(range,labels,meta);if(a.note){const p=document.createElement('p');p.textContent=a.note;card.append(p);}card.onclick=()=>editAnnotation(a);const preview=document.createElement('button');preview.textContent='循环试听';preview.onclick=e=>{e.stopPropagation();editAnnotation(a);$('loop').checked=true;play();};const del=document.createElement('button');del.textContent='删除';del.onclick=e=>{e.stopPropagation();state.annotations=state.annotations.filter(v=>v.id!==a.id);if(state.editing===a.id)cancelEdit();persist();renderAnnotations();};card.append(preview,del);root.append(card);}}
function saveAnnotation(){if(!state.map)return status('请先打开谱面');if(state.end<=state.start)return status('终点需要晚于起点');if(!state.tags.size&&!state.checked)return status('请选择标签，或勾选「已完整检查」再保存');const now=new Date().toISOString();const prev=state.editing?state.annotations.find(v=>v.id===state.editing):null;const a={id:state.editing||crypto.randomUUID(),startMs:Math.round(state.start),endMs:Math.round(state.end),labels:[...state.tags],confidence:Number($('confidence').value)||2,checked:!!state.checked,note:$('note').value.trim(),annotator:state.annotator,mods:$('mods').value,createdAt:prev?.createdAt||now,updatedAt:now};const index=state.annotations.findIndex(v=>v.id===a.id);if(index>=0)state.annotations[index]=a;else state.annotations.push(a);persist();cancelEdit();status(a.checked&&!a.labels.length?'已保存「已检查、无此标签」的片段':'已保存标注；可以继续选择下一个片段');}
function switchMap(index){pause();state.map=state.maps[index];state.time=state.start=state.end=state.view=0;state.span=duration();state.annotations=[];try{const saved=JSON.parse(localStorage.getItem(storageKey())||'[]');if(Number.isFinite(saved.durationMs)&&saved.durationMs>0&&saved.durationMs<86400000)state.map.duration=Math.max(state.map.duration,saved.durationMs);state.annotations=validateAnnotations(Array.isArray(saved)?saved:saved.annotations);}catch{status('本地标注无法读取，可以重新导入 JSON');}for(const a of state.annotations)for(const label of a.labels)if(!tagNames.has(label))tagNames.set(label,label);cancelEdit();for(const o of state.map.objects)if(o.kind==='slider')o.path=sliderPath(o);$('empty').hidden=true;$('title').textContent=`${state.map.artist} — ${state.map.title}`;$('metadata').textContent=`${state.map.creator} · ${state.map.objects.length} 物件 · CS ${state.map.settings.CircleSize} / AR ${state.map.settings.ApproachRate} / OD ${state.map.settings.OverallDifficulty}`;setAudio(state.map.audioUrl||null);$('difficulty').value=index;ddMap.get('difficulty')?.label();updateTime();updateSelection();updatePan();if(!state.map.audioUrl)status('谱面已打开；单独的 .osu 可通过“添加音频”选择音乐');else status('谱包已打开，音乐已载入');}
function loadMaps(maps){state.maps=maps;const select=$('difficulty');select.replaceChildren();maps.forEach((m,i)=>{const o=document.createElement('option');o.value=i;o.textContent=m.version;select.append(o);});switchMap(0);}
async function openFile(file){if(!file)return;status('正在读取谱面…');try{const response=await fetch('/api/open',{method:'POST',headers:{'X-Filename':encodeURIComponent(file.name)},body:file});const data=await response.json();if(!response.ok)throw Error(data.error||'打开失败');loadMaps(data.maps);}catch(e){status(`打开失败：${e.message}`);}}
function updatePan(){state.span=clamp(state.span,Math.min(500,duration()),duration());state.view=clamp(state.view,0,Math.max(0,duration()-state.span));$('pan').value=duration()===state.span?0:state.view/(duration()-state.span)*1000;}
function ensureVisible(){if(state.time<state.view||state.time>state.view+state.span){state.view=state.time-state.span*.3;updatePan();}}
function zoom(factor,anchor=.5){const t=state.view+state.span*anchor;state.span*=factor;state.span=clamp(state.span,Math.min(500,duration()),duration());state.view=t-state.span*anchor;updatePan();}
function canvasContext(canvas){const rect=canvas.getBoundingClientRect(),dpr=devicePixelRatio||1;const w=Math.round(rect.width*dpr),h=Math.round(rect.height*dpr);if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}const c=canvas.getContext('2d');c.setTransform(dpr,0,0,dpr,0,0);c.clearRect(0,0,rect.width,rect.height);return [c,rect.width,rect.height];}
function bezier(points,t){let p=points.map(v=>[...v]);while(p.length>1)p=p.slice(0,-1).map((v,i)=>[v[0]*(1-t)+p[i+1][0]*t,v[1]*(1-t)+p[i+1][1]*t]);return p[0];}
function sliderPath(o){const pts=o.points;let out=[];if(o.curve==='L')out=pts;else if(o.curve==='P'&&pts.length===3){const [a,b,c]=pts;const d=2*(a[0]*(b[1]-c[1])+b[0]*(c[1]-a[1])+c[0]*(a[1]-b[1]));if(Math.abs(d)>1e-5){const sq=p=>p[0]**2+p[1]**2;const center=[(sq(a)*(b[1]-c[1])+sq(b)*(c[1]-a[1])+sq(c)*(a[1]-b[1]))/d,(sq(a)*(c[0]-b[0])+sq(b)*(a[0]-c[0])+sq(c)*(b[0]-a[0]))/d];const angle=p=>Math.atan2(p[1]-center[1],p[0]-center[0]);const tau=Math.PI*2,norm=x=>(x%tau+tau)%tau;const start=angle(a),mid=norm(angle(b)-start),end=norm(angle(c)-start);const sweep=mid<=end?end:end-tau;const r=Math.hypot(a[0]-center[0],a[1]-center[1]);out=Array.from({length:101},(_,i)=>[center[0]+r*Math.cos(start+sweep*i/100),center[1]+r*Math.sin(start+sweep*i/100)]); }else out=pts;}else if(o.curve==='C'){for(let i=0;i<pts.length-1;i++){const a=pts[Math.max(0,i-1)],b=pts[i],c=pts[i+1],d=pts[Math.min(pts.length-1,i+2)];for(let j=0;j<25;j++){const t=j/25;out.push([0,1].map(k=>.5*((2*b[k])+(-a[k]+c[k])*t+(2*a[k]-5*b[k]+4*c[k]-d[k])*t*t+(-a[k]+3*b[k]-3*c[k]+d[k])*t*t*t)));}}out.push(pts.at(-1));}else{let segment=[pts[0]];for(let i=1;i<pts.length;i++){segment.push(pts[i]);if(i===pts.length-1||(pts[i][0]===pts[i+1][0]&&pts[i][1]===pts[i+1][1])){for(let j=0;j<=60;j++)out.push(bezier(segment,j/60));segment=[pts[i]];if(i<pts.length-1)i++;}}}
    const path=[out[0]||[o.x,o.y]];let length=0;for(let i=1;i<out.length;i++){const a=path.at(-1),b=out[i],dist=Math.hypot(b[0]-a[0],b[1]-a[1]);if(dist<1e-8)continue;if(length+dist>=o.length){const f=(o.length-length)/dist;path.push([a[0]+(b[0]-a[0])*f,a[1]+(b[1]-a[1])*f]);length=o.length;break;}path.push(b);length+=dist;}if(length<o.length&&path.length>1){const a=path.at(-2),b=path.at(-1),d=Math.hypot(b[0]-a[0],b[1]-a[1]);if(d)path.push([b[0]+(b[0]-a[0])*(o.length-length)/d,b[1]+(b[1]-a[1])*(o.length-length)/d]);}const cumulative=[0];for(let i=1;i<path.length;i++)cumulative.push(cumulative.at(-1)+Math.hypot(path[i][0]-path[i-1][0],path[i][1]-path[i-1][1]));return {points:path,cumulative,total:cumulative.at(-1)};}
function pathPosition(o,f){const p=o.path;const target=clamp(f,0,1)*p.total;let i=p.cumulative.findIndex(v=>v>=target);if(i<=0)return p.points[0];const a=p.points[i-1],b=p.points[i],d=p.cumulative[i]-p.cumulative[i-1],r=d?(target-p.cumulative[i-1])/d:0;return [a[0]+(b[0]-a[0])*r,a[1]+(b[1]-a[1])*r];}
function circle(c,x,y,r,fill,stroke,width=2){c.beginPath();c.arc(x,y,Math.max(.1,r),0,Math.PI*2);if(fill){c.fillStyle=fill;c.fill();}if(stroke){c.strokeStyle=stroke;c.lineWidth=width;c.stroke();}}
function lowerBound(objects,time){let l=0,r=objects.length;while(l<r){const m=(l+r)>>1;if(objects[m].time<time)l=m+1;else r=m;}return l;}
function drawField(){const [c,w,h]=canvasContext($('playfield'));if(!state.map)return;const scale=Math.min(w/640,h/480);c.translate((w-512*scale)/2,(h-384*scale)/2);c.scale(scale,scale);c.strokeStyle='#ffffff06';c.lineWidth=1;for(let x=0;x<=512;x+=64){c.beginPath();c.moveTo(x,0);c.lineTo(x,384);c.stroke();}const ar=state.map.settings.ApproachRate,preempt=ar<5?1800-120*ar:1200-150*(ar-5);const r=54.4-4.48*state.map.settings.CircleSize;const objects=state.map.objects;const end=lowerBound(objects,state.time+preempt);let visible=[];for(let i=0;i<end;i++){const o=objects[i];if(o.end>=state.time-180)visible.push(o);}for(const o of visible.reverse()){const age=state.time-o.time;const alpha=age<0?clamp((age+preempt)/Math.min(400,preempt),0,1):o.kind==='circle'?clamp(1-age/180,0,1):clamp(1-Math.max(0,state.time-o.end)/180,0,1);c.globalAlpha=alpha;const color=colors[Math.floor(o.index/8)%colors.length];if(o.kind==='spinner'){circle(c,256,192,130,'#ffffff05',color,3);c.fillStyle=color;c.font='18px system-ui';c.textAlign='center';c.fillText('SPINNER',256,198);continue;}if(o.kind==='slider'){const points=o.path.points;c.lineCap=c.lineJoin='round';c.beginPath();points.forEach((p,i)=>i?c.lineTo(...p):c.moveTo(...p));c.strokeStyle=color;c.lineWidth=r*2+3;c.stroke();c.strokeStyle='#252d3e';c.lineWidth=r*2-2;c.stroke();const tail=points.at(-1);circle(c,...tail,r*.7,'#242b3b',color,1.5);if(o.repeats>1){c.fillStyle=color;c.font='20px system-ui';c.textAlign='center';c.fillText('↶',tail[0],tail[1]+6);}if(age>=0&&state.time<=o.end){const progress=age/Math.max(1,o.end-o.time)*o.repeats;let f=progress%1;if(Math.floor(progress)%2)f=1-f;const p=pathPosition(o,f);circle(c,...p,r*.9,'#ffffff20','#fff',3);}}circle(c,o.x,o.y,r,'#273044',color,2.5);c.fillStyle='#f4f6ff';c.font=`${Math.max(12,r*.85)}px system-ui`;c.textAlign='center';c.textBaseline='middle';c.fillText(String(o.number),o.x,o.y);if(age<0)circle(c,o.x,o.y,r*(1+2.2*(-age/preempt)),null,color,1.5);}
    c.globalAlpha=1;
}
function drawTimeline(){const [c,w,h]=canvasContext($('timeline'));const x=t=>(t-state.view)/state.span*w;c.font='10px monospace';c.textBaseline='top';const target=state.span/(w/90),steps=[100,200,500,1000,2000,5000,10000,15000,30000,60000,120000,300000,600000];const step=steps.find(v=>v>=target)||600000;for(let t=Math.ceil(state.view/step)*step;t<=state.view+state.span;t+=step){const px=x(t);c.strokeStyle='#303543';c.beginPath();c.moveTo(px,26);c.lineTo(px,h);c.stroke();c.fillStyle='#8a93a8';c.fillText(fmt(t),px+5,9);}if(state.map){const objects=state.map.objects;const first=lowerBound(objects,state.view);const last=lowerBound(objects,state.view+state.span);for(let i=Math.max(0,first-1);i<last;i++){const o=objects[i],px=x(o.time);c.fillStyle=o.kind==='circle'?'#a7bcd6':o.kind==='slider'?'#c4f277':'#ff8fbd';c.fillRect(px,43,Math.max(2,x(o.end)-px),25);}}
    state.annotations.forEach((a,i)=>{if(a.endMs<state.view||a.startMs>state.view+state.span)return;const lane=i%3;c.fillStyle=colors[i%colors.length]+'55';c.fillRect(x(a.startMs),82+lane*24,Math.max(2,x(a.endMs)-x(a.startMs)),21);c.save();c.beginPath();c.rect(x(a.startMs),82+lane*24,Math.max(2,x(a.endMs)-x(a.startMs)),21);c.clip();c.fillStyle='#eff4ff';c.fillText(a.labels.join(' + '),x(a.startMs)+5,87+lane*24);c.restore();});if(state.end>state.start){c.fillStyle='#c4f27716';c.fillRect(x(state.start),27,x(state.end)-x(state.start),h-27);}for(const [t,label] of [[state.start,'I'],[state.end,'O']]){const px=x(t);c.strokeStyle='#c4f277';c.lineWidth=1.5;c.beginPath();c.moveTo(px,27);c.lineTo(px,h);c.stroke();c.fillStyle='#c4f277';c.fillText(label,px+4,h-15);}const px=x(state.time);c.strokeStyle='#ff8fbd';c.lineWidth=2;c.beginPath();c.moveTo(px,25);c.lineTo(px,h);c.stroke();c.fillStyle='#ff8fbd';c.beginPath();c.moveTo(px-5,22);c.lineTo(px+5,22);c.lineTo(px,29);c.fill();}
function frame(now){const dt=now-lastFrame;lastFrame=now;if(state.playing){const a=$('audio');state.time=a.src&&!a.paused&&!a.ended?a.currentTime*1000:state.time+dt*state.rate;if($('loop').checked&&state.end>state.start&&state.time>=state.end)seek(state.start);else if(state.time>=duration()){seek(duration());pause();}ensureVisible();updateTime();}drawField();drawTimeline();requestAnimationFrame(frame);}
function timelineTime(e){const r=$('timeline').getBoundingClientRect();return clamp(state.view+(e.clientX-r.left)/r.width*state.span,0,duration());}
function beginTimelineDrag(e){
    if(!state.map||![0,1,2].includes(e.button))return;
    if(e.currentTarget===$('pan')&&e.button!==1)return;
    e.preventDefault();pause();
    const r=$('timeline').getBoundingClientRect(),t=timelineTime(e);
    const threshold=8/r.width*state.span;
    const mode=e.button===1?'pan':e.button===2||e.shiftKey?'select':Math.abs(t-state.start)<threshold?'start':Math.abs(t-state.end)<threshold?'end':'seek';
    drag={mode,anchor:t,clientX:e.clientX,view:state.view,span:state.span,width:r.width,pointerId:e.pointerId,target:e.currentTarget};
    e.currentTarget.setPointerCapture(e.pointerId);
    if(mode!=='pan')seek(t);
    if(mode==='pan')e.currentTarget.classList.add('panning');
}
function moveTimelineDrag(e){
    if(!drag||drag.pointerId!==e.pointerId)return;
    e.preventDefault();
    if(drag.mode==='pan'){
        state.view=drag.view-(e.clientX-drag.clientX)/drag.width*drag.span;
        updatePan();return;
    }
    const t=timelineTime(e);
    if(drag.mode==='select'){
        if(Math.abs(e.clientX-drag.clientX)<3&&!drag.moved)return;
        drag.moved=true;state.start=Math.min(drag.anchor,t);state.end=Math.max(drag.anchor,t);
    }else if(drag.mode!=='seek')state[drag.mode]=t;
    seek(t);updateSelection();
}
function endTimelineDrag(e){
    if(!drag||drag.pointerId!==e.pointerId)return;
    if(e.type==='pointerup')moveTimelineDrag(e);
    const target=drag.target;target.classList.remove('panning');
    if(target.hasPointerCapture(e.pointerId))target.releasePointerCapture(e.pointerId);
    drag=null;
}
function wheelTimeline(e){
    e.preventDefault();if(!state.map||e.deltaY===0)return;
    const r=e.currentTarget.getBoundingClientRect();
    zoom(e.deltaY>0?1.2:1/1.2,clamp((e.clientX-r.left)/r.width,0,1));
}
for(const id of ['timeline','pan']){
    const element=$(id);
    element.addEventListener('pointerdown',beginTimelineDrag);
    element.addEventListener('pointermove',moveTimelineDrag);
    element.addEventListener('pointerup',endTimelineDrag);
    element.addEventListener('pointercancel',endTimelineDrag);
    element.addEventListener('lostpointercapture',()=>{element.classList.remove('panning');drag=null;});
    element.addEventListener('auxclick',e=>{if(e.button===1)e.preventDefault();});
    element.addEventListener('contextmenu',e=>e.preventDefault());
    element.addEventListener('wheel',wheelTimeline,{passive:false});
}
$('random').onclick=async()=>{const b=$('random');b.disabled=true;status('正在随机抽一张并下载…');const ctl=new AbortController();const timer=setTimeout(()=>ctl.abort(),120000);try{const r=await fetch('/api/random',{method:'POST',signal:ctl.signal});const d=await r.json();if(!r.ok)throw Error(d.error||'下载失败');loadMaps(d.maps);status(`已下载 set ${d.set.id} · ${d.set.artist} — ${d.set.title}（${d.maps.length} 张难度）`);}catch(e){status(e.name==='AbortError'?'随机失败：超时，再点一次试试':`随机失败：${e.message}`);}finally{clearTimeout(timer);b.disabled=false;}};
$('open').onclick=()=>$('file').click();$('file').onchange=e=>{openFile(e.target.files[0]);e.target.value='';};$('audioOpen').onclick=()=>$('audioFile').click();$('audioFile').onchange=e=>{if(!state.map)return status('请先打开谱面');const file=e.target.files[0];if(file){pause();if(audioURL)URL.revokeObjectURL(audioURL);audioURL=URL.createObjectURL(file);setAudio(audioURL);status(`已添加音频：${file.name}`);}e.target.value='';};$('difficulty').onchange=e=>switchMap(Number(e.target.value));
$('play').onclick=()=>state.playing?pause():play();$('back').onclick=()=>seek(state.time-1000);$('forward').onclick=()=>seek(state.time+1000);$('rate').onchange=e=>{state.rate=Number(e.target.value);$('audio').playbackRate=state.rate;};$('time').onchange=e=>{const t=parseTime(e.target.value);if(Number.isFinite(t))seek(t);else{status('时间格式：分:秒.毫秒，或秒数');updateTime();}};
for(const key of ['start','end']){$(key).onchange=e=>{const t=parseTime(e.target.value);if(Number.isFinite(t))state[key]=clamp(t,0,duration());else status('时间格式：分:秒.毫秒，或秒数');updateSelection();};$(key==='start'?'setStart':'setEnd').onclick=()=>{state[key]=state.time;updateSelection();};}
$('zoomIn').onclick=()=>zoom(.5);$('zoomOut').onclick=()=>zoom(2);$('fit').onclick=()=>{state.span=duration();state.view=0;updatePan();};$('pan').oninput=e=>{state.view=Number(e.target.value)/1000*(duration()-state.span);};$('save').onclick=saveAnnotation;$('cancel').onclick=cancelEdit;
$('addTag').onclick=()=>{const value=$('customTag').value.trim();if(value&&value.length<=60){tagNames.set(value,value);state.tags.add(value);$('customTag').value='';renderTags();}};
function validateAnnotations(items){if(!Array.isArray(items)||items.length>100000)throw Error('标注列表无效');const ids=new Set();return items.map(a=>{const checked=!!a.checked;if(!Number.isFinite(a.startMs)||!Number.isFinite(a.endMs)||a.startMs<0||a.endMs<=a.startMs||a.endMs>duration()+1||!Array.isArray(a.labels)||(!a.labels.length&&!checked)||a.labels.some(v=>typeof v!=='string'||!v.trim()||v.length>60)||typeof a.note!=='string')throw Error('标注包含无效区间或标签');const id=typeof a.id==='string'&&!ids.has(a.id)?a.id:crypto.randomUUID();ids.add(id);const confidence=Number(a.confidence);return {id,startMs:a.startMs,endMs:a.endMs,labels:[...new Set(a.labels)],confidence:Number.isFinite(confidence)&&confidence>=1&&confidence<=3?confidence:2,checked,note:a.note,annotator:typeof a.annotator==='string'?a.annotator:'',mods:typeof a.mods==='string'?a.mods:'NM',createdAt:typeof a.createdAt==='string'?a.createdAt:undefined,updatedAt:typeof a.updatedAt==='string'?a.updatedAt:undefined};});}
function download(name,data){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function beatAt(t){const tm=state.map?.timing||[];let beat=500;for(const p of tm){if(p[0]>t)break;if(p[2])beat=p[1];}return beat>0?beat:500;}
function segmentStats(objs){if(!objs.length)return{medianDtMs:0,medianDistPx:0,beatMs:500,snap:0};const beat=beatAt(objs[0].time);if(objs.length<2)return{medianDtMs:0,medianDistPx:0,beatMs:Math.round(beat),snap:0};const dts=[],ds=[];for(let i=1;i<objs.length;i++){dts.push(objs[i].time-objs[i-1].time);ds.push(Math.hypot(objs[i].x-objs[i-1].x,objs[i].y-objs[i-1].y));}const med=a=>[...a].sort((x,y)=>x-y)[Math.floor(a.length/2)];const dt=med(dts);return{medianDtMs:Math.round(dt),medianDistPx:Math.round(med(ds)),beatMs:Math.round(beat),snap:+(dt/beat).toFixed(3)};}
$('export').onclick=()=>{if(!state.map)return status('请先打开谱面');const s=state.map.settings||{};download(`osuneu-${state.map.id.slice(0,12)}.json`,{schema:'osuneu.annotations',version:2,timeUnit:'ms',boundaryMode:'free',createdAt:new Date().toISOString(),app:{name:'osu!neu annotator',schemaVersion:2},session:{annotator:state.annotator,mods:$('mods').value},beatmap:{sha256:state.map.id,filename:state.map.filename,title:state.map.title,artist:state.map.artist,version:state.map.version,creator:state.map.creator,durationMs:duration(),cs:s.CircleSize,ar:s.ApproachRate,od:s.OverallDifficulty,bpm:state.map.bpm||0},annotations:state.annotations.map(a=>{const objs=state.map.objects.filter(o=>o.time>=a.startMs&&o.time<=a.endMs);return {...a,objectIndices:objs.map(o=>o.index),objectCount:objs.length,stats:segmentStats(objs)};})});status('已导出 v2 标注 JSON');};
$('import').onclick=()=>$('jsonFile').click();$('jsonFile').onchange=async e=>{try{if(!state.map)throw Error('请先打开对应谱面');const file=e.target.files[0];if(!file)return;const data=JSON.parse(await file.text());if(data.schema!=='osuneu.annotations'||![1,2].includes(data.version))throw Error('不支持的标注格式');if(data.beatmap?.sha256!==state.map.id)throw Error('标注与当前谱面不匹配，请打开原谱面');if(Number.isFinite(data.beatmap.durationMs)&&data.beatmap.durationMs>0&&data.beatmap.durationMs<86400000)state.map.duration=Math.max(state.map.duration,data.beatmap.durationMs);const annotations=validateAnnotations(data.annotations);const existing=new Map(state.annotations.map(a=>[a.id,a]));for(const a of annotations){existing.set(a.id,a);for(const label of a.labels)if(!tagNames.has(label))tagNames.set(label,label);}state.annotations=[...existing.values()];persist();cancelEdit();status(`已导入 ${annotations.length} 条标注`);}catch(err){status(`导入失败：${err.message}`);}finally{e.target.value='';}};
document.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.ctrlKey){e.preventDefault();saveAnnotation();return;}if(['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName))return;if(e.code==='Space'){e.preventDefault();state.playing?pause():play();}else if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();seek(state.time+(e.key==='ArrowLeft'?-1:1)*(e.shiftKey?1000:100));ensureVisible();}else if(e.key.toLowerCase()==='i'){state.start=state.time;updateSelection();}else if(e.key.toLowerCase()==='o'){state.end=state.time;updateSelection();}else if(e.key==='Enter'&&e.ctrlKey){e.preventDefault();saveAnnotation();}});
document.addEventListener('dragover',e=>{e.preventDefault();document.body.classList.add('dragging');});document.addEventListener('dragleave',e=>{if(!e.relatedTarget)document.body.classList.remove('dragging');});document.addEventListener('drop',e=>{e.preventDefault();document.body.classList.remove('dragging');openFile(e.dataTransfer.files[0]);});
$('demo').onclick=()=>{const objects=[];for(let i=0;i<56;i++){const stream=i>=24&&i<48;const t=i<24?1500+i*500:i<48?13500+(i-24)*125:17000+(i-48)*500;objects.push({index:i,number:i%8+1,time:t,end:t,x:stream?160+Math.sin(i*.55)*70:(i%2?390:120),y:stream?170+Math.cos(i*.55)*70:100+(i%3)*85,kind:'circle'});}loadMaps([{id:'demo-v1',title:'Pattern study',artist:'osu!neu',creator:'Demo / 不用于训练',version:'Jump → Stream',filename:'demo.osu',settings:{CircleSize:4,ApproachRate:8,OverallDifficulty:7},duration:22500,objects,timing:[]}]);status('演示谱面 · 无音频；打开真实谱包可同步音乐');};
// Native <select> popups are rendered by Qt as separate windows; on this setup
// (DPR 1.5) they come out wider than their content and leave a growing white
// strip. Replace them with an in-page listbox: same .value/.change contract,
// no native popup window at all.
const ddMap=new Map();
function enhanceSelect(sel){
  if(!sel||ddMap.has(sel.id))return;
  const wrap=document.createElement('div');wrap.className='dd';
  const btn=document.createElement('button');btn.type='button';btn.className='dd-button';
  btn.setAttribute('aria-haspopup','listbox');btn.setAttribute('aria-expanded','false');
  const list=document.createElement('div');list.className='dd-list';list.hidden=true;list.setAttribute('role','listbox');
  sel.parentNode.insertBefore(wrap,sel);wrap.append(btn,list,sel);sel.classList.add('dd-native');
  const label=()=>{const o=sel.options[sel.selectedIndex];btn.textContent=o?o.textContent:'—';};
  const close=()=>{list.hidden=true;btn.setAttribute('aria-expanded','false');document.removeEventListener('pointerdown',outside,true);};
  const outside=e=>{if(!wrap.contains(e.target))close();};
  const open=()=>{
    list.replaceChildren();
    [...sel.options].forEach((o,i)=>{const it=document.createElement('button');it.type='button';
      it.className='dd-option'+(i===sel.selectedIndex?' active':'');it.textContent=o.textContent;
      it.onclick=e=>{e.stopPropagation();sel.selectedIndex=i;sel.dispatchEvent(new Event('change',{bubbles:true}));close();label();};
      list.append(it);});
    list.hidden=false;btn.setAttribute('aria-expanded','true');document.addEventListener('pointerdown',outside,true);
  };
  btn.onclick=e=>{e.stopPropagation();list.hidden?open():close();};
  sel.addEventListener('change',label);
  wrap.addEventListener('keydown',e=>{if(e.key==='Escape')close();});
  label();
  ddMap.set(sel.id,{sel,btn,list,label,close});
}
for(const id of ['difficulty','rate','mods','confidence'])enhanceSelect($(id));
document.addEventListener('keydown',e=>{if(e.key==='Escape')for(const d of ddMap.values())d.close();});
loadSession();$('annotator').value=state.annotator;$('mods').value=state.mods;
$('annotator').oninput=e=>{state.annotator=e.target.value.slice(0,40);saveSession();};
$('mods').onchange=e=>{state.mods=e.target.value;saveSession();};
$('confidence').onchange=e=>{state.confidence=Number(e.target.value)||2;};
$('checked').onchange=e=>{state.checked=e.target.checked;};
renderTags();updateSelection();requestAnimationFrame(frame);
