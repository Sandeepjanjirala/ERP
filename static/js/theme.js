// Apply a saved light/dark choice before the page paints, so there is no flash of the wrong theme.
// Loaded in <head> without `defer` on purpose. Without a saved choice, CSS follows the system.
(function () {
  try {
    var saved = window.localStorage.getItem("edunexa-theme");
    if (saved === "light" || saved === "dark") {
      document.documentElement.dataset.theme = saved;
    }
  } catch (error) {
    // Storage can be blocked (private windows); the system theme still applies.
  }
})();
