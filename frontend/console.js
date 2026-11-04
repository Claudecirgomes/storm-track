/* Console navigation keeps the authenticated application as the source of data. */
(() => {
  const clock = document.querySelector('#console-clock');
  function updateClock() {
    const now = new Date();
    const format = new Intl.DateTimeFormat('pt-BR', {
      timeZone: 'America/Sao_Paulo', day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
    clock.dateTime = now.toISOString();
    clock.replaceChildren(document.createTextNode(format.format(now).replace(',', '')));
    const caption = document.createElement('small');
    caption.textContent = 'Horário de Brasília';
    clock.append(caption);
  }
  updateClock();
  setInterval(updateClock, 30000);
  for (const button of document.querySelectorAll('[data-console-target]')) {
    button.addEventListener('click', () => {
      document.querySelector('[data-view="monitor-view"]').click();
      const target = document.querySelector(button.dataset.consoleTarget);
      if (target) {
        target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        target.setAttribute('tabindex', '-1');
        target.focus({ preventScroll: true });
      }
    });
  }
  document.querySelector('#focus-maringa').addEventListener('click', () => {
    document.querySelector('#map-maringa').click();
    document.querySelector('.map-panel').scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
})();
