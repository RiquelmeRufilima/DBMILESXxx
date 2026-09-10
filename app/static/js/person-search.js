(() => {
  const escapeHtml = (value) => String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');

  const boolData = (value) => ['1', 'true', 'sim', 'yes', 'on'].includes(String(value || '').toLowerCase());

  function ensureHiddenId(input, wrapper) {
    let hidden = wrapper.querySelector('.person-id');
    if (!hidden && input.dataset.targetId) {
      hidden = document.getElementById(input.dataset.targetId) || document.querySelector(`[name="${CSS.escape(input.dataset.targetId)}"]`);
    }
    if (!hidden && input.name) {
      hidden = document.createElement('input');
      hidden.type = 'hidden';
      hidden.className = 'person-id';
      hidden.name = input.dataset.personIdName || `${input.name}_person_id`;
      input.insertAdjacentElement('afterend', hidden);
    }
    return hidden;
  }

  function createResultsContainer(wrapper) {
    let container = wrapper.querySelector('.search-results');
    if (container) return container;
    container = document.createElement('div');
    container.className = 'search-results person-search-results';
    container.hidden = true;
    wrapper.appendChild(container);
    return container;
  }

  function registrationUrl(input) {
    const rawType = String(input.dataset.personType || '').split(',')[0].trim();
    const params = new URLSearchParams({ quick: '1' });
    if (rawType) params.set('person_type', rawType);
    return `/persons/new?${params.toString()}`;
  }

  async function searchPersons(query, input) {
    const params = new URLSearchParams({ q: query || '', limit: '15' });
    if (input.dataset.personType) params.set('person_type', input.dataset.personType);
    const response = await fetch(`/persons/search?${params.toString()}`, { headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error(`Busca de pessoas falhou (${response.status})`);
    const data = await response.json();
    return Array.isArray(data.results) ? data.results : [];
  }

  function renderResults(results, container, input, hiddenId) {
    container.innerHTML = '';
    if (!results.length) {
      container.innerHTML = `
        <div class="person-search-empty">
          <strong>Nenhum cadastro encontrado.</strong>
          <small>Cadastre essa pessoa antes de usar o nome.</small>
          <a class="secondary-button tiny" href="${registrationUrl(input)}" target="_blank" rel="noopener">+ Cadastrar pessoa</a>
        </div>`;
      container.hidden = false;
      return;
    }

    results.forEach((person) => {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'search-result-item person-search-item';
      const documentText = person.cpf_cnpj || person.rg || 'sem documento';
      const phone = person.phone ? ` • ${escapeHtml(person.phone)}` : '';
      item.innerHTML = `
        <span>
          <strong>${escapeHtml(person.name)}</strong>
          <small>${escapeHtml(documentText)} • ${escapeHtml(person.person_type || 'pessoa')}${phone}</small>
        </span>
        <em class="badge ${person.is_complete ? 'success' : 'warn'}">${person.is_complete ? 'Completo' : 'Pendente'}</em>`;
      item.addEventListener('click', () => selectPerson(person, input, hiddenId, container));
      container.appendChild(item);
    });
    container.hidden = false;
  }

  function selectPerson(person, input, hiddenId, container) {
    input.value = person.name || '';
    input.dataset.selectedPersonName = input.value;
    input.dataset.selectedPersonId = String(person.id || '');
    if (hiddenId) hiddenId.value = String(person.id || '');
    input.setCustomValidity('');
    if (container) container.hidden = true;
    input.dispatchEvent(new CustomEvent('person-selected', { bubbles: true, detail: { person } }));
  }

  function validateSelection(input, hiddenId, show = false) {
    const requireSelection = boolData(input.dataset.requireSelection);
    const hasText = input.value.trim().length > 0;
    const valid = !hasText || Boolean(hiddenId?.value);
    if (requireSelection && !valid) {
      input.setCustomValidity('Selecione um cadastro da lista. Se não existir, cadastre a pessoa primeiro.');
      if (show) input.reportValidity();
      return false;
    }
    input.setCustomValidity('');
    return true;
  }

  function initPersonSearch(input) {
    if (!input || input.dataset.personSearchReady === '1') return;
    input.dataset.personSearchReady = '1';
    input.autocomplete = 'off';
    const wrapper = input.closest('.person-search-wrapper') || input.parentElement;
    if (!wrapper) return;
    wrapper.classList.add('person-search-wrapper');
    const hiddenId = ensureHiddenId(input, wrapper);
    const resultsContainer = createResultsContainer(wrapper);
    if (hiddenId?.value && input.value) {
      input.dataset.selectedPersonName = input.value;
      input.dataset.selectedPersonId = hiddenId.value;
    }

    let timeoutId = null;
    let requestSerial = 0;
    const runSearch = async () => {
      const serial = ++requestSerial;
      try {
        resultsContainer.innerHTML = '<div class="person-search-loading">Buscando cadastros...</div>';
        resultsContainer.hidden = false;
        const results = await searchPersons(input.value.trim(), input);
        if (serial !== requestSerial) return;
        renderResults(results, resultsContainer, input, hiddenId);
      } catch (error) {
        if (serial !== requestSerial) return;
        console.error(error);
        resultsContainer.innerHTML = '<div class="person-search-empty"><small>Não foi possível carregar os cadastros.</small></div>';
        resultsContainer.hidden = false;
      }
    };

    input.addEventListener('focus', runSearch);
    input.addEventListener('input', () => {
      const selectedName = String(input.dataset.selectedPersonName || '');
      if (!selectedName || input.value.trim() !== selectedName.trim()) {
        if (hiddenId) hiddenId.value = '';
        input.dataset.selectedPersonId = '';
      }
      input.setCustomValidity('');
      clearTimeout(timeoutId);
      timeoutId = setTimeout(runSearch, 180);
    });
    input.addEventListener('blur', () => {
      window.setTimeout(() => {
        resultsContainer.hidden = true;
        validateSelection(input, hiddenId, false);
      }, 180);
    });

    const form = input.closest('form');
    if (form && !input.dataset.personValidationBound) {
      input.dataset.personValidationBound = '1';
      form.addEventListener('submit', (event) => {
        if (!validateSelection(input, hiddenId, true)) event.preventDefault();
      });
    }
  }

  function scan(root = document) {
    root.querySelectorAll?.('.person-search').forEach(initPersonSearch);
  }

  window.initPersonSearch = initPersonSearch;
  window.selectPersonFromSearch = selectPerson;

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => scan());
  else scan();

  const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => mutation.addedNodes.forEach((node) => {
      if (!(node instanceof Element)) return;
      if (node.matches?.('.person-search')) initPersonSearch(node);
      scan(node);
    }));
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });
})();
