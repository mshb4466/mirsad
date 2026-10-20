/* Layout and optional device speech; no market calculation is modified. */
function initLayoutV022_() {
  // Keep the first screen focused; all original IDs and their handlers survive.
  const main = document.getElementById('mainCard'), today = document.getElementById('tab-today');
  const aside = document.createElement('div'); aside.id='sessionAside';
  main.after(aside);
  aside.append(document.getElementById('nextCard'),document.getElementById('riskCard'));
  const explanation = document.createElement('details'); explanation.className='assessment-details';
  const summary = document.createElement('summary');summary.textContent='تفاصيل العوامل وتوافق التقييم';explanation.append(summary);
  for(const id of ['mRel','mDrivers','mNews','mTags']) explanation.append(document.getElementById(id));
  document.getElementById('mHow').before(explanation);
  const diagnostics=document.createElement('details');diagnostics.id='gammaDiagnostics';diagnostics.className='card gamma-diagnostics';diagnostics.open=true;
  const diagTitle=document.createElement('summary');diagTitle.textContent='عرض تفاصيل GEX حسب Strike والمقارنة';diagnostics.append(diagTitle);
  document.getElementById('gLevels').after(diagnostics);
  for(const id of ['gLine','gLine2','gCmp','gChart','gEsNote']) diagnostics.append(document.getElementById(id));
  document.getElementById('gPriceMap').before(document.getElementById('gCtl'));
  const pulse = document.getElementById('pulseDetails');
  const wide = matchMedia('(min-width:900px)');
  const resize = () => { pulse.open = wide.matches; };
  resize(); wide.addEventListener('change', resize);
  const jump = document.getElementById('gammaJump');
  jump.onclick = () => { showTab('gamma'); document.getElementById('gPriceMap').scrollIntoView({block:'start'}); };
  const speak = document.getElementById('speakSummary'), stop = document.getElementById('stopSummary'), note = document.getElementById('speechNote');
  if (!('speechSynthesis' in window) || !('SpeechSynthesisUtterance' in window)) {
    speak.disabled = true; note.textContent = 'القراءة الصوتية غير مدعومة على هذا الجهاز.'; return;
  }
  speak.onclick = () => {
    const text = ['mAdvice','mLeanW','mBiasW','mConfW','mIntW','mReason'].map(id=>document.getElementById(id).textContent.trim()).filter(Boolean).join('. ');
    const voices = speechSynthesis.getVoices(), arabic = voices.find(v=>/^ar(?:-|$)/.test(v.lang));
    if (!arabic && document.documentElement.lang === 'ar') { note.textContent='لا يتوفر صوت عربي على الجهاز؛ الخلاصة النصية تبقى متاحة.'; return; }
    speechSynthesis.cancel(); const u = new SpeechSynthesisUtterance(text); u.lang = document.documentElement.lang === 'en' ? 'en-US' : 'ar-IQ';
    if (arabic && u.lang.startsWith('ar')) u.voice=arabic;
    u.rate=.95; u.onstart=()=>{stop.hidden=false;note.textContent='تتم قراءة التقييم المعروض.';};
    u.onend=()=>{stop.hidden=true;note.textContent='انتهت القراءة.';};
    u.onerror=()=>{stop.hidden=true;note.textContent='تعذّرت القراءة الصوتية على الجهاز.';};
    speechSynthesis.speak(u);
  };
  stop.onclick = () => {speechSynthesis.cancel();stop.hidden=true;note.textContent='توقفت القراءة.';};
  // Cancel old spoken advice as soon as the user refreshes or leaves the page.
  document.getElementById('refreshBtn').addEventListener('click',()=>speechSynthesis.cancel());
  window.addEventListener('pagehide',()=>speechSynthesis.cancel());
}
try { initLayoutV022_(); } catch(error) { console.warn('Optional layout enhancement unavailable; existing app remains loaded'); }

try { if(typeof renderGamma_==='function')renderGamma_(); } catch(e) {}
