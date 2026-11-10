// Small progressive enhancements. Every page also works with JavaScript turned off.

// Mobile navigation drawer.
const sidebar = document.getElementById("sidebar");
const menuButton = document.getElementById("menu-toggle");
if (sidebar && menuButton) {
  const setOpen = (open) => {
    sidebar.classList.toggle("open", open);
    menuButton.setAttribute("aria-expanded", String(open));
  };
  menuButton.addEventListener("click", () => setOpen(!sidebar.classList.contains("open")));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setOpen(false);
  });
}

// Ctrl+K (Cmd+K on a Mac) jumps to the global search in the top bar.
const globalSearch = document.getElementById("global-search");
if (globalSearch) {
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      globalSearch.focus();
      globalSearch.select();
    }
  });
}

// Ask before actions with lasting effects, such as publishing results or deactivating accounts.
// Listened for on the document, so forms that htmx swaps in later are covered too.
document.addEventListener(
  "submit",
  (event) => {
    const form = event.target.closest("form[data-confirm]");
    if (form && !window.confirm(form.dataset.confirm)) event.preventDefault();
  },
  true,
);

// Print / Save as PDF for student reports.
document.addEventListener("click", (event) => {
  if (event.target.closest("[data-print]")) window.print();
});

// Light/dark toggle. The choice is remembered in this browser only.
const root = document.documentElement;
const prefersDark = window.matchMedia("(prefers-color-scheme: dark)");
const currentTheme = () => root.dataset.theme || (prefersDark.matches ? "dark" : "light");
document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
  const sync = () => button.setAttribute("aria-pressed", String(currentTheme() === "dark"));
  sync();
  prefersDark.addEventListener("change", sync);
  button.addEventListener("click", () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try {
      window.localStorage.setItem("edunexa-theme", next);
    } catch (error) {
      // Storage blocked: the theme still changes for this page view.
    }
    sync();
  });
});
