/* Pacotes de operadora/consolidadora, comissão (lucro) e seguradoras.
 *
 * Usa o estado global do editor da cotação (cotacao_form.html): services,
 * flights, costItems, saleItems, commission, sale e as funções renderAll,
 * val, setVal, brMoney, parseMoney, setPersonField, requireRegisteredName.
 * Tudo é chamado só depois que a página carrega.
 *
 * Comissão = lucro. Ao salvar, os valores vão para o lugar certo:
 *  - operadora recebe do passageiro → Venda › Recebimento de comissão;
 *  - agência recebe do passageiro   → Valores de venda (valor cheio) e
 *                                      Valores de custo (líquido da operadora).
 * Cada lançamento leva um "ref"; ao editar, os antigos são trocados (sem duplicar).
 */
(() => {
  'use strict';
  const INSURER_LOGO_PREFIX = '/static/brand/seguros/';
  const round2 = (n) => Math.round((Number(n) || 0) * 100) / 100;
  const pctText = (n) => (Number(n) || 0).toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const parsePct = (v) => { const n = parseFloat(String(v || '').replace('%', '').replace(/\s/g, '').replace(/\./g, '').replace(',', '.')); return Number.isFinite(n) ? n : 0; };
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const today = () => (typeof todayIso === 'function' ? todayIso() : new Date().toISOString().slice(0, 10));
  const newId = (p) => p + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

  /* ---------- caixa de comissão (% ⇄ R$) ---------- */
  const boxes = {};
  function box(prefix) {
    if (boxes[prefix]) return boxes[prefix];
    const root = document.querySelector(`[data-commission-box="${prefix}"]`);
    if (!root) return null;
    const q = (k) => root.querySelector(`[data-cm="${k}"]`);
    const b = {root, sale: q('sale'), pct: q('pct'), value: q('value'), total: q('total'), net: q('net'), note: q('note'), last: 'pct', onChange: null};
    const refresh = () => {
      const sale = parseMoney(b.sale.value);
      if (b.last === 'pct') b.value.value = sale && b.pct.value !== '' ? brMoney(round2(sale * parsePct(b.pct.value) / 100)) : b.value.value;
      else b.pct.value = sale ? pctText(parseMoney(b.value.value) / sale * 100) : '';
      paint();
    };
    const paint = () => {
      const sale = parseMoney(b.sale.value), value = parseMoney(b.value.value);
      b.total.textContent = brMoney(value);
      b.net.textContent = brMoney(Math.max(0, sale - value));
      const warn = value > sale && sale > 0;
      b.note.classList.toggle('warn', warn);
      const mode = root.querySelector('input[type=radio]:checked')?.value;
      b.note.textContent = warn ? 'A comissão está maior que o valor de venda. Confira os números.'
        : !value ? '' : mode === 'agency'
          ? `Ao salvar: ${brMoney(sale)} em Valores de venda e ${brMoney(Math.max(0, sale - value))} em Valores de custo. Lucro: ${brMoney(value)}.`
          : `Ao salvar: ${brMoney(value)} em Venda › Recebimento de comissão.`;
      b.onChange && b.onChange(get(prefix));
    };
    b.sale.addEventListener('input', refresh);
    b.pct.addEventListener('input', () => { b.last = 'pct'; refresh(); });
    b.value.addEventListener('input', () => { b.last = 'value'; refresh(); });
    [b.sale, b.value].forEach((el) => el.addEventListener('blur', () => { if (el.value.trim()) el.value = brMoney(parseMoney(el.value)); }));
    root.querySelectorAll('input[type=radio]').forEach((r) => r.addEventListener('change', paint));
    b.paint = paint;
    return (boxes[prefix] = b);
  }
  function get(prefix) {
    const b = box(prefix); if (!b) return {sale: 0, pct: 0, value: 0, mode: 'operator'};
    return {
      sale: round2(parseMoney(b.sale.value)),
      pct: round2(parsePct(b.pct.value)),
      value: round2(parseMoney(b.value.value)),
      mode: b.root.querySelector('input[type=radio]:checked')?.value === 'agency' ? 'agency' : 'operator',
    };
  }
  function set(prefix, data) {
    const b = box(prefix); if (!b) return;
    const d = data || {};
    b.sale.value = Number(d.sale) ? brMoney(d.sale) : '';
    b.value.value = Number(d.value) ? brMoney(d.value) : '';
    b.pct.value = Number(d.pct) ? pctText(d.pct) : (Number(d.sale) && Number(d.value) ? pctText(d.value / d.sale * 100) : '');
    b.last = Number(d.value) ? 'value' : 'pct';
    const mode = d.mode === 'agency' ? 'agency' : 'operator';
    b.root.querySelectorAll('input[type=radio]').forEach((r) => { r.checked = r.value === mode; });
    b.paint();
  }

  /* ---------- lançamentos financeiros ---------- */
  function clearFinance(ref) {
    const drop = (arr) => { if (!Array.isArray(arr)) return; for (let i = arr.length - 1; i >= 0; i--) if (arr[i] && arr[i].ref === ref) arr.splice(i, 1); };
    drop(costItems); drop(saleItems);
    if (commission && typeof commission === 'object') drop(commission.receive);
  }
  function applyFinance(ref, o) {
    clearFinance(ref);
    const saleValue = round2(o.sale), profit = round2(o.value);
    if (!saleValue && !profit) return;
    const due = (typeof sale === 'object' && sale && sale.date) || today();
    const supplier = o.supplier || '', supplierId = o.supplier_id || null;
    if (o.mode === 'agency') {
      if (saleValue > 0) saleItems.push({ref, description: o.label, value: saleValue, account: '', category: o.saleCategory || 'Venda de Pacote', due_date: due, payment_method: '', installments: 1, paid: false});
      const net = round2(saleValue - profit);
      if (net > 0) costItems.push({ref, type: 'Dinheiro', program: '', milheiro: '', milhas: '', description: `${o.label} • líquido da operadora`, value: net, supplier, supplier_person_id: supplierId, account: '', category: o.costCategory || 'Pacote', due_date: due, payment_method: '', installments: 1, paid: false});
    } else if (profit > 0) {
      if (!Array.isArray(commission.receive)) commission.receive = [];
      commission.receive.push({ref, account: '', supplier, supplier_person_id: supplierId, payment_method: '', installments: 1, due_date: due, category: 'Comissão recebida', description: `Comissão • ${o.label}`, value: profit});
    }
  }

  /* ---------- seguradoras ---------- */
  function bindInsurer(container, otherWrap, otherInput, onPick) {
    const cards = [...container.querySelectorAll('.ins-card')];
    const pick = (card) => {
      cards.forEach((c) => c.setAttribute('aria-checked', c === card ? 'true' : 'false'));
      const isOther = card && !card.dataset.insurer;
      otherWrap.hidden = !isOther;
      if (isOther) otherInput.focus();
      onPick && onPick();
    };
    cards.forEach((c) => c.addEventListener('click', () => pick(c)));
    return {
      get() {
        const chosen = cards.find((c) => c.getAttribute('aria-checked') === 'true');
        if (!chosen) return {insurer: '', logo: ''};
        if (chosen.dataset.insurer) return {insurer: chosen.dataset.insurer, logo: chosen.dataset.logo || ''};
        return {insurer: otherInput.value.trim(), logo: ''};
      },
      set(name, logo) {
        const known = cards.find((c) => c.dataset.insurer && c.dataset.insurer === name);
        if (known) { pick(known); otherInput.value = ''; }
        else if (name) { pick(cards.find((c) => !c.dataset.insurer)); otherInput.value = name; }
        else { cards.forEach((c) => c.setAttribute('aria-checked', 'false')); otherWrap.hidden = true; otherInput.value = ''; }
      },
    };
  }
  let svcInsurer = null, pkgInsurer = null;
  function svcInsurerPicker() {
    if (svcInsurer) return svcInsurer;
    const fs = document.getElementById('insurerPicker'); if (!fs) return null;
    return (svcInsurer = bindInsurer(fs.querySelector('.ins-options'), fs.querySelector('.ins-other-name'), document.getElementById('svc_insurer_other')));
  }
  function pkgInsurerPicker() {
    if (pkgInsurer) return pkgInsurer;
    return (pkgInsurer = bindInsurer(document.querySelector('#packageModal .pkg-insurer'), document.querySelector('#packageModal .pkg-ins-other'), document.getElementById('pkg_ins_other')));
  }

  /* ---------- ganchos do modal de serviço (hospedagem, seguro) ---------- */
  window.dbmServiceModalOpen = (key, s) => {
    const wrap = document.getElementById('svcCommissionWrap');
    const isHotel = key === 'hotel';
    if (wrap) wrap.hidden = !isHotel;
    const saleField = document.getElementById('svc_sale_value')?.closest('label');
    if (saleField) saleField.hidden = isHotel; // na hospedagem o valor de venda fica na caixa de comissão
    if (isHotel) {
      const b = box('svc');
      if (b && !b.onChange) b.onChange = (c) => { if (c.sale && c.value) setVal('svc_value', brMoney(round2(c.sale - c.value))); };
      set('svc', {sale: s.sale_value || 0, pct: s.commission_pct || 0, value: s.commission_value || 0, mode: s.commission_mode});
    }
    const picker = document.getElementById('insurerPicker');
    if (picker) picker.hidden = key !== 'insurance';
    if (key === 'insurance') svcInsurerPicker()?.set(s.insurer || '', s.insurer_logo || '');
  };

  window.dbmServiceModalSave = (key, s, prev) => {
    ['package_ref', 'finance_ref'].forEach((k) => { if (prev && prev[k] && !s[k]) s[k] = prev[k]; });
    if (key === 'insurance') {
      const ins = svcInsurerPicker()?.get() || {insurer: '', logo: ''};
      s.insurer = ins.insurer;
      s.insurer_logo = ins.logo.startsWith(INSURER_LOGO_PREFIX) ? ins.logo : '';
      if (!s.name && s.insurer) s.name = `Seguro ${s.insurer}`;
    }
    if (key === 'hotel') {
      const c = get('svc');
      if (c.value > c.sale && c.sale > 0) { alert('A comissão não pode ser maior que o valor de venda.'); return false; }
      s.sale_value = c.sale || '';
      s.commission_pct = c.pct || 0;
      s.commission_value = c.value || 0;
      s.commission_mode = c.mode;
      if (c.sale && c.value) s.value = round2(c.sale - c.value);
      if (!s.finance_ref && (c.sale || c.value)) s.finance_ref = newId('h');
      if (s.finance_ref) {
        applyFinance('svc:' + s.finance_ref, {label: `Hospedagem ${s.name || ''}`.trim(), supplier: s.supplier, supplier_id: s.supplier_person_id, sale: c.sale, value: c.value, mode: c.mode, saleCategory: 'Venda de Hospedagem', costCategory: 'Hotel'});
      }
    }
    return true;
  };

  /* ---------- pacote ---------- */
  let editPackageIndex = null;
  const PART_KEYS = ['flight', 'hotel', 'transfer', 'insurance', 'tours'];
  const partLabels = {flight: '✈ Voo', hotel: '🏨 Hotel', transfer: '🚐 Transfer', insurance: '🛡 Seguro', tours: '🎟 Passeios'};

  function syncParts() {
    const checked = new Set([...document.querySelectorAll('#packageModal .pkg-inc:checked')].map((el) => el.value));
    document.querySelectorAll('#packageModal .pkg-part').forEach((sec) => { sec.hidden = !checked.has(sec.dataset.part); });
  }
  document.addEventListener('change', (e) => { if (e.target.closest && e.target.closest('#packageModal .pkg-includes')) syncParts(); });
  // Datas do pacote preenchem as do hotel e do voo quando estão vazias.
  document.addEventListener('change', (e) => {
    if (e.target.id === 'pkg_start_date') { if (!val('pkg_ht_in')) setVal('pkg_ht_in', e.target.value); if (!val('pkg_fl_out_date')) setVal('pkg_fl_out_date', e.target.value); }
    if (e.target.id === 'pkg_end_date') { if (!val('pkg_ht_out')) setVal('pkg_ht_out', e.target.value); if (!val('pkg_fl_back_date')) setVal('pkg_fl_back_date', e.target.value); }
  });

  window.openPackageModal = (index = null) => {
    if (!Array.isArray(services.package)) services.package = [];
    editPackageIndex = index;
    const p = index !== null ? (services.package[index] || {}) : {};
    const c = p.components || {};
    document.getElementById('packageModalTitle').textContent = index !== null ? 'Editar pacote' : 'Novo pacote';
    const fields = {
      pkg_name: p.name, pkg_destination: p.destination, pkg_reservation: p.reservation_number, pkg_start_date: p.start_date, pkg_end_date: p.end_date,
      pkg_link: p.link, pkg_guests: p.guests, pkg_notes: p.description,
      pkg_fl_airline: c.flight?.airline, pkg_fl_origin: c.flight?.origin, pkg_fl_destination: c.flight?.destination, pkg_fl_locator: c.flight?.locator,
      pkg_fl_out_date: c.flight?.out_date, pkg_fl_out_time: c.flight?.out_time, pkg_fl_out_number: c.flight?.out_number, pkg_fl_out_arrival: c.flight?.out_arrival,
      pkg_fl_back_date: c.flight?.back_date, pkg_fl_back_time: c.flight?.back_time, pkg_fl_back_number: c.flight?.back_number, pkg_fl_back_arrival: c.flight?.back_arrival,
      pkg_ht_name: c.hotel?.name, pkg_ht_address: c.hotel?.address, pkg_ht_type: c.hotel?.type, pkg_ht_in: c.hotel?.checkin, pkg_ht_out: c.hotel?.checkout,
      pkg_ht_rooms: c.hotel?.rooms ?? 1, pkg_ht_stars: c.hotel?.stars, pkg_tr_name: c.transfer?.name, pkg_tr_details: c.transfer?.details,
      pkg_ins_plan: c.insurance?.plan, pkg_tours: c.tours?.list,
    };
    Object.entries(fields).forEach(([id, v]) => setVal(id, v ?? ''));
    setPersonField('pkg_supplier', 'pkg_supplier_id', p.supplier || '', p.supplier_person_id || '');
    const inc = new Set(p.includes || []);
    document.querySelectorAll('#packageModal .pkg-inc').forEach((el) => { el.checked = inc.has(el.value); });
    syncParts();
    pkgInsurerPicker().set(c.insurance?.insurer || '', c.insurance?.logo || '');
    set('pkg', {sale: p.sale_value || 0, pct: p.commission_pct || 0, value: p.commission_value || 0, mode: p.commission_mode});
    document.getElementById('packageModal').showModal();
  };

  function removeLinked(id) {
    for (let i = flights.length - 1; i >= 0; i--) if (flights[i] && flights[i].package_ref === id) flights.splice(i, 1);
    ['hotel', 'transport', 'cruise', 'experiences', 'insurance', 'additional'].forEach((k) => {
      const arr = services[k]; if (!Array.isArray(arr)) return;
      for (let i = arr.length - 1; i >= 0; i--) if (arr[i] && arr[i].package_ref === id) arr.splice(i, 1);
    });
  }
  function iata(text) { const code = airportCode(text); return /^[A-Z]{3}$/.test(code) ? code : ''; }
  function flightRow(id, kind, d) {
    return {label: kind === 'ida' ? 'Voo de Ida (pacote)' : 'Voo de Volta (pacote)', kind, segment_key: `pkg-${id}-${kind}`, selected_schedule: true,
      airline: d.airline, flight_number: d.number || '', locator: d.locator || '', origin: d.origin, destination: d.destination,
      date: d.date, departure_date: d.date, departure_time: d.time || '', arrival_date: d.date, arrival_time: d.arrival || '',
      duration: '', purchase_number: d.purchase || '', class: '', connections: 'Direto', checkin_status: 'pendente', checkin_link: '',
      notes: d.note, bags_personal: 1, bags_carry: 1, bags_checked: 0, stops: [], package_ref: id};
  }

  window.savePackageFromModal = () => {
    if (!requireRegisteredName('pkg_supplier', 'pkg_supplier_id', 'a operadora')) return;
    const includes = [...document.querySelectorAll('#packageModal .pkg-inc:checked')].map((el) => el.value);
    const name = val('pkg_name').trim() || (val('pkg_destination').trim() ? `Pacote ${val('pkg_destination').trim()}` : 'Pacote');
    const c = get('pkg');
    if (c.value > c.sale && c.sale > 0) { alert('A comissão não pode ser maior que o valor do pacote.'); return; }
    const flight = {airline: val('pkg_fl_airline').trim(), origin: iata(val('pkg_fl_origin')), destination: iata(val('pkg_fl_destination')), locator: val('pkg_fl_locator').trim(),
      out_date: val('pkg_fl_out_date'), out_time: val('pkg_fl_out_time'), out_number: val('pkg_fl_out_number').trim(), out_arrival: val('pkg_fl_out_arrival'),
      back_date: val('pkg_fl_back_date'), back_time: val('pkg_fl_back_time'), back_number: val('pkg_fl_back_number').trim(), back_arrival: val('pkg_fl_back_arrival')};
    if (includes.includes('flight') && (!flight.origin || !flight.destination || !flight.out_date)) {
      alert('No voo do pacote, informe origem e destino (código de 3 letras, ex.: FOR e CUN) e a data de ida.');
      document.getElementById(!flight.origin ? 'pkg_fl_origin' : !flight.destination ? 'pkg_fl_destination' : 'pkg_fl_out_date')?.focus();
      return;
    }
    const ins = pkgInsurerPicker().get();
    if (!Array.isArray(services.package)) services.package = [];
    const prev = editPackageIndex !== null ? (services.package[editPackageIndex] || {}) : {};
    const id = prev.id || newId('p');
    const supplier = val('pkg_supplier').trim(), supplierId = val('pkg_supplier_id') || null;
    const reservation = val('pkg_reservation').trim();
    const start = val('pkg_start_date'), end = val('pkg_end_date');
    const pkg = {
      id, name, destination: val('pkg_destination').trim(), reservation_number: reservation, link: val('pkg_link').trim(),
      start_date: start, end_date: end, guests: Number(val('pkg_guests') || 0) || '', supplier, supplier_person_id: supplierId,
      includes, description: val('pkg_notes'),
      sale_value: c.sale || '', commission_pct: c.pct || 0, commission_value: c.value || 0, commission_mode: c.mode, value: round2(Math.max(0, c.sale - c.value)),
      components: {
        flight, hotel: {name: val('pkg_ht_name').trim(), address: val('pkg_ht_address').trim(), type: val('pkg_ht_type').trim(), checkin: val('pkg_ht_in'), checkout: val('pkg_ht_out'), rooms: Number(val('pkg_ht_rooms') || 0), stars: val('pkg_ht_stars')},
        transfer: {name: val('pkg_tr_name').trim(), details: val('pkg_tr_details').trim()},
        insurance: {insurer: ins.insurer, logo: ins.logo.startsWith(INSURER_LOGO_PREFIX) ? ins.logo : '', plan: val('pkg_ins_plan').trim()},
        tours: {list: val('pkg_tours').trim()},
      },
    };
    // Recria os itens do pacote (sem duplicar os de uma edição anterior).
    ['hotel', 'transport', 'experiences', 'insurance'].forEach((k) => { if (!Array.isArray(services[k])) services[k] = []; });
    removeLinked(id);
    const note = `Incluído no pacote ${name}.`; // sem o nome da operadora: pode ir para o PDF do cliente
    const base = {link: pkg.link, reservation_number: reservation, supplier, supplier_person_id: supplierId, value: 0, package_ref: id, description: note};
    if (includes.includes('flight')) {
      flights.push(flightRow(id, 'ida', {airline: flight.airline, origin: flight.origin, destination: flight.destination, date: flight.out_date, time: flight.out_time, arrival: flight.out_arrival, number: flight.out_number, locator: flight.locator || reservation, purchase: reservation, note}));
      if (flight.back_date) flights.push(flightRow(id, 'volta', {airline: flight.airline, origin: flight.destination, destination: flight.origin, date: flight.back_date, time: flight.back_time, arrival: flight.back_arrival, number: flight.back_number, locator: flight.locator || reservation, purchase: reservation, note}));
    }
    const h = pkg.components.hotel;
    if (includes.includes('hotel')) {
      const checkin = h.checkin || start, checkout = h.checkout || end;
      const nights = checkin && checkout ? Math.max(0, Math.round((Date.parse(checkout) - Date.parse(checkin)) / 86400000)) : 0;
      services.hotel.push({...defaultService('hotel'), ...base, name: h.name || `Hospedagem • ${name}`, address: h.address, type: h.type, start_date: checkin, end_date: checkout, nights, rooms: h.rooms, stars: h.stars, amenities: []});
    }
    if (includes.includes('transfer')) services.transport.push({...defaultService('transport'), ...base, name: pkg.components.transfer.name || 'Transfer', start_date: start, end_date: end, description: [pkg.components.transfer.details, note].filter(Boolean).join(' ')});
    if (includes.includes('insurance')) services.insurance.push({...defaultService('insurance'), ...base, name: ins.insurer ? `Seguro ${ins.insurer}` : 'Seguro viagem', insurer: ins.insurer, insurer_logo: pkg.components.insurance.logo, type: pkg.components.insurance.plan, start_date: start, end_date: end});
    if (includes.includes('tours')) {
      const list = pkg.components.tours.list.split(',').map((t) => t.trim()).filter(Boolean);
      (list.length ? list : ['Passeios do pacote']).forEach((t) => services.experiences.push({...defaultService('experiences'), ...base, name: t, start_date: start, end_date: end}));
    }
    applyFinance('pkg:' + id, {label: `Pacote ${name}`, supplier, supplier_id: supplierId, sale: c.sale, value: c.value, mode: c.mode, saleCategory: 'Venda de Pacote', costCategory: 'Pacote'});
    if (editPackageIndex !== null) services.package[editPackageIndex] = pkg; else services.package.push(pkg);
    closeDialog('packageModal');
    document.getElementById('packageAccordion')?.setAttribute('open', '');
    renderAll();
  };

  /* ---------- lista de serviços: editar / excluir / selos ---------- */
  function packageIndexById(id) { return (services.package || []).findIndex((p) => p && p.id === id); }

  window.dbmEditService = (key, i) => {
    const s = (services[key] || [])[i]; if (!s) return;
    if (key === 'package') return openPackageModal(i);
    if (s.package_ref) {
      const pi = packageIndexById(s.package_ref);
      if (pi >= 0 && confirm('Este item faz parte de um pacote. Abrir o pacote para editar tudo junto?\n\nCancelar = editar só este item.')) return openPackageModal(pi);
    }
    openServiceModal(key, i);
  };

  window.dbmDeleteService = (key, i) => {
    const s = (services[key] || [])[i]; if (!s) return;
    if (key === 'package') {
      if (!confirm(`Excluir o pacote "${s.name || 'Pacote'}"?\n\nTambém saem o voo, a hospedagem e os outros itens dele, e os valores lançados (venda, custo ou comissão).`)) return;
      removeLinked(s.id); clearFinance('pkg:' + s.id); services.package.splice(i, 1); renderAll(); return;
    }
    if (s.finance_ref) clearFinance('svc:' + s.finance_ref);
    services[key].splice(i, 1); renderAll();
  };

  window.dbmServiceBadges = (key, s) => {
    let out = '';
    if (key === 'package') {
      out += (s.includes || []).map((p) => `<span class="pkg-badge">${esc(partLabels[p] || p)}</span>`).join('');
      if (Number(s.sale_value)) out += `<span class="pkg-badge pkg-money">Venda ${esc(brMoney(s.sale_value))}</span>`;
      if (Number(s.commission_value)) out += `<span class="pkg-badge pkg-money">Comissão ${esc(brMoney(s.commission_value))}</span>`;
    } else if (s.package_ref) {
      out += '<span class="pkg-badge">Parte do pacote</span>';
    }
    if (key === 'insurance' && s.insurer) {
      const logo = String(s.insurer_logo || '');
      out += `<span class="ins-badge">${logo.startsWith(INSURER_LOGO_PREFIX) ? `<img src="${esc(logo)}" alt="">` : ''}${esc(s.insurer)}</span>`;
    }
    if (key === 'hotel' && Number(s.commission_value)) out += `<span class="pkg-badge pkg-money">Comissão ${esc(brMoney(s.commission_value))}</span>`;
    return out ? `<span class="svc-badges">${out}</span>` : '';
  };
})();
