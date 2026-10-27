/*
 * Calculadora em etapas no celular (até 760px).
 * 1. Companhia  →  2. Essenciais e tipo de voo  →  3. Cálculos  →  4. Opcionais  →  Salvar
 *
 * No computador nada muda. Os dados, as rotas e o salvamento são exatamente os
 * mesmos: só a apresentação é dividida em partes.
 */
(() => {
  'use strict';
  const grid = document.querySelector('.wizard-grid.old-calculation-layout');
  const form = document.getElementById('quoteForm');
  if (!grid || !form) return;

  const media = window.matchMedia('(max-width: 760px)');
  const STEPS = [
    {n: 1, label: 'Companhia'},
    {n: 2, label: 'Essenciais'},
    {n: 3, label: 'Cálculo'},
    {n: 4, label: 'Opcionais'},
  ];
  const MAP = [
    [1, '.selector-panel'],
    [2, '.calc-selected-airline, .category-helper, .type-tabs, #operationProfilePanel, .segment-scope-panel, #skipAirportPanel'],
    [3, '[data-standard-calculation-section], #skipFinancialPanel'],
    [4, '#optionMetadataSection, .optional-bottom-stack, .sticky-form-actions'],
  ];

  const params = new URLSearchParams(location.search);
  const selectedAirline = grid.querySelector('.airline-mini.active strong')?.textContent?.trim() || '';
  // Escolheu a companhia (ou a categoria) agora, ou está editando: começa na etapa 2.
  let current = (params.has('airline_id') || params.has('type_id') || params.has('edit_id') || params.has('option_id')) ? 2 : 1;

  MAP.forEach(([step, selector]) => {
    grid.querySelectorAll(selector).forEach((el) => {
      if (!el.closest('[data-mstep]') || el.closest('[data-mstep]') === el) el.dataset.mstep = String(step);
    });
  });
  grid.querySelector('.calc-workflow-guide')?.setAttribute('data-mstep-hide', '1');

  // Barra de etapas no topo
  const stepper = document.createElement('nav');
  stepper.className = 'mcalc-stepper';
  stepper.setAttribute('aria-label', 'Etapas da calculadora');
  stepper.innerHTML = STEPS.map((s) => `<button type="button" data-goto="${s.n}" data-confirm-ignore="1"><b>${s.n}</b><span>${s.label}</span></button>`).join('');
  grid.parentNode.insertBefore(stepper, grid);

  // Navegação inferior
  const nav = document.createElement('div');
  nav.className = 'mcalc-nav';
  nav.innerHTML = `
    <button type="button" class="ghost-button" data-mcalc-prev data-confirm-ignore="1">← Voltar</button>
    <span class="mcalc-nav-info"></span>
    <button type="button" class="primary-button" data-mcalc-next data-confirm-ignore="1">Próximo →</button>`;
  grid.appendChild(nav);
  const prevButton = nav.querySelector('[data-mcalc-prev]');
  const nextButton = nav.querySelector('[data-mcalc-next]');
  const info = nav.querySelector('.mcalc-nav-info');

  function stepFields(step) {
    return [...grid.querySelectorAll(`[data-mstep="${step}"]`)]
      .flatMap((el) => [...el.querySelectorAll('input, select, textarea')])
      .filter((field) => !field.disabled && field.type !== 'hidden' && !field.closest('[hidden]'));
  }

  function validStep(step) {
    for (const field of stepFields(step)) {
      if (!field.checkValidity()) {
        field.reportValidity();
        field.focus({preventScroll: false});
        return false;
      }
    }
    return true;
  }

  function render(scroll) {
    const on = media.matches;
    grid.classList.toggle('is-mobile-steps', on);
    document.body.classList.toggle('mcalc-active', on);
    stepper.hidden = !on;
    nav.hidden = !on;
    if (!on) return;
    grid.dataset.mstepCurrent = String(current);
    stepper.querySelectorAll('[data-goto]').forEach((button) => {
      const n = Number(button.dataset.goto);
      button.classList.toggle('is-active', n === current);
      button.classList.toggle('is-done', n < current);
    });
    prevButton.hidden = current === 1;
    nextButton.hidden = current === 4;
    if (current === 1) {
      nextButton.textContent = selectedAirline ? `Continuar com ${selectedAirline} →` : 'Escolha uma companhia';
      nextButton.disabled = !selectedAirline;
      info.textContent = '';
    } else {
      nextButton.disabled = false;
      nextButton.textContent = current === 3 ? 'Opcionais →' : 'Próximo →';
      info.textContent = `Etapa ${current} de 4`;
    }
    if (scroll) stepper.scrollIntoView({behavior: 'smooth', block: 'start'});
  }

  function go(step, scroll = true) {
    current = Math.min(4, Math.max(1, step));
    render(scroll);
  }

  nextButton.addEventListener('click', () => {
    if (current >= 2 && !validStep(current)) return;
    go(current + 1);
  });
  prevButton.addEventListener('click', () => go(current - 1));
  stepper.addEventListener('click', (event) => {
    const button = event.target.closest('[data-goto]');
    if (!button) return;
    const target = Number(button.dataset.goto);
    if (target > current) {
      if (current === 1 && !selectedAirline) return;
      for (let s = Math.max(2, current); s < target; s += 1) {
        if (!validStep(s)) { go(s); return; }
      }
    }
    go(target);
  });

  // Se o envio falhar por campo obrigatório em outra etapa, abre a etapa certa.
  form.addEventListener('invalid', (event) => {
    if (!media.matches) return;
    const holder = event.target.closest('[data-mstep]');
    const step = holder ? Number(holder.dataset.mstep) : 0;
    if (step && step !== current) {
      go(step, false);
      setTimeout(() => { event.target.reportValidity(); event.target.focus(); }, 80);
    }
  }, true);

  (media.addEventListener ? media.addEventListener('change', () => render(false)) : media.addListener(() => render(false)));
  render(false);
})();
