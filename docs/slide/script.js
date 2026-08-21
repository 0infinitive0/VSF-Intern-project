/* ===========================================
   SLIDE PRESENTATION CONTROLLER
   =========================================== */
class SlidePresentation{
  constructor(){
    this.slides = Array.from(document.querySelectorAll('.slide'));
    this.currentSlide = 0;
    this.stage = document.getElementById('deckStage');
    this.counter = document.getElementById('counter');
    this.appendixBackBtn = document.getElementById('appendixBackBtn');
    this.jumpHint = document.getElementById('jumpHint');
    this.jumpBuffer = '';
    this.jumpTimer = null;
    this.setupStageScale();
    this.setupKeyboardNav();
    this.setupTouchNav();
    this.setupButtons();
    this.setupIndexJump();
    this.appendixBackBtn.addEventListener('click', ()=>{
      const arch = document.getElementById('s5');
      const idx = this.slides.indexOf(arch);
      if(idx >= 0) this.showSlide(idx);
    });
    this.showSlide(0);
  }
  setupIndexJump(){
    document.querySelectorAll('.appendix-index .idx-item').forEach(item=>{
      item.style.cursor = 'pointer';
      item.addEventListener('click', ()=>{
        const n = parseInt(item.querySelector('.idx-num').textContent, 10);
        if(!isNaN(n)) this.showSlide(n-1);
      });
    });
    const jumpBtn = document.getElementById('jumpToAppendixBtn');
    if(jumpBtn){
      jumpBtn.addEventListener('click', ()=>{
        const divider = document.querySelector('.slide[data-appendix="true"]');
        if(divider){
          const idx = this.slides.indexOf(divider);
          if(idx >= 0) this.showSlide(idx);
        }
      });
    }
  }
  handleDigit(digit){
    clearTimeout(this.jumpTimer);
    this.jumpBuffer = (this.jumpBuffer + digit).slice(-2);
    this.jumpHint.textContent = 'Nhảy đến slide ' + this.jumpBuffer + ' — Enter để xác nhận';
    this.jumpHint.classList.add('show');
    this.jumpTimer = setTimeout(()=>{ this.jumpBuffer=''; this.jumpHint.classList.remove('show'); }, 2000);
  }
  confirmJump(){
    const n = parseInt(this.jumpBuffer, 10);
    this.jumpBuffer=''; this.jumpHint.classList.remove('show');
    clearTimeout(this.jumpTimer);
    if(!isNaN(n) && n>=1 && n<=this.slides.length) this.showSlide(n-1);
  }
  setupStageScale(){
    const scale = () => {
      const factor = Math.min(window.innerWidth/1920, window.innerHeight/1080);
      const x = (window.innerWidth - 1920*factor)/2;
      const y = (window.innerHeight - 1080*factor)/2;
      this.stage.style.transform = `translate(${x}px, ${y}px) scale(${factor})`;
    };
    scale();
    window.addEventListener('resize', scale);
  }
  setupKeyboardNav(){
    document.addEventListener('keydown', (e) => {
      if(editor.isActive) return;
      if(/^[0-9]$/.test(e.key)){ this.handleDigit(e.key); return; }
      if(e.key==='Enter' && this.jumpBuffer){ this.confirmJump(); return; }
      if(e.key==='Escape' && this.jumpBuffer){ this.jumpBuffer=''; this.jumpHint.classList.remove('show'); return; }
      if(['ArrowRight','PageDown',' '].includes(e.key)){ e.preventDefault(); this.next(); }
      if(['ArrowLeft','PageUp'].includes(e.key)){ e.preventDefault(); this.prev(); }
      if(e.key==='Home') this.showSlide(0);
      if(e.key==='End') this.showSlide(this.slides.length-1);
    });
  }
  setupTouchNav(){
    let touchX = null;
    document.addEventListener('touchstart', e=> touchX = e.touches[0].clientX);
    document.addEventListener('touchend', e=>{
      if(touchX===null) return;
      const dx = e.changedTouches[0].clientX - touchX;
      if(dx > 50) this.prev();
      if(dx < -50) this.next();
      touchX = null;
    });
  }
  setupButtons(){
    document.getElementById('prevBtn').addEventListener('click', ()=> this.prev());
    document.getElementById('nextBtn').addEventListener('click', ()=> this.next());
  }
  next(){ this.showSlide(this.currentSlide+1); }
  prev(){ this.showSlide(this.currentSlide-1); }
  showSlide(index){
    this.currentSlide = Math.max(0, Math.min(index, this.slides.length-1));
    this.slides.forEach((slide,i)=>{
      slide.classList.toggle('active', i===this.currentSlide);
      slide.classList.toggle('visible', i===this.currentSlide);
    });
    const isAppendix = this.slides[this.currentSlide].dataset.appendix === 'true';
    const num = String(this.currentSlide+1).padStart(2,'0') + ' / ' + String(this.slides.length).padStart(2,'0');
    this.counter.textContent = isAppendix ? ('BACKUP · ' + num) : num;
    this.appendixBackBtn.classList.toggle('show', isAppendix);
  }
}

/* ===========================================
   INLINE EDITING (contenteditable + localStorage)
   =========================================== */
const STORAGE_KEY = 'vsf-pitch-deck-edits';
class InlineEditor{
  constructor(){
    this.isActive = false;
    this.editableSelector = 'h1, h2, h4, p, span, li, div.nm, div.tag, div.detail, div.lbl, div.node-name, div.idx-label, div.note';
    this.toggle = document.getElementById('editToggle');
    this.hotzone = document.getElementById('editHotzone');
    this.bindHover();
    this.bindToggle();
    this.bindKeyboard();
    this.restore();
  }
  bindHover(){
    let hideTimeout = null;
    const show = () => { clearTimeout(hideTimeout); this.toggle.classList.add('show'); };
    const scheduleHide = () => { hideTimeout = setTimeout(()=>{ if(!this.isActive) this.toggle.classList.remove('show'); }, 400); };
    this.hotzone.addEventListener('mouseenter', show);
    this.hotzone.addEventListener('mouseleave', scheduleHide);
    this.toggle.addEventListener('mouseenter', show);
    this.toggle.addEventListener('mouseleave', scheduleHide);
  }
  bindToggle(){
    this.toggle.addEventListener('click', ()=> this.toggleEditMode());
    this.hotzone.addEventListener('click', ()=> this.toggleEditMode());
  }
  bindKeyboard(){
    document.addEventListener('keydown', (e)=>{
      if((e.key==='e' || e.key==='E') && document.activeElement.getAttribute('contenteditable')!=='true'){
        this.toggleEditMode();
      }
      if((e.key==='s' || e.key==='S') && (e.ctrlKey || e.metaKey)){
        e.preventDefault(); this.save();
      }
    });
  }
  toggleEditMode(){
    this.isActive = !this.isActive;
    this.toggle.classList.toggle('active', this.isActive);
    document.querySelectorAll('.slide').forEach(slide=>{
      slide.querySelectorAll(this.editableSelector).forEach(el=>{
        if(el.closest('.edit-toggle')) return;
        el.setAttribute('contenteditable', this.isActive ? 'true' : 'false');
      });
    });
    if(!this.isActive) this.persist();
  }
  persist(){
    const data = {};
    document.querySelectorAll('[id^="s"]').forEach(slide=>{
      data[slide.id] = slide.innerHTML;
    });
    try{ localStorage.setItem(STORAGE_KEY, JSON.stringify(data)); }catch(e){}
  }
  restore(){
    try{
      const raw = localStorage.getItem(STORAGE_KEY);
      if(!raw) return;
      const data = JSON.parse(raw);
      Object.keys(data).forEach(id=>{
        const el = document.getElementById(id);
        if(el) el.innerHTML = data[id];
      });
    }catch(e){}
  }
  save(){
    this.persist();
    const html = '<!DOCTYPE html>\n' + document.documentElement.outerHTML;
    const blob = new Blob([html], {type:'text/html'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'VSF-Trip-Planner-Pitch-Deck.html';
    a.click();
  }
}

const editor = new InlineEditor();
const presentation = new SlidePresentation();
