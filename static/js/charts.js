// Dashboard charts. The numbers come from a <script type="application/json"> block written by
// the server (json_script), so no inline script runs and the CSP stays "script-src 'self'".
(function () {
  "use strict";

  var source = document.getElementById("dashboard-charts");
  if (!source || typeof Chart === "undefined") {
    return;
  }
  var data = JSON.parse(source.textContent);
  var css = getComputedStyle(document.documentElement);
  function token(name) {
    return css.getPropertyValue(name).trim();
  }

  Chart.defaults.font.family = token("--font-sans");
  Chart.defaults.color = token("--color-text-muted");
  var grid = token("--color-border");
  var percent = {
    min: 0,
    max: 100,
    grid: { color: grid },
    ticks: { callback: function (value) { return value + "%"; } }
  };

  var trend = document.getElementById("attendance-trend");
  if (trend && data.trend && data.trend.length) {
    new Chart(trend, {
      type: "line",
      data: {
        labels: data.trend.map(function (point) { return point.label; }),
        datasets: [{
          label: "Attendance",
          data: data.trend.map(function (point) { return point.rate; }),
          borderColor: token("--color-primary"),
          backgroundColor: token("--color-primary-soft"),
          fill: true,
          tension: 0.3,
          pointRadius: 2,
          spanGaps: true
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: { y: percent, x: { grid: { display: false } } },
        plugins: { legend: { display: false } }
      }
    });
  }

  var branches = document.getElementById("branch-comparison");
  if (branches && data.branches && data.branches.length) {
    new Chart(branches, {
      type: "bar",
      data: {
        labels: data.branches.map(function (row) { return row.branch; }),
        datasets: [{
          label: "Attendance, last 30 days",
          data: data.branches.map(function (row) { return row.rate; }),
          backgroundColor: token("--color-accent"),
          borderRadius: 6,
          maxBarThickness: 48
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: { y: percent, x: { grid: { display: false } } },
        plugins: { legend: { display: false } }
      }
    });
  }
})();
