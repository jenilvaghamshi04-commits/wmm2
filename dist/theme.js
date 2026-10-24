(function(){
  const root=document.documentElement,storageKey='wmm-team-theme',system=window.matchMedia('(prefers-color-scheme: dark)');
  let preference=null;
  try{const stored=localStorage.getItem(storageKey);if(stored==='light'||stored==='dark')preference=stored}catch{}
  function apply(theme){
    root.dataset.theme=theme;
    const dark=theme==='dark';
    document.querySelectorAll('[data-theme-toggle]').forEach(button=>{
      button.textContent=dark?'☀ Light':'☾ Dark';
      button.setAttribute('aria-label','Switch to '+(dark?'light':'dark')+' theme');
      button.setAttribute('aria-pressed',String(dark));
      button.title='Current theme: '+theme;
    });
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content',dark?'#0e1615':'#236b51');
  }
  apply(preference||(system.matches?'dark':'light'));
  document.addEventListener('DOMContentLoaded',()=>{
    apply(root.dataset.theme);
    document.querySelectorAll('[data-theme-toggle]').forEach(button=>button.addEventListener('click',()=>{
      preference=root.dataset.theme==='dark'?'light':'dark';
      try{localStorage.setItem(storageKey,preference)}catch{}
      apply(preference);
    }));
  });
  system.addEventListener('change',event=>{if(!preference)apply(event.matches?'dark':'light')});
  window.addEventListener('storage',event=>{
    if(event.key!==storageKey)return;
    preference=event.newValue==='dark'||event.newValue==='light'?event.newValue:null;
    apply(preference||(system.matches?'dark':'light'));
  });
})();
