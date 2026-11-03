(() => {
  if (!document.body) return;
  let audioCtx = null;
  let unlocked = false;
  let baselineReady = false;
  let previousUnread = 0;

  function unlock(){
    if(unlocked) return;
    try{
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if(!Ctx) return;
      audioCtx ||= new Ctx();
      if(audioCtx.state === 'suspended') audioCtx.resume().catch(()=>{});
      unlocked = true;
    }catch(_){}
  }

  function play(){
    unlock();
    if(!audioCtx || audioCtx.state !== 'running') return;
    try{
      const t = audioCtx.currentTime + .01;
      [[0,784,.14,.055],[.10,1046.5,.18,.07]].forEach(([delay,freq,duration,volume])=>{
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.type='sine';
        osc.frequency.setValueAtTime(freq,t+delay);
        gain.gain.setValueAtTime(.0001,t+delay);
        gain.gain.exponentialRampToValueAtTime(volume,t+delay+.018);
        gain.gain.exponentialRampToValueAtTime(.0001,t+delay+duration);
        osc.connect(gain); gain.connect(audioCtx.destination);
        osc.start(t+delay); osc.stop(t+delay+duration+.03);
      });
    }catch(_){}
  }

  window.dbmChatPlaySound = play;
  ['pointerdown','touchstart','keydown','click'].forEach(name => {
    window.addEventListener(name, unlock, {once:true, passive:true});
  });

  async function check(){
    try{
      const res = await fetch('/company/chat/unread', {cache:'no-store', credentials:'same-origin'});
      if(!res.ok) return;
      const data = await res.json();
      if(!data?.ok) return;
      const current = Number(data.unread || 0);
      if(!baselineReady){ previousUnread=current; baselineReady=true; return; }
      if(current > previousUnread) play();
      previousUnread = current;
      window.dispatchEvent(new CustomEvent('dbm:chat-unread',{detail:{count:current,data}}));
    }catch(_){}
  }

  setTimeout(check,1200);
  setInterval(()=>{ if(!document.hidden) check(); },5500);
})();
