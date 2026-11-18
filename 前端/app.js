const app=document.querySelector('#app');
const demo={article:'During exam week, the library moved its closing time from eight to ten. Some students used the extra time to study. Students who depended on the last bus still left at eight every evening.',question:'Which statement is supported by the report?',options:['The last bus began running two hours later.','All students stayed longer after the library extended its hours.','Students asked the library to open earlier during exam week.','Some students took advantage of the later closing time.'],answer:'D'};
const editor={name:'橙笺',image:'assets/office.png'};
let db={records:[]},booted=false;
let page='home',r=null,reading=false,scrollAt=0,noticeTimer;
function note(s){statusBox().textContent=s;clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>statusBox().textContent='',4500)}function statusBox(){return document.querySelector('#status')}
async function save(){if(!booted)return false;try{await saveState(db);return true}catch{note('浏览器保存失败，请检查存储空间后再试。');return false}}
const BASIS_LABEL={evidence:'当时圈了依据',elimination:'排除法',guess:'猜的',dont_remember:'记不清'};
const KIND_MAP={'范围':'scope','目的':'purpose','因果':'causality'};
const DIFF_LABEL={added:'多说了',omitted:'漏说了',shifted:'答偏了'};
const SENTENCE_PATTERN=/[^.!?。！？\n]+(?:[.!?。！？]+(?=\s|$)|$)|[^\n]+/g;
const MAX_ANALYSIS_EVIDENCE=10;
const ANALYSIS_MATERIALS='分析会发送原文、题干、四个选项、作答和圈选依据。';
const analysisRequests=new WeakMap();
function migrate(x){for(const rec of [...(x.records||[]),...(x.story?[x.story]:[])]){if(rec.forgot!==undefined){rec.basis=rec.forgot?'dont_remember':'evidence';delete rec.forgot}if(!rec.basis)rec.basis='evidence';delete rec.analyzing}}

function sentenceSpans(article){
  const spans=[];
  let previousEnd=0,offset=0;
  for(const match of article.matchAll(SENTENCE_PATTERN)){
    const text=match[0].trim();
    if(!text)continue;
    const startIndex=match.index+match[0].length-match[0].trimStart().length;
    // 后端用 Unicode 码点计数，JS 的字符串索引按 UTF-16 码元计数。
    const start=offset+Array.from(article.slice(previousEnd,startIndex)).length;
    const end=start+Array.from(text).length;
    spans.push({text,start,end});
    previousEnd=startIndex+text.length;
    offset=end;
  }
  return spans;
}

function compareChoice(record){
  if(!record.answer||!record.pick)return '';
  if(record.answer!==record.pick)return record.answer;
  const candidate=record.analysisOther;
  return candidate&&candidate!==record.pick&&[...'ABCD'].includes(candidate)?candidate:'';
}

function selectedMarks(record){
  return [...new Set([...record.marks,...record.later])];
}

function analysisPanel(a){return '<section class="analysis"><span class="label">自动分析 · 建议（可纠正）</span><ul class="diffs">'+a.differences.map(d=>'<li><b>'+DIFF_LABEL[d.kind]+'</b>　'+esc(d.detail_zh)+'</li>').join('')+'</ul>'+(a.quotes.length?'<p class="muted">点击引文回跳原文：</p>'+a.quotes.map((q,i)=>'<button class="sentence" data-act="jump" data-i="'+i+'">'+esc(q.text)+(q.note_zh?'<small>　'+esc(q.note_zh)+'</small>':'')+'</button>').join(''):'')+'<div class="editor"><strong>追问 · 建议</strong><p>'+esc(a.follow_up_zh)+'</p></div><p class="muted">'+esc(a.explanation_zh)+'</p>'+(a.needs_review_reasons&&a.needs_review_reasons.length?'<p class="error">待核对：'+a.needs_review_reasons.map(x=>esc(x.message_zh)).join(' ')+'</p>':'')+'</section>'}

function analysisStatus(record){
  const choice=compareChoice(record);
  if(!choice)return '';
  const marks=selectedMarks(record);
  const markKey=marks.slice(0,MAX_ANALYSIS_EVIDENCE).join(',');
  const limit=marks.length>MAX_ANALYSIS_EVIDENCE
    ?'<p class="muted">自动分析最多使用前 '+MAX_ANALYSIS_EVIDENCE+' 条圈选依据。全部圈选均保留。</p>'
    :'';
  const request=analysisRequests.get(record);
  if(request?.choice===choice){
    if(request.pending)return limit+'<p class="muted">正在分析选项 '+record.pick+' 和 '+choice+'…</p>';
    if(request.error)return limit+'<p class="error">'+esc(request.error)+'</p>'+btn('analyze','重试自动分析',true);
  }
  if(record.analysis?.compare===choice){
    const update=record.analysis.markKey!==markKey?btn('analyze','按当前依据更新分析',true):'';
    return limit+analysisPanel(record.analysis)+update;
  }
  return limit+btn('analyze','自动分析（建议）',true);
}

function analysisControls(record){
  if(!record.answer||!record.pick)return '';
  let selector='';
  if(record.answer===record.pick){
    const options=[...'ABCD'].filter(letter=>letter!==record.pick).map(letter=>
      '<option value="'+letter+'" '+(letter===record.analysisOther?'selected':'')+'>'+letter+'. '+esc(record.options['ABCD'.indexOf(letter)])+'</option>'
    ).join('');
    selector='<label class="field">选一个干扰项分析<select data-field="analysisOther"><option value="">请选择</option>'+options+'</select></label><p class="muted">'+ANALYSIS_MATERIALS+'</p>';
  }
  return selector+'<div data-analysis-status aria-live="polite">'+analysisStatus(record)+'</div>';
}

function refreshAnalysis(record){
  if(r!==record||page!=='review')return;
  const output=app.querySelector('[data-analysis-status]');
  if(output)output.innerHTML=analysisStatus(record);
}

function analyzeWrongAnswer(record){
  if(!record.answer||record.pick===record.answer||record.analysis?.compare===record.answer||analysisRequests.has(record))return;
  return analyze(record);
}

async function analyze(record){
  const choice=compareChoice(record);
  if(!choice)return;
  const previous=analysisRequests.get(record);
  if(previous?.choice===choice&&previous.pending)return;
  const request={choice,pending:true,error:''};
  analysisRequests.set(record,request);
  refreshAnalysis(record);
  try{
    const marks=selectedMarks(record).slice(0,MAX_ANALYSIS_EVIDENCE);
    const spans=sentenceSpans(record.article);
    const evidence=marks.map(index=>spans[index]).filter(Boolean)
      .map(({text,start,end})=>({quote:text,start,end}));
    const response=await fetch(window.YICI_API_BASE+'/api/v1/reviews/analyze',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        article_text:record.article,
        question_stem:record.question,
        options:record.options.map((text,index)=>({id:'ABCD'[index],text})),
        student_choice:record.pick,
        compare_choice:choice,
        answer_basis:record.basis||'evidence',
        evidence,
        reference_answer:record.answer,
        focus_kind:KIND_MAP[record.kind]||null
      })
    });
    const result=await response.json().catch(()=>null);
    if(analysisRequests.get(record)!==request)return;
    if(!response.ok||!result?.review){
      request.error=result?.error?.message_zh||'自动分析失败，可继续手动复盘。';
      return;
    }
    record.analysis={...result.review,compare:choice,markKey:marks.join(','),at:Date.now()};
    await save();
  }catch{
    request.error='无法连接分析服务，可继续手动复盘，已填内容保留。';
  }finally{
    request.pending=false;
    if(analysisRequests.get(record)===request)refreshAnalysis(record);
  }
}
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const btn=(a,t,secondary=false)=>'<button class="btn '+(secondary?'sub':'')+'" data-act="'+a+'">'+t+'</button>';
const mast=(title,eng,sub='校报编辑部')=>'<div class="mast"><div><div class="kicker">'+eng+'</div><h1>'+title+'</h1></div><div class="issue">THE NIGHT EDITION<br>'+sub+'</div></div>';
function goto(p){page=p;reading=false;draw();window.scrollTo(0,0)}
function home(){return mast('雨夜编辑部','THE READING DESK','校园英文校报 · 夜刊')+'<section class="hero"><div class="hero-copy"><span class="label">第一章　／　剧情审稿</span><h2>闭馆前十分钟</h2><p>“还有十分钟截稿。关于图书馆的这篇报道，你会签发哪一句？”</p>'+btn('story',db.story?'继续审稿　→':'开始审稿　→')+'</div><div class="scene"><img src="'+editor.image+'" alt="橙发值班编辑坐在雨夜窗边的暖灯下"><span class="caption">值班编辑　/　'+editor.name+'</span></div></section><div class="section"><h2>我的工作台</h2></div><div class="cards"><button class="card" data-act="import"><span class="ico">＋</span><span><b>导入我的错题</b><small>粘贴英文材料，还原当时的判断</small></span><span class="arrow">↗</span></button><button class="card" data-act="archive"><span class="ico">▤</span><span><b>翻开错题本</b><small>查看证据、笔记与待核对的稿件</small></span><span class="arrow">↗</span></button></div>'+(db.signed?'<div class="section"><h2>值班表</h2></div><p>今夜值班　·　橙笺</p>':'')}
function draw(){document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('active',b.dataset.act===(page==='archive'?'archive':'home')));app.innerHTML=({home,archive,mode,import:importPage,edit:editPage,review,ending})[page]()}
function fresh(story=false){return {id:crypto.randomUUID(),story,stage:'initial',article:'',question:'',options:['','','',''],answer:'',pick:'',marks:[],later:[],other:'',kind:'范围',basis:'evidence',analysis:null,memo:'',...story&&structuredClone(demo)}}
function archive(){return mast('我的错题本','REVIEW ARCHIVE')+'<section class="paper">'+(db.records.length?db.records.map(x=>'<button class="record" data-act="open" data-id="'+x.id+'"><b>'+esc(x.question||'未完成的来稿')+'</b><br><small>'+esc(x.answer?(x.stage==='done'?'已复盘':'复盘中'):'待核对')+'</small></button>').join(''):'<p>还没有来稿。带来一道你犹豫过的题，留下第一次判断。</p>')+btn('import','导入我的错题')+'</section>'}
function mode(){return mast('闭馆前十分钟','CHAPTER 01')+'<section class="paper"><h2>今晚这篇稿子，你想怎么审？</h2><p>选择将沿用到本章签发。</p><div class="actions">'+btn('fast','速通 · 提交后直接看对照')+btn('slow','慢通 · 先让我自己找',true)+'</div></section>'}
function importPage(){return mast('导入我的错题','INCOMING COPY')+'<section class="paper"><label class="field">粘贴一篇文章和一道题<textarea id="raw" rows="9" placeholder="英文原文…&#10;&#10;Which statement is supported?&#10;A. …&#10;B. …&#10;C. …&#10;D. …">'+esc(r.raw)+'</textarea></label><p class="muted">原文、题干和选项可在下一步校正。参考答案可留空。</p>'+btn('parse','解析并校对　→')+'</section>'}
function parse(){let raw=r.raw||'',m=[...raw.matchAll(/^\s*([A-DＡ-Ｄ])[.．、)）:：]\s*/gm)];let head=raw.slice(0,m[0]?.index??raw.length).trim().split(/\n+/);r.question=head.length>1?head.pop().trim():'';r.article=head.join('\n');for(let i=0;i<m.length;i++){let k='ABCD'.indexOf(m[i][1].normalize('NFKC'));r.options[k]=raw.slice(m[i].index+m[i][0].length,m[i+1]?.index??raw.length).trim()}}
function field(k,v,t){return '<label class="field">'+t+'<textarea data-field="'+k+'">'+esc(v)+'</textarea></label>'}
function letters(curr,empty){return (empty?'<option value="">未提供</option>':'')+[...'ABCD'].map(s=>'<option '+(s===curr?'selected':'')+'>'+s+'</option>').join('')}
function editPage(){return mast('校对来稿','COPY DESK')+'<div class="paper">'+field('article',r.article,'英文原文')+field('question',r.question,'题干')+r.options.map((v,i)=>field('opt'+i,v,'选项　'+'ABCD'[i])).join('')+'<label class="field">参考答案<select data-field="answer">'+letters(r.answer,true)+'</select></label><details><summary>查看粘贴原稿</summary><pre style="white-space:pre-wrap">'+esc(r.raw)+'</pre></details><div class="actions">'+btn('ready','开始复盘')+btn('draft','保存草稿',true)+'</div></div>'}
function sentences(){return sentenceSpans(r.article).map(span=>span.text)}
function promptText(){if(r.story){if(r.pick==='B')return r.marks.includes(1)?'原文的 some 能支持摘要里的 all 吗？':(r.marks.length===1&&r.marks[0]===0?'这句告诉你几点关门。哪一句写了谁真的留下了？':'哪一句直接写了学生如何利用延长的时间？');if(r.pick==='D'&&!r.marks.includes(1))return '你找到了摘要。哪一句直接写了学生利用延长的时间？';if(r.pick!=='D')return '看看句子的主语。原稿写的是谁做了什么？';return '你圈出了学生实际利用延时的那一句。'}return (r.basis==='dont_remember'||r.basis==='guess')?'这次重新读，哪一句最能帮助你判断？':r.kind==='目的'?'这个例子在帮作者说明什么？':r.kind==='因果'?'原文说明了因果，还是只记录了同时发生的事？':'把选项和引文放在一起。它们说的是同一群人、同一个范围吗？'}
const stem=()=>({'范围':'下次看到范围限定词，我会','目的':'下次判断举例目的，我会','因果':'下次判断因果关系，我会'}[r.kind]);
function dialogue(t){return '<div class="editor"><strong>'+editor.name+' · 值班编辑</strong><p>'+esc(t)+'</p></div>'}
function quote(ids){return ids.length?ids.map(i=>esc(sentences()[i])).join(' '):'未圈选'}
function review(){let initial=r.stage==='initial',full=['compare','done'].includes(r.stage),marks=initial?r.marks:r.later;
let article='<section class="paper '+(reading?'reading-on':'reading-off')+'"><h2>英文原稿</h2>'+sentences().map((s,i)=>'<button class="sentence" data-act="mark" data-i="'+i+'" aria-pressed="'+marks.includes(i)+'">'+esc(s)+'</button>').join('')+'<div class="sticky"><small>'+(initial?'点选当时依据的原句，可多选或撤销。':esc(promptText()))+'</small><div class="actions">'+btn('backEvidence','提交依据',true)+'</div></div></section>';
let side='<section class="paper side"><span class="label">'+(initial?'初次判断':full?'选项对照':'编辑追问')+'</span><h3 class="en">'+esc(r.question)+'</h3>';
if(initial){side+='<p>你当时选了哪一项？</p>'+r.options.map((s,i)=>'<button class="choice" data-act="pick" data-i="'+i+'" aria-pressed="'+(r.pick==='ABCD'[i])+'"><b>'+'ABCD'[i]+'.</b> '+esc(s)+'</button>').join('')+'<button class="btn sub mobile" data-act="read">回原文选依据</button><label class="field">当时的依据<select data-field="basis">'+Object.entries(BASIS_LABEL).map(([v,t])=>'<option value="'+v+'" '+(r.basis===v?'selected':'')+'>'+t+'</option>').join('')+'</select></label>'+(!r.story?'<label class="field">这次想核对什么？<select data-field="kind">'+['范围','目的','因果'].map(k=>'<option '+(k===r.kind?'selected':'')+'>'+k+'</option>').join('')+'</select></label>':'')+
  (r.answer?'<p class="muted">提交后若答错，将自动比较初选项和参考答案。'+ANALYSIS_MATERIALS+'</p>':'')+
  '<div class="actions">'+btn('submit','提交我的判断')+'</div>'}
else{side+=dialogue(promptText())+'<p class="quote">当时的依据　'+(r.basis==='evidence'?quote(r.marks):BASIS_LABEL[r.basis])+'</p>'+(r.later.length?'<p class="quote">复盘补充　'+quote(r.later)+'</p>':'')+'<button class="btn sub mobile" data-act="read">回原文找证据</button>';
if(!full){side+='<div class="actions">'+(r.story?btn('hint','给我一点提示',true):'')+btn('compare',r.story?'完成对照':'直接看两项差异')+'</div>'+(r.hint?dialogue('看看末班车那句。这个例外会改变哪个选项？'):'')}
else{side+='<p><b>我的选择　'+r.pick+'</b><br>'+esc(r.options['ABCD'.indexOf(r.pick)])+'</p>'+(r.answer?'<p><b>参考答案　'+esc(r.answer)+'</b><br>'+esc(r.options['ABCD'.indexOf(r.answer)])+'</p>':'<label class="field">待核对 · 另一候选项<select data-field="other">'+letters(r.other,true)+'</select></label><p>'+esc(r.options['ABCD'.indexOf(r.other)]||'')+'</p>')+(r.story?dialogue('Some students used the extra time to study. 第二句支持 D；末班车乘客提供了反例，B 的 all 扩大了范围。'):'')+
  (!r.story&&!r.answer?'<details><summary>补录参考答案</summary><select id="verified">'+letters('',true)+'</select><p class="muted">确认后若答错，将自动分析。'+ANALYSIS_MATERIALS+'</p>'+btn('verify','确认参考答案',true)+'</details>':'')+
  analysisControls(r)+field('memo',r.memo,stem()+'……')+'<div class="actions">'+btn('finish',r.story?'签发修订稿':'保存复盘')+(r.story&&r.pick==='B'?btn('falseReport','坚持签发 B',true):'')+'</div>'}}
return mast(r.story?'闭馆前十分钟':'错题复盘',r.story?'CHAPTER 01':'EVIDENCE REVIEW')+'<div class="grid">'+article+side+'</section></div>'}
function ending(){return mast(r.letter?'读者来信':'本章已签发','FINAL EDITION')+'<section class="paper">'+(r.letter?dialogue('我每天赶八点的末班车。报道说我们全都留下了，我想请你再核对一次。')+btn('correct','刊发更正'):('<h2>'+ (r.corrected?'更正已刊发':'修订稿已签发')+'</h2><p class="en">Some students took advantage of the later closing time.</p>'+btn('home','回到编辑部')))+'</section>'}
function useDraft(){if(!db.records.some(x=>x.id===r.id))db.records.unshift(r);db.pending=r.id;save()}
document.addEventListener('input',e=>{
  if(!r||!booted)return;
  const field=e.target.dataset.field;
  if(e.target.id==='raw')r.raw=e.target.value;
  else if(field?.startsWith('opt'))r.options[+field.slice(3)]=e.target.value;
  else if(field)r[field]=e.target.value;
  else return;
  save();
  if(field==='other')draw();
  if(field==='analysisOther'){
    analysisRequests.delete(r);
    if(compareChoice(r))return analyze(r);
    refreshAnalysis(r);
  }
});
document.addEventListener('click',async e=>{if(!booted)return;let b=e.target.closest('[data-act]');if(!b)return;let a=b.dataset.act,i=+b.dataset.i;
if(a==='home'||a==='archive')return goto(a);
if(a==='story'){if(db.story){r=db.story;return goto(r.signed||r.letter?'ending':'review')}return goto('mode')}
if(a==='fast'||a==='slow'){r=fresh(true);r.mode=a;db.story=r;save();return goto('review')}
if(a==='import'){r=fresh();r.draft=true;useDraft();return goto('import')}
if(a==='open'){r=db.records.find(x=>x.id===b.dataset.id);return goto(r.draft?(r.article?'edit':'import'):'review')}
if(a==='parse'){if(!r.raw?.trim())return note('请先粘贴英文材料。');parse();save();return goto('edit')}
if(a==='draft'){save();return goto('archive')}
if(a==='ready'){if(!r.article.trim()||!r.question.trim()||r.options.some(v=>!v.trim()))return note('请补齐原文、题干和四个选项，或保存草稿。');r.draft=false;save();return goto('review')}
if(a==='pick')r.pick='ABCD'[i];
if(a==='mark'){let list=r.stage==='initial'?r.marks:r.later;list.includes(i)?list.splice(list.indexOf(i),1):list.push(i)}
if(a==='read'){reading=true;draw();window.scrollTo(0,scrollAt);return}
if(a==='backEvidence'){scrollAt=window.scrollY;reading=false;draw();document.querySelector('.side').scrollIntoView();return}
if(a==='submit'){if(!r.pick||(!r.marks.length&&r.basis==='evidence'))return note('请选择一项，并圈依据或选择“排除法／猜的／记不清”。');r.stage=r.mode==='fast'?'compare':'ask';save();draw();analyzeWrongAnswer(r);return}
if(a==='verify'){const v=document.querySelector('#verified').value;if(!v)return note('请选择参考答案。');r.answer=v;save();draw();analyzeWrongAnswer(r);return}
if(a==='hint')r.hint=true;
if(a==='compare')r.stage='compare';
if(a==='falseReport'){r.letter=true;save();return goto('ending')}
if(a==='correct'){r.letter=false;r.corrected=true;r.signed=true;db.signed=true;save();return goto('ending')}
if(a==='jump'){const q=r.analysis?.quotes[i];if(!q)return;const si=sentenceSpans(r.article).findIndex(span=>q.start<span.end&&q.end>span.start);if(si<0)return;reading=true;draw();const el=document.querySelectorAll('[data-act="mark"]')[si];if(el){el.scrollIntoView({block:'center'});el.classList.add('hl')}return}
if(a==='analyze')return analyze(r);
if(a==='finish'){if(!r.memo.trim())return note('请先补完下次判断的方法。');if(!r.answer&&(!r.other||r.other===r.pick))return note('请选择另一个待核对的选项。');r.stage='done';if(r.story){db.signed=true;r.signed=true;save();return goto('ending')}if(await save()){goto('archive');note('复盘已保存')}return}
save();draw()});
loadState().then(state=>{db=state;migrate(db);booted=true;draw()}).catch(()=>{booted=true;draw();note('本地存储不可用，本次内容可能无法保存。')});
