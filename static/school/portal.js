const menu = document.getElementById('menu-toggle');
if (menu) menu.addEventListener('click', () => { const open = document.getElementById('sidebar').classList.toggle('open'); menu.setAttribute('aria-expanded', String(open)); });
document.querySelectorAll('form[data-confirm]').forEach(form => form.addEventListener('submit', event => { if (!window.confirm(form.dataset.confirm)) event.preventDefault(); }));
document.querySelectorAll('.print-button').forEach(button => button.addEventListener('click', () => window.print()));
const present = document.getElementById('mark-present');
if (present) present.addEventListener('click', () => document.querySelectorAll('select[name^="status_"]:not(:disabled)').forEach(select => { select.value = 'P'; }));
