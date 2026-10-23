const $ = s => document.querySelector(s);
let prerequisitePolicy = {}, hlOnlyTopics = new Set();
let catalog = {}, currentDoc = null, currentQuestion = null;
let previewUrl;
let pendingImportIds = [], importing = false;
let pickerQuestions=[], teacherSelection=new Set(), pickerSignature=null;
document.addEventListener('DOMContentLoaded',()=>$('#preview-question').addEventListener('click',async()=>{ const button=$('#preview-question'); button.disabled=true; try { const response=await fetch(`/api/documents/${currentDoc.id}/preview`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({regions:currentQuestion.regions})}); if(!response.ok) throw new Error((await response.json()).error); if(previewUrl) URL.revokeObjectURL(previewUrl); previewUrl=URL.createObjectURL(await response.blob()); $('#crop-image').src=previewUrl; $('#crop-preview').hidden=false; } catch(error){status(error.message,true);} finally{button.disabled=false;} }));
function status(message, error=false) { $('#status').textContent=message; $('#status').classList.toggle('error',error); }
function el(tag, text, className) { const node=document.createElement(tag); if(text!==undefined) node.textContent=text; if(className) node.className=className; return node; }
async function api(url, options={}) { const response=await fetch(url, options); const value=await response.json(); if(!response.ok){const error=new Error(value.error || 'Request failed');error.diagnostics=value.diagnostics;throw error;} return value; }
function post(url, value) { return api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)}); }
async function busy(form, work) { const button=form.querySelector('[type=submit]'); button.disabled=true; try { await work(); } catch(error) { status(error.message,true); } finally { button.disabled=false; } }
document.querySelectorAll('[data-tab]').forEach(button=>button.addEventListener('click',()=>{ document.querySelectorAll('.tab').forEach(section=>section.hidden=section.id!==button.dataset.tab); document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b===button)); status(''); if(button.dataset.tab==='library') search().catch(e=>status(e.message,true)); }));
function applyTopicLevel(form) {
 const restricted=['SL','Both'].includes(form.elements.level?.value);
 const select=form.querySelector('select[name="topics"],select[name="topic"]');
 const removed=[];
 for(const option of select.options){
  option.disabled=restricted&&hlOnlyTopics.has(option.value);
  if(option.disabled&&option.selected){removed.push(option.value);option.selected=false;}
  if(catalog[option.value])option.textContent=`${option.value} · ${catalog[option.value]}${hlOnlyTopics.has(option.value)?' (HL only)':''}`;
 }
 if(form.id==='question'){
  const conflicts=[...new Set([...(currentQuestion?.level_conflicts||[]),...removed])];
  $('#level-topic-note').textContent=restricted?'HL-only topics are disabled for SL and Both.'+(conflicts.length?` Detected HL-only content: ${conflicts.join(', ')}. Check the source and level; this question is excluded from SL papers while that conflict remains.`:''):'';
 }
 return removed;
}
for(const id of ['question','generate','search'])$('#'+id).elements.level.addEventListener('change',()=>{
 const removed=applyTopicLevel($('#'+id));
 if(removed.length)status(`Removed HL-only topic selections: ${removed.join(', ')}.`);
});
async function search() {
 const params=new URLSearchParams(new FormData($('#search'))); const questions=await api('/api/questions?'+params);
 $('#count').textContent=`${questions.length} question${questions.length===1?'':'s'}`; $('#results').replaceChildren();
 if(!questions.length) { $('#results').append(el('div','No questions yet for these filters. Upload papers and use Confirm import, or save questions individually. For unknown metadata, choose All syllabuses.','empty')); return; }
 for(const q of questions) {
  const card=el('article',undefined,'card'); card.append(el('h3',`Question ${q.number} · ${q.year??'Unknown year'}`),el('p',`${q.level} · ${q.paper} · ${q.marks??'?'} marks · ~${q.minutes} min · ${q.difficulty}`));
  if(q.analysis_outdated)card.append(el('span','Needs review after reanalysis','badge'));
  if(q.possible_duplicate_ids?.length)card.append(el('span','Similar wording exists — compare diagrams','badge'));
  if(q.review_status==='imported') card.append(el('span','Imported · not individually reviewed','badge'));
  const tags=el('div',undefined,'tags'); for(const t of [...q.topics.map(t=>`${t} ${catalog[t]||''}`),...q.commands,...q.tags]) tags.append(el('span',t)); card.append(tags);
  const image=el('img'); const scope=new URLSearchParams(); for(const topic of new FormData($('#search')).getAll('topic').filter(Boolean))scope.append('topic',topic); image.src=`/api/questions/${q.id}/image?${scope}`; image.alt=`Cropped question ${q.number}`; image.loading='lazy';
  const link=el('a','Open PNG'); link.href=image.src; link.target='_blank'; link.rel='noopener';
  if(q.topic_omitted_parts?.length)card.append(el('p',`Topic view: omitted ${q.topic_omitted_parts.join(', ')}. Original question is preserved.`,'muted')); const edit=el('button','Edit review','secondary'); edit.type='button'; edit.addEventListener('click',async()=>{ try { await openDocument(q.document_id); document.querySelector('[data-tab="import"]').click(); selectQuestion(currentDoc.questions.find(original=>original.id===q.id)||currentDoc.questions.find(original=>original.number===q.number)); }catch(e){status(e.message,true);} });
  const partsButton=el('button','Dependencies & Short','secondary'); partsButton.type='button'; partsButton.addEventListener('click',()=>openSubquestions(q.id)); card.append(image,el('p',q.filename,'muted'),link,el('p'),edit,el('p'),partsButton); $('#results').append(card);
 }
}
$('#search').addEventListener('submit',e=>{ e.preventDefault(); busy(e.target,search); });
async function listDocuments() {
 const docs=await api('/api/documents');$('#documents').replaceChildren(new Option('Choose an uploaded paper',''));
 const source=$('#source-documents'), selected=new Set([...source.selectedOptions].map(option=>option.value));source.replaceChildren();
 for(const doc of docs){$('#documents').add(new Option(doc.filename,doc.id));const option=new Option(doc.filename,doc.id);option.selected=selected.has(doc.id);source.add(option);}
 pickerSignature=null;
}
async function openDocument(id) { currentDoc=await api('/api/documents/'+id); setImportTargets([id]); const analysis=currentDoc.analysis; $('#analysis-status').textContent='Analysis saved on this computer'+(analysis?.completed_at?' · '+new Date(analysis.completed_at).toLocaleString():'')+'. Available after restarting the app.'+(currentDoc.rules_changed?' Analysis rules changed; use Reanalyse saved text to update tags without OCR.':'')+(analysis?.language_review_status==='pending'?' Some optional model checks did not finish; completed results are preserved.':''); $('#review').hidden=false; $('#question').hidden=true; $('#documents').value=id; $('#warnings').replaceChildren(...currentDoc.warnings.map(w=>el('p',w))); renderCandidates(); $('#source-page').replaceChildren(...currentDoc.pages.map((p,i)=>new Option(`Page ${i+1}`,i))); showPage(0); }
function renderCandidates() { $('#candidates').replaceChildren(); for(const q of currentDoc.questions) { const button=el('button',`Question ${q.number}${currentDoc.saved_numbers.includes(q.number)?' · saved':''}`); button.type='button'; button.addEventListener('click',()=>selectQuestion(q)); $('#candidates').append(button); } }
function selectQuestion(q) { $('#crop-preview').hidden=true; currentQuestion=structuredClone(q); $('#question').hidden=false; $('#review-number').textContent=q.number; const labels={agreement:'OCR and PDF text suggest the same topics. This is not a semantic accuracy guarantee.',disagreement:'OCR and PDF text suggest different topics. Check the source image and revise tags.',ocr_only:'Tags use OCR only; there is no independent PDF text to compare. Check the source image.',not_run:'OCR verification has not run for this question.'}; $('#ocr-status').textContent=labels[q.ocr_comparison?.status||'not_run']; $('#tag-evidence').textContent=JSON.stringify(q.topic_evidence||{},null,2); for(const name of ['number','year','level','syllabus','paper','marks','minutes','difficulty']) $('#question').elements[name].value=q[name]??''; for(const name of ['commands','tags']) $('#question').elements[name].value=(q[name]||[]).join(', '); for(const opt of $('#question').elements.topics.options) opt.selected=(q.topics||[]).includes(opt.value); applyTopicLevel($('#question')); $('#extracted').textContent=q.text||'No extracted text. Enter tags manually.'; renderRegions(); if(q.regions.length) showPage(q.regions[0].page); showLanguageReview(q.language_review); }
function showPage(n) { $('#source-page').value=n; const p=currentDoc.pages[n]; $('#page-size').textContent=`${p.width} × ${p.height} PDF points`; $('#source-image').src=`/api/documents/${currentDoc.id}/pages/${n}`; }
$('#source-page').addEventListener('change',e=>showPage(Number(e.target.value)));
function renderRegions() { showLanguageReview(null); $('#regions').replaceChildren(); currentQuestion.regions.forEach((region,i)=>{ const row=el('div',undefined,'region'); const pageLabel=el('label','Page'); const page=el('select'); currentDoc.pages.forEach((p,n)=>page.add(new Option(n+1,n))); page.value=region.page; page.addEventListener('change',()=>{ region.page=Number(page.value); const p=currentDoc.pages[region.page]; region.rect=[30,35,p.width-30,p.height-30]; renderRegions(); showPage(region.page); }); pageLabel.append(page); row.append(pageLabel); ['Left','Top','Right','Bottom'].forEach((title,j)=>{ const label=el('label',title), input=el('input'); input.type='number'; input.step='0.1'; input.value=Math.round(region.rect[j]*10)/10; input.required=true; input.addEventListener('input',()=>region.rect[j]=Number(input.value)); label.append(input); row.append(label); }); const view=el('button','View','secondary'); view.type='button'; view.addEventListener('click',()=>showPage(region.page)); const remove=el('button','Remove','secondary'); remove.type='button'; remove.addEventListener('click',()=>{ currentQuestion.regions.splice(i,1); renderRegions(); }); row.append(view,remove); $('#regions').append(row); }); }
$('#add-region').addEventListener('click',()=>{ const n=Math.min(currentQuestion.regions.at(-1)?.page+1||0,currentDoc.pages.length-1), p=currentDoc.pages[n]; currentQuestion.regions.push({page:n,rect:[30,35,p.width-30,p.height-30]}); renderRegions(); showPage(n); });
$('#add-question').addEventListener('click',()=>{ const p=currentDoc.pages[0]; const q={...currentDoc.metadata,number:Math.max(0,...currentDoc.questions.map(q=>q.number),...currentDoc.saved_numbers)+1,regions:[{page:0,rect:[30,35,p.width-30,p.height-30]}],topics:[],commands:[],minutes:5,difficulty:'Unrated'}; currentDoc.questions.push(q); renderCandidates(); selectQuestion(q); });
$('#documents').addEventListener('change',async e=>{if(e.target.value) try{await openDocument(e.target.value);}catch(error){status(error.message,true);}});
function setImportTargets(ids) {
 pendingImportIds=[...ids];
 $('#import-confirmation').hidden=!ids.length;
 $('#import-targets').textContent=`${ids.length} paper${ids.length===1?'':'s'} selected for import.`;
 $('#confirm-import').disabled=importing||!ids.length;
 $('#import-outcome').replaceChildren();
}
function setUploadType() {
 const folder=$('#upload-type').value==='folder';
 $('#pdf-picker').hidden=folder; $('#folder-picker').hidden=!folder;
 $('#pdf-files').disabled=folder; $('#pdf-files').required=!folder;
 $('#pdf-folder').disabled=!folder; $('#pdf-folder').required=false;
}
$('#upload-type').addEventListener('change',()=>{
 setUploadType();
 if($('#upload-type').value==='folder')chooseFolder();
});
function chooseFolder(){
 if(importing)return;
 const input=$('#pdf-folder');
 if(!('webkitdirectory' in input)){status('Folder selection is unavailable in this browser. Open the app in a current Chrome, Edge, Firefox or Safari browser.',true);return;}
 $('#upload-type').value='folder';setUploadType();
 input.setAttribute('webkitdirectory','');input.setAttribute('directory','');input.multiple=true;
 input.click();
}
$('#choose-folder').addEventListener('click',chooseFolder);
$('#pdf-folder').addEventListener('change',()=>{
 const files=[...$('#pdf-folder').files], pdfs=files.filter(file=>file.name.toLowerCase().endsWith('.pdf'));
 const name=files[0]?.webkitRelativePath.split('/')[0]||'Selected folder';
 $('#folder-selection').textContent=files.length?`${name}: ${pdfs.length} PDFs found across all subfolders (${files.length-pdfs.length} other files skipped).`:'No folder selected';
});
$('#upload').addEventListener('submit',e=>{
 e.preventDefault();
 busy(e.target,async()=>{
  const input=$('#upload-type').value==='folder'?$('#pdf-folder'):$('#pdf-files');
  const selected=[...input.files];
  const files=selected.filter(file=>file.name.toLowerCase().endsWith('.pdf'));
  if(!files.length) throw new Error(input.id==='pdf-folder'?'No PDFs found. Choose a folder containing PDFs; nested subfolders are included.':'No PDF files found in this selection.');
  const mode=e.target.elements.ocr_mode.value, autoImport=$('#auto-import').checked, uploaded=[];
  let automaticallyAdded=0, importFailures=0, skippedMarkschemes=0;
  importing=true; setImportTargets([]); $('#documents').disabled=true;
  $('#upload-progress').replaceChildren();
  if(selected.length>files.length) $('#upload-progress').append(el('p',`Skipped ${selected.length-files.length} non-PDF files.`,'muted'));
  for(const control of e.target.querySelectorAll('input,select,#choose-folder'))control.disabled=true;
  try {
   for(const [index,file] of files.entries()) {
    const name=file.webkitRelativePath||file.name;
    status(`Reading PDF ${index+1} of ${files.length}: ${name}. OCR may take several minutes.`);
    const row=el('p',`${name}: extracting…`); $('#upload-progress').append(row);
    try {
     if(file.size>40*1024*1024) throw new Error('Exceeds the 40 MB per-file limit.');
     const data=new FormData(); data.append('file',file,file.name); data.append('ocr_mode',mode); data.append('relative_path',file.webkitRelativePath||file.name); if(autoImport)data.append('auto_import','1');
     const result=await api('/api/documents',{method:'POST',body:data});
     if(result.status==='skipped'&&result.reason==='markscheme'){skippedMarkschemes++;row.textContent=`${name}: ${result.message}`;continue;}
     if(!uploaded.includes(result.id))uploaded.push(result.id); row.textContent=`${name}: ${result.questions.length} detected question groups.`;
     if(result.duplicate_document)row.textContent+=' Reused saved analysis for this duplicate PDF.';
     if(result.import_result){
      automaticallyAdded+=result.import_result.imported; importFailures+=result.import_result.failed.length;
      row.textContent+=` ${result.import_result.imported} automatically saved; ${result.import_result.skipped_numbers.length} already in the bank; ${result.import_result.failed.length} import failures.`;
      for(const item of result.import_result.failed)$('#upload-progress').append(el('p',`${name}, question ${item.number}: ${item.error}`,'error'));
     }
    }catch(error){row.textContent=`${name}: failed — ${error.message}`;row.classList.add('error');}
   }
   await listDocuments();
   if(uploaded.length) await openDocument(uploaded[0]);
   if(autoImport)await search();
   status(`${uploaded.length} of ${files.length} PDFs uploaded. ${skippedMarkschemes} markschemes ignored. `+(autoImport?`${automaticallyAdded} questions automatically saved; ${importFailures} import failures.`:uploaded.length?'Use Confirm import to add their questions without individual review.':'No question papers were added.'),(uploaded.length===0&&skippedMarkschemes<files.length)||importFailures>0);
  }finally{
   importing=false; $('#documents').disabled=false;
   for(const control of e.target.querySelectorAll('input,select,#choose-folder'))control.disabled=false;
   setUploadType(); setImportTargets(uploaded);
  }
 });
});
$('#confirm-import').addEventListener('click',async()=>{
 if(importing||!pendingImportIds.length)return;
 const ids=[...pendingImportIds];importing=true;$('#confirm-import').disabled=true;$('#documents').disabled=true;
 $('#upload').querySelector('[type=submit]').disabled=true;
 const rows=[];let added=0,skipped=0,failed=0;
 try{
  for(const [index,id] of ids.entries()){
   status(`Adding questions from paper ${index+1} of ${ids.length}…`);
   try{
    const result=await post(`/api/documents/${id}/confirm-import`,{});
    added+=result.imported;skipped+=result.skipped_numbers.length;failed+=result.failed.length;
    for(const item of result.failed)rows.push(el('p',`Paper ${index+1}, question ${item.number}: ${item.error}`));
   }catch(error){failed++;rows.push(el('p',`Paper ${index+1}: ${error.message}`));}
  }
  if(currentDoc)await openDocument(currentDoc.id);
  await search();
 }catch(error){failed++;rows.push(el('p',error.message));}
 finally{
  importing=false;$('#documents').disabled=false;$('#upload').querySelector('[type=submit]').disabled=false;
  setImportTargets(ids);
  const summary=`${added} questions added; ${skipped} already saved; ${failed} failures. Imported questions can be edited in the library.`;
  $('#import-outcome').replaceChildren(el('p',summary),...rows);status(summary,failed>0);
 }
});
$('#reanalyse').addEventListener('click',async()=>{
 if(!currentDoc)return;const button=$('#reanalyse');button.disabled=true;
 try{
  const id=currentDoc.id;status('Reanalysing saved OCR/native page data. OCR will not run.');
  const result=await post(`/api/documents/${id}/reanalyse`,{});
  await listDocuments();await openDocument(id);await search();
  status(`Reanalysis saved. ${result.questions} groups detected; ${result.updated_question_ids.length} auto-imported questions updated; ${result.new_question_ids.length} newly detected questions added; ${result.duplicate_numbers.length} duplicates already in bank; ${result.outdated_numbers.length} older groups need review; ${result.preserved_reviewed_ids.length} manual reviews preserved; ${result.failed.length} failures. No OCR was run.`,result.failed.length>0);
 }catch(error){status(error.message,true);}finally{button.disabled=false;}
});
$('#autofill-tags').addEventListener('click',async()=>{
 const button=$('#autofill-tags');button.disabled=true;
 try{
  const form=$('#question');
  const result=await post(`/api/documents/${currentDoc.id}/suggest-tags`,{
   regions:currentQuestion.regions,paper:form.elements.paper.value,level:form.elements.level.value,
   topics:[...form.elements.topics.selectedOptions].map(option=>option.value)
  });
  form.elements.commands.value=result.commands.join(', ');
  form.elements.tags.value=result.tags.join(', ');
  status('Command terms and tags filled from the current crop text and selected topics. You can edit them before saving.');
 }catch(error){status(error.message,true);}finally{button.disabled=false;}
});
$('#question').addEventListener('submit',e=>{e.preventDefault(); busy(e.target,async()=>{ const value=Object.fromEntries(new FormData(e.target)); value.topics=[...e.target.elements.topics.selectedOptions].map(o=>o.value); for(const name of ['commands','tags']) value[name]=value[name].split(',').map(v=>v.trim()).filter(Boolean); value.document_id=currentDoc.id; value.regions=currentQuestion.regions; const saved=await post('/api/questions',value); currentQuestion={...saved}; const i=currentDoc.questions.findIndex(q=>q.number===saved.number); if(i>=0) currentDoc.questions[i]=saved; else currentDoc.questions.push(saved); if(!currentDoc.saved_numbers.includes(saved.number)) currentDoc.saved_numbers.push(saved.number); renderCandidates(); status(`Question ${saved.number} saved with ${saved.regions.length} page crop(s).`); });});
function paperOptions(){
 const form=$('#generate'),value=Object.fromEntries(new FormData(form));
 value.topics=[...form.elements.topics.selectedOptions].map(option=>option.value);
 value.document_ids=[...$('#source-documents').selectedOptions].map(option=>option.value);
 return value;
}
function pickerSummary(){
 const chosen=pickerQuestions.filter(q=>teacherSelection.has(q.id));
 const preferred=chosen.reduce((sum,q)=>sum+q.preferred_minutes,0),minimum=chosen.reduce((sum,q)=>sum+q.minimum_minutes,0);
 $('#picker-status').textContent=`${chosen.length} selected · ${minimum.toFixed(1)}–${preferred.toFixed(1)} estimated minutes · budget ${$('#generate').elements.minutes.value} minutes.`+(pickerSignature?'':' Filters changed; refresh the question list.');
}
$('#manual-selection').addEventListener('change',()=>{$('#question-picker').hidden=!$('#manual-selection').checked;pickerSummary();});
$('#generate').addEventListener('input',event=>{if(event.target.matches('[name]')){pickerSignature=null;pickerSummary();}});
$('#preview-questions').addEventListener('click',async()=>{
 const button=$('#preview-questions');button.disabled=true;
 try{
  const options=paperOptions(),signature=JSON.stringify(options);const result=await post('/api/papers/preview',options);
  if(signature!==JSON.stringify(paperOptions()))throw new Error('Filters changed during loading. Refresh the question list.');
  pickerQuestions=result.questions;teacherSelection=new Set([...teacherSelection].filter(id=>pickerQuestions.some(q=>q.id===id)));
  pickerSignature=signature;$('#manual-selection').checked=true;$('#question-picker').hidden=false;$('#paper-candidates').replaceChildren();
  for(const q of pickerQuestions){
   const card=el('article',undefined,'card'),label=el('label',undefined,'check'),check=el('input');check.type='checkbox';check.checked=teacherSelection.has(q.id);check.dataset.questionId=q.id;
   check.addEventListener('change',()=>{check.checked?teacherSelection.add(q.id):teacherSelection.delete(q.id);pickerSummary();});
   label.append(check,el('span',`Source Q${q.number} · ${q.filename}`));card.append(label,el('p',`${q.minimum_minutes.toFixed(1)}–${q.preferred_minutes.toFixed(1)} minutes · ${q.topics.map(t=>`${t} ${catalog[t]}`).join(', ')}`,'muted'));
   const params=new URLSearchParams({mode:options.render_mode});for(const topic of options.topics)params.append('topic',topic);
   const details=el('details'),summary=el('summary','Preview question'),image=el('img');image.src=`/api/questions/${q.id}/image?${params}`;image.alt=`Source question ${q.number}`;image.loading='lazy';details.append(summary,image);card.append(details);$('#paper-candidates').append(card);
  }
  pickerSummary();$('#paper-result').replaceChildren();showPaperDiagnostics(result.diagnostics);
  status(`${pickerQuestions.length} matching question groups. Select the questions to include. Short mode may choose smaller safe variants to fit the budget.`);
 }catch(error){status(error.message,true);}finally{button.disabled=false;}
});
function chooseAllQuestions(selected){teacherSelection=new Set(selected?pickerQuestions.map(q=>q.id):[]);for(const check of $('#paper-candidates').querySelectorAll('input[type=checkbox]'))check.checked=selected;pickerSummary();}
$('#select-all-questions').addEventListener('click',()=>chooseAllQuestions(true));
$('#clear-selected-questions').addEventListener('click',()=>chooseAllQuestions(false));
function showPaperDiagnostics(report){
 if(!report)return;
 const box=el('section',undefined,'notice');box.append(el('h3','Question availability'),el('p',report.summary));
 box.append(el('p',`${report.total_saved} questions in the bank · ${report.matching_filters} match the filters · ${report.fitting_budget} have a valid version within the time budget.`));
 for(const [label,key] of [['Levels','bank_levels'],['Syllabuses','bank_syllabuses'],['Paper types','bank_papers']]){
  const values=Object.entries(report[key]||{}).map(([name,count])=>`${name}: ${count}`).join(' · ');
  if(values)box.append(el('p',`${label} in your bank — ${values}`,'muted'));
 }
 if(report.analyzed_not_imported){
  box.append(el('p',`${report.analyzed_not_imported} analyzed groups have not been added to the bank.`));
  const button=el('button','Open imports','secondary');button.type='button';button.addEventListener('click',()=>document.querySelector('[data-tab="import"]').click());box.append(button);
 }
 if(report.exclusions?.length){
  const table=el('table',undefined,'diagnostics-table'),head=el('tr');
  for(const title of ['Reason','Questions','How to resolve'])head.append(el('th',title));
  const thead=el('thead');thead.append(head);table.append(thead);const body=el('tbody');
  for(const exclusion of report.exclusions){
   const row=el('tr'),reason=el('td',exclusion.reason),action=el('td',exclusion.action);
   if(exclusion.examples?.length){const details=el('details'),summary=el('summary','Examples');details.append(summary);for(const q of exclusion.examples)details.append(el('p',`${q.filename} · Q${q.number} · ${q.level} · ${q.syllabus} · ${q.paper} · ~${q.minutes} min`));reason.append(details);}
   row.append(reason,el('td',String(exclusion.count)),action);body.append(row);
  }
  table.append(body);const scroll=el('div',undefined,'diagnostics-scroll');scroll.append(table);box.append(scroll,el('p','Each excluded question is counted once.','muted'));
 }
 $('#paper-result').append(box);
}
$('#generate').addEventListener('submit',e=>{e.preventDefault();busy(e.target,async()=>{
 $('#paper-result').replaceChildren();const value=paperOptions();
 if($('#manual-selection').checked){
  if(pickerSignature!==JSON.stringify(value))throw new Error('Refresh the filtered question list after changing filters or analysis.');
  value.question_ids=pickerQuestions.filter(q=>teacherSelection.has(q.id)).map(q=>q.id);
  value.fill_paper=$('#fill-paper').checked;
 }
 try{
  const result=await post('/api/papers',value);const link=el('a','Download practice paper PDF');link.href=`/api/papers/${result.id}/download`;
  $('#paper-result').append(el('p',`${result.count} question groups · ${result.render_mode||'full'} · Estimated ${result.actual_minutes} / ${result.target_minutes} minutes · ${result.shortfall_minutes} minutes unfilled.`),link);
  showPaperDiagnostics(result.diagnostics);
  const numberingWarnings=Object.values(result.numbering||{}).flatMap(info=>info.warnings||[]);if(numberingWarnings.length)$('#paper-result').append(el('p',numberingWarnings.join(' '),'notice'));
  status(`Practice paper generated. ${result.filled_question_ids?.length||0} extra questions added by Fill paper. ${result.selections?.reduce((n,s)=>n+s.omitted_parts.length,0)||0} parts omitted. ${result.short_fallbacks?.length||0} questions retained whole because no approved dependency map was available.`);
 }catch(error){showPaperDiagnostics(error.diagnostics);throw error;}
});});
async function init() { const value=await api('/api/catalog'); catalog=value.topics; hlOnlyTopics=new Set(value.hl_only_topics||[]); prerequisitePolicy=value.prerequisite_policy||{}; document.querySelectorAll('.topic-list,.topic-filter').forEach(select=>{ for(const [code,name] of Object.entries(catalog)) select.add(new Option(`${code} · ${name}`,code)); }); for(const id of ['question','generate','search'])applyTopicLevel($('#'+id)); await Promise.all([search(),listDocuments()]); }
init().catch(e=>status(e.message,true));

function showLanguageReview(result) {
 currentQuestion && (currentQuestion.language_review=result);
 $('#language-result').hidden=!result;
 $('#apply-language-topics').hidden=result?.status!=='resolved';
 if(!result) return;
 const title=result.status==='resolved'?'Model proposal — check the source before saving.':result.status==='not_needed'?'Source suggestions agree.':'Manual review remains necessary.';
 $('#language-summary').textContent=title+' '+result.reason;
 $('#language-evidence').textContent=(result.evidence||[]).map(e=>`${e.topic} · ${e.source}: “${e.quote}”`).join('\n');
}
$('#language-review').addEventListener('click',async()=>{
 if(!currentQuestion) return;
 const button=$('#language-review');button.disabled=true;
 try { status('Reviewing both text versions with the local language model…');
  const result=await post(`/api/documents/${currentDoc.id}/questions/${$('#question').elements.number.value}/language-review`,{regions:currentQuestion.regions,paper:$('#question').elements.paper.value});
  showLanguageReview(result);status(result.status==='resolved'?'Topic proposal ready. Apply it and check the source before saving.':result.reason,result.status==='unavailable');
 }catch(error){status(error.message,true);}finally{button.disabled=false;}
});
$('#apply-language-topics').addEventListener('click',()=>{
 const result=currentQuestion?.language_review;if(result?.status!=='resolved')return;
 for(const opt of $('#question').elements.topics.options)opt.selected=result.topics.includes(opt.value);
 applyTopicLevel($('#question')); status('Allowed model topics applied to this draft. Save after checking the source.');
});
$('#question').addEventListener('input',e=>{if(e.target.closest('.region')||e.target.name==='paper')showLanguageReview(null);});

let sqQuestion=null, sqMapping=null, sqOmitted=new Set(), sqCustom=false, sqPreviewUrl;
function sqMessage(message){$('#sq-status').textContent=message;}
function sqDirty(){if(sqMapping)sqMapping.status='draft';$('#sq-confirm').checked=false;$('#sq-preview').disabled=true;$('#sq-preview-box').hidden=true;}
async function openSubquestions(id){
 try{const value=await api(`/api/questions/${id}/subquestions`);sqQuestion=value.question;sqMapping=value.mapping;sqOmitted=new Set();sqCustom=false;
 $('#sq-parent').textContent=`${sqQuestion.filename} · Question ${sqQuestion.number} · ${sqQuestion.minutes} minutes total`;
 $('#sq-source').href=`/api/questions/${id}/image`;renderSubquestions();$('#subquestion-dialog').showModal();
 }catch(error){status(error.message,true);}
}
function renderSubquestions(){
 $('#sq-parts').replaceChildren();$('#sq-confirm').checked=false;$('#sq-preview').disabled=sqMapping.status!=='approved';$('#sq-preview-box').hidden=true;
 const model=sqMapping.model_review;sqMessage(`${sqMapping.status==='approved'?'Approved map.':'Draft map — Full is preserved until approval.'} ${model?.reason||sqMapping.reason||''}`);
 for(const part of sqMapping.parts){
  const blocked=['SL','Both'].includes(sqQuestion.level)?(part.topics||[]).filter(code=>hlOnlyTopics.has(code)):[];
  if(blocked.length){part.topics=part.topics.filter(code=>!hlOnlyTopics.has(code));sqDirty();sqMessage('HL-only topic labels were excluded from this SL draft. Check the source and level before approving.');}
  const card=el('section',undefined,'sq-card');card.append(el('h3',`${part.id} · ${part.label}`));
  const timeLabel=el('label','Estimated minutes for this part');const time=el('input');time.type='number';time.min=part.id==='stem'?'0':'0.1';time.step='0.1';time.value=part.minutes;time.addEventListener('input',()=>{part.minutes=Number(time.value);sqDirty();});timeLabel.append(time);card.append(timeLabel); const topicLabel=el('label','Assessed topics for this part (select all that apply)'); const topicSelect=el('select'); topicSelect.multiple=true; topicSelect.size=5; for(const [code,name] of Object.entries(catalog)){const option=new Option(`${code} · ${name}${hlOnlyTopics.has(code)?' (HL only)':''}`,code);option.disabled=['SL','Both'].includes(sqQuestion.level)&&hlOnlyTopics.has(code);option.selected=(part.topics||[]).includes(code);topicSelect.add(option);}topicSelect.addEventListener('change',()=>{part.topics=[...topicSelect.selectedOptions].map(o=>o.value);sqDirty();});topicLabel.append(topicSelect);card.append(topicLabel);
  if(part.id!=='stem'){
   card.append(el('p','Always requires the shared stem. Also requires:','muted'));const dependencies=el('div',undefined,'sq-dependencies');
   for(const other of sqMapping.parts.filter(p=>p.id!=='stem'&&p.id!==part.id)){
    const label=el('label',undefined,'check'),check=el('input');check.type='checkbox';check.checked=part.requires.includes(other.id);check.addEventListener('change',()=>{part.requires=check.checked?[...part.requires,other.id]:part.requires.filter(id=>id!==other.id);sqDirty();});label.append(check,el('span',other.label));dependencies.append(label);
   }card.append(dependencies);
   const omitLabel=el('label',undefined,'check'),omit=el('input');omit.type='checkbox';omit.checked=sqOmitted.has(part.id);omit.addEventListener('change',()=>{sqCustom=true;omit.checked?sqOmitted.add(part.id):sqOmitted.delete(part.id);});omitLabel.append(omit,el('span','Omit from custom Short preview (prerequisites are enforced)'));card.append(omitLabel);
  }else card.append(el('p','Always retained. If there is no separate stem crop, the question heading stays and shared context inside another part must be listed as a prerequisite.','muted'));
  for(const [index,region] of part.regions.entries()){
   const row=el('div',undefined,'sq-crop');for(const [label,key] of [['Page',-1],['Left',0],['Top',1],['Right',2],['Bottom',3]]){
    const field=el('label',label),input=el('input');input.type='number';input.step=key===-1?'1':'0.1';input.value=key===-1?region.page+1:region.rect[key];input.addEventListener('input',()=>{if(key===-1)region.page=Number(input.value)-1;else region.rect[key]=Number(input.value);sqDirty();});field.append(input);row.append(field);
   }const remove=el('button','Remove crop','secondary');remove.type='button';remove.addEventListener('click',()=>{part.regions.splice(index,1);sqDirty();renderSubquestions();});row.append(remove);card.append(row);
  }
  const add=el('button','Add crop','secondary');add.type='button';add.addEventListener('click',()=>{part.regions.push(structuredClone(sqQuestion.regions[0]));sqDirty();renderSubquestions();});card.append(add);
  const details=el('details'),summary=el('summary','Part text and model evidence'),text=el('pre',part.text||'(No separate stem text)');details.append(summary,text);const evidence=model?.evidence?.find(e=>e.id===part.id);if(evidence)details.append(el('p',`${evidence.confidence} confidence: ${evidence.reason}`),el('blockquote',evidence.quote));card.append(details);$('#sq-parts').append(card);
 }
}
$('#sq-close').addEventListener('click',()=>$('#subquestion-dialog').close());
$('#sq-model').addEventListener('click',async()=>{const button=$('#sq-model');button.disabled=true;try{sqMessage('Checking the full parent context with the local language model…');sqMapping=await post(`/api/questions/${sqQuestion.id}/subquestions/analyze`,{parts:sqMapping.parts});renderSubquestions();}catch(error){sqMessage(error.message);}finally{button.disabled=false;}});
$('#sq-approve').addEventListener('click',async()=>{const button=$('#sq-approve');button.disabled=true;try{sqMapping=await post(`/api/questions/${sqQuestion.id}/subquestions/approve`,{parts:sqMapping.parts,confirmed:$('#sq-confirm').checked});renderSubquestions();sqMessage('Approved. Short may omit optional parts; any retained part always brings its prerequisites and shared stem.');await search();}catch(error){sqMessage(error.message);}finally{button.disabled=false;}});
$('#sq-preview').addEventListener('click',async()=>{const button=$('#sq-preview');button.disabled=true;try{const payload={mode:'short'};if(sqCustom)payload.omitted_parts=[...sqOmitted];const response=await fetch(`/api/questions/${sqQuestion.id}/render`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(!response.ok)throw new Error((await response.json()).error);if(sqPreviewUrl)URL.revokeObjectURL(sqPreviewUrl);sqPreviewUrl=URL.createObjectURL(await response.blob());$('#sq-preview-image').src=sqPreviewUrl;$('#sq-preview-box').hidden=false;}catch(error){sqMessage(error.message);}finally{button.disabled=sqMapping.status!=='approved';}});

function showTopicScope(form, target){
 const name=form.id==='search'?'topic':'topics';const selected=new FormData(form).getAll(name).filter(Boolean);const allowed=new Set(selected);
 function visit(code){for(const p of prerequisitePolicy.requires?.[code]||[]){if(!allowed.has(p)){allowed.add(p);visit(p);}}} selected.forEach(visit);
 const earlier=[...allowed].filter(c=>!selected.includes(c));
 $(target).textContent=selected.length?`Selected targets: ${selected.join(', ')}. ${earlier.length?'Also allows earlier prerequisites: '+earlier.join(', ')+'. ':''}Out-of-scope extensions are removed only with an approved part/topic map; required context is never dropped.`:'No topic restriction. Full preserves every part; Short uses approved dependency maps.';
}
$('#search').addEventListener('change',()=>showTopicScope($('#search'),'#search-scope'));
$('#generate').addEventListener('change',()=>showTopicScope($('#generate'),'#generate-scope'));
