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

// Ask before actions with lasting effects, such as publishing results or deactivating accounts.
document.querySelectorAll("form[data-confirm]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});

// Print / Save as PDF for student reports.
document.querySelectorAll("[data-print]").forEach((button) => {
  button.addEventListener("click", () => window.print());
});

// "Mark all present" sets every editable status on the attendance register.
document.querySelectorAll("[data-mark-all]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll('select[name^="status_"]:not(:disabled)').forEach((select) => {
      select.value = button.dataset.markAll;
    });
  });
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
