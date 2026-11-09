/* Escolha de destino: nova cotação ou cotação já existente (aba Cotações).
 * Usado ao aceitar voos e nos acompanhamentos (+ Novo / Mover). */
(() => {
  if (window.dbmChooseQuoteTarget) return;

  const ACCEPT_ACTION = /\/cadastros\/cotacoes-aceitas\/(?:opcao\/\d+|\d+)\/add$/;
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  const style = document.createElement('style');
  style.textContent = `
  .qt-dialog{border:1px solid var(--border,#24364f);border-radius:20px;padding:0;width:min(560px,calc(100vw - 32px));background:var(--panel,#0f1b2d);color:var(--text,#e8f0fa);box-shadow:0 30px 80px rgba(0,0,0,.45)}
  .qt-dialog::backdrop{background:rgba(5,10,20,.6)}
  .qt-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;padding:20px 22px 8px}
  .qt-head h2{margin:0;font-size:1.15rem}.qt-head p{margin:4px 0 0;color:var(--muted,#8aa0b8);font-size:.88rem}
  .qt-close{background:none;border:0;color:inherit;font-size:1.5rem;line-height:1;cursor:pointer;min-width:44px;min-height:44px}
  .qt-body{padding:8px 22px 4px;display:grid;gap:10px}
  .qt-choice{display:flex;gap:12px;align-items:flex-start;padding:14px;border:1px solid var(--border,#24364f);border-radius:14px;cursor:pointer;background:var(--panel-2,transparent)}
  .qt-choice:has(input:checked){border-color:var(--cyan,#32c9ff);box-shadow:0 0 0 1px var(--cyan,#32c9ff) inset}
  .qt-choice input{margin-top:3px;accent-color:var(--cyan,#32c9ff)}
  .qt-choice strong{display:block}.qt-choice small{color:var(--muted,#8aa0b8)}
  .qt-panel{display:grid;gap:8px;padding:2px 2px 0}
  .qt-panel[hidden]{display:none}
  .qt-panel label{display:grid;gap:5px;font-size:.85rem;color:var(--muted,#8aa0b8)}
  .qt-panel input[type=search],.qt-panel input[type=text]{width:100%;box-sizing:border-box;padding:11px 12px;border-radius:12px;border:1px solid var(--border,#24364f);background:var(--panel-2,#0b1524);color:inherit;font:inherit}
  .qt-list{max-height:260px;overflow:auto;display:grid;gap:6px}
  .qt-item{display:flex;gap:10px;align-items:center;padding:10px 12px;border:1px solid var(--border,#24364f);border-radius:12px;cursor:pointer}
  .qt-item:has(input:checked){border-color:var(--cyan,#32c9ff)}
  .qt-item input{accent-color:var(--cyan,#32c9ff)}
  .qt-item b{display:block;font-size:.92rem}.qt-item small{color:var(--muted,#8aa0b8)}
  .qt-code{font-size:.72rem;padding:2px 7px;border-radius:999px;background:color-mix(in srgb,var(--cyan,#32c9ff) 16%,transparent);color:var(--cyan,#32c9ff);margin-right:6px}
  .qt-empty{color:var(--muted,#8aa0b8);font-size:.88rem;padding:8px 2px}
  .qt-foot{display:flex;justify-content:flex-end;gap:10px;padding:14px 22px 20px}
  .qt-error{color:#f87171;font-size:.85rem;min-height:1em;margin:0}
  `;
  document.head.append(style);

  const dialog = document.createElement('dialog');
  dialog.className = 'qt-dialog';
  dialog.setAttribute('aria-labelledby', 'qtTitle');
  dialog.innerHTML = `
    <form method="dialog" class="qt-form">
      <div class="qt-head"><div><h2 id="qtTitle"></h2><p id="qtDesc"></p></div><button type="button" class="qt-close" aria-label="Fechar" data-confirm-ignore="1">×</button></div>
      <div class="qt-body">
        <label class="qt-choice"><input type="radio" name="qt_mode" value="new" checked><span><strong id="qtNewLabel">Criar nova cotação</strong><small id="qtNewHint"></small></span></label>
        <div class="qt-panel" id="qtNewPanel" hidden><label for="qtClient">Nome do cliente (opcional)<input type="text" id="qtClient" maxlength="200" autocomplete="off"></label></div>
        <label class="qt-choice"><input type="radio" name="qt_mode" value="existing"><span><strong id="qtExistingLabel">Adicionar a uma cotação já criada</strong><small id="qtExistingHint"></small></span></label>
        <div class="qt-panel" id="qtExistingPanel" hidden>
          <label for="qtSearch">Buscar cotação por cliente, nome ou código<input type="search" id="qtSearch" placeholder="Ex.: Maria, q0123, Lisboa" autocomplete="off"></label>
          <div class="qt-list" id="qtList" role="radiogroup" aria-label="Cotações da aba Cotações"></div>
        </div>
        <p class="qt-error" id="qtError" role="alert"></p>
      </div>
      <div class="qt-foot">
        <button type="button" class="secondary-button" id="qtCancel" data-confirm-ignore="1">Cancelar</button>
        <button type="button" class="primary-button" id="qtOk" data-confirm-ignore="1">Continuar</button>
      </div>
    </form>`;
  document.body.append(dialog);

  const $ = (id) => dialog.querySelector('#' + id);
  let current = null;
  let searchTimer = null;
  let searchSeq = 0;

  function mode() { return dialog.querySelector('input[name="qt_mode"]:checked')?.value || 'new'; }

  function syncPanels() {
    const m = mode();
    $('qtExistingPanel').hidden = m !== 'existing';
    $('qtNewPanel').hidden = !(m === 'new' && current?.askClient);
    $('qtError').textContent = '';
    if (m === 'existing' && !$('qtList').dataset.loaded) load('');
    if (m === 'existing') setTimeout(() => $('qtSearch').focus(), 30);
  }

  async function load(q) {
    const seq = ++searchSeq;
    const list = $('qtList');
    list.dataset.loaded = '1';
    list.innerHTML = '<p class="qt-empty">Carregando cotações…</p>';
    try {
      const params = new URLSearchParams({q});
      if (current?.exclude) params.set('exclude', current.exclude);
      const res = await fetch('/cadastros/cotacoes-aceitas/destinos?' + params, {headers: {'Accept': 'application/json'}, credentials: 'same-origin'});
      if (!res.ok) throw new Error(String(res.status));
      const data = await res.json();
      if (seq !== searchSeq) return;
      const items = Array.isArray(data.items) ? data.items : [];
      list.innerHTML = items.length ? items.map((it) => `
        <label class="qt-item"><input type="radio" name="qt_group" value="${esc(it.id)}">
          <span><b><span class="qt-code">${esc(it.code)}</span>${esc(it.title)}</b>
          <small>${esc(it.client || 'Cliente não informado')}${it.status ? ' · ' + esc(it.status) : ''}${it.updated ? ' · ' + esc(it.updated) : ''}</small></span></label>`).join('')
        : '<p class="qt-empty">Nenhuma cotação encontrada na aba Cotações.</p>';
    } catch (_) {
      if (seq === searchSeq) list.innerHTML = '<p class="qt-empty">Não foi possível carregar as cotações. Tente novamente.</p>';
    }
  }

  function finish(value) {
    const resolve = current?.resolve;
    current = null;
    if (dialog.open) dialog.close();
    resolve?.(value);
  }

  dialog.querySelectorAll('input[name="qt_mode"]').forEach((el) => el.addEventListener('change', syncPanels));
  $('qtSearch').addEventListener('input', (e) => { clearTimeout(searchTimer); searchTimer = setTimeout(() => load(e.target.value.trim()), 250); });
  $('qtCancel').addEventListener('click', () => finish(null));
  dialog.querySelector('.qt-close').addEventListener('click', () => finish(null));
  dialog.addEventListener('cancel', (e) => { e.preventDefault(); finish(null); });
  $('qtOk').addEventListener('click', () => {
    if (mode() === 'existing') {
      const picked = dialog.querySelector('input[name="qt_group"]:checked');
      if (!picked) { $('qtError').textContent = 'Escolha uma cotação da lista.'; return; }
      finish({mode: 'existing', groupId: picked.value, clientName: ''});
    } else {
      finish({mode: 'new', groupId: '', clientName: $('qtClient').value.trim()});
    }
  });

  window.dbmChooseQuoteTarget = (opts = {}) => new Promise((resolve) => {
    if (current) finish(null);
    current = {...opts, resolve};
    $('qtTitle').textContent = opts.title || 'Para onde vai este voo?';
    $('qtDesc').textContent = opts.description || '';
    $('qtNewLabel').textContent = opts.newLabel || 'Criar nova cotação';
    $('qtNewHint').textContent = opts.newHint || '';
    $('qtExistingLabel').textContent = opts.existingLabel || 'Adicionar a uma cotação já criada';
    $('qtExistingHint').textContent = opts.existingHint || '';
    $('qtOk').textContent = opts.okLabel || 'Continuar';
    $('qtClient').value = '';
    $('qtSearch').value = '';
    $('qtList').innerHTML = '';
    delete $('qtList').dataset.loaded;
    dialog.querySelector('input[name="qt_mode"][value="' + (opts.defaultMode === 'existing' ? 'existing' : 'new') + '"]').checked = true;
    dialog.showModal();
    syncPanels();
  });

  function setHidden(form, name, value) {
    let input = form.querySelector(`input[type="hidden"][name="${name}"]`);
    if (!input) { input = document.createElement('input'); input.type = 'hidden'; input.name = name; form.append(input); }
    input.value = value;
  }

  function configFor(form) {
    const action = (form.getAttribute('action') || '').split('?')[0];
    if (form.dataset.quoteTarget) {
      return {
        title: form.dataset.targetTitle || 'Escolha a cotação',
        description: form.dataset.targetDescription || '',
        newLabel: form.dataset.targetNewLabel,
        newHint: form.dataset.targetNewHint,
        existingLabel: form.dataset.targetExistingLabel,
        existingHint: form.dataset.targetExistingHint,
        okLabel: form.dataset.targetOk,
        askClient: form.dataset.targetAskClient === '1',
        exclude: form.dataset.targetExclude || '',
      };
    }
    if (ACCEPT_ACTION.test(action)) {
      const groupMatch = action.match(/\/cotacoes-aceitas\/(\d+)\/add$/);
      return {
        title: 'Para onde vai este voo?',
        description: 'Escolha se o voo aceito vira uma cotação nova ou entra numa cotação que já está na aba Cotações.',
        newLabel: 'Criar nova cotação',
        newHint: 'Comportamento atual: a cotação vai para a aba Cotações.',
        existingLabel: 'Adicionar a uma cotação já criada',
        existingHint: 'Os trechos entram nela e o custo e a venda do voo são somados aos valores que já existem.',
        exclude: groupMatch ? groupMatch[1] : '',
      };
    }
    return null;
  }

  // Captura antes do carregamento global, para que o envio só aconteça após a escolha.
  document.addEventListener('click', async (event) => {
    const trigger = event.target?.closest?.('button,input[type="submit"]');
    if (!trigger || trigger.closest('.qt-dialog')) return;
    if (trigger.type && trigger.type !== 'submit') return;
    const form = trigger.form || trigger.closest('form');
    if (!form || form.dataset.qtChosen === '1') return;
    const config = configFor(form);
    if (!config) return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation?.();
    const choice = await window.dbmChooseQuoteTarget(config);
    if (!choice) return;
    setHidden(form, 'target_group_id', choice.mode === 'existing' ? choice.groupId : '');
    setHidden(form, 'client_name', choice.clientName || '');
    form.dataset.qtChosen = '1';
    window.dbmShowLoader?.(choice.mode === 'existing' ? 'Adicionando à cotação…' : 'Criando cotação…');
    HTMLFormElement.prototype.submit.call(form);
  }, true);
})();
