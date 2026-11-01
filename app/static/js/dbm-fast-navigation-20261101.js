(() => {
  // Links leves: transição sem loader bloqueante, preserva as navegações normais.
  const badge = document.getElementById('dbmChatUnreadBadge');
  function updateBadge(n){if(!badge)return;const count=Math.max(0,Number(n)||0);badge.textContent=String(Math.min(99,count))+(count>99?'+':'');badge.hidden=!count;}
  window.addEventListener('dbm:chat-unread', e => updateBadge(e.detail?.count));
  // Renderização progressiva para listas muito longas, apenas quando necessário.
  if (/^\/(?:calculations\/history|cadastros\/cotacoes)/.test(location.pathname)) {
    const style=document.createElement('style');
    style.textContent='@supports (content-visibility:auto){.history-group-card,.quote-option-card{content-visibility:auto;contain-intrinsic-size:auto 260px}}';
    document.head.append(style);
  }
  // Retomada da aba usa atualização normal da aplicação, sem polling adicional.
})();
