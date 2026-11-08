/* Formulário de bagagens da opção. Contador informativo; cálculos seguem no backend. */
(function () {
  function update() {
    var a = document.querySelector('[name="bags_outbound"]');
    var b = document.querySelector('[name="bags_return"]');
    var out = document.getElementById('dbmBagOutboundCount');
    var ret = document.getElementById('dbmBagReturnCount');
    var total = document.getElementById('dbmBagTotalCount');
    if (!a || !b || !out || !ret || !total) return;
    function val(el) { return Math.max(0, Math.min(100, Math.floor(Number(el.value) || 0))); }
    var ida = val(a), volta = val(b);
    out.textContent = String(ida);
    ret.textContent = String(volta);
    total.textContent = String(ida + volta);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', update);
  else update();
  document.addEventListener('input', function (event) {
    if (event.target && (event.target.name === 'bags_outbound' || event.target.name === 'bags_return')) update();
  });
  document.addEventListener('change', function (event) {
    if (event.target && (event.target.name === 'bags_outbound' || event.target.name === 'bags_return')) update();
  });
})();
