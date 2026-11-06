# Vendored front-end libraries

Served from our own static files (no CDN), so the Content-Security-Policy stays `script-src 'self'`.
Each file is the package's own published file, checked against the hash jsDelivr publishes for it
(`https://data.jsdelivr.com/v1/packages/npm/<package>@<version>?structure=flat`).

| Library | Version | File | SHA-256 (base64) | Licence |
|---|---|---|---|---|
| [Chart.js](https://www.chartjs.org/) | 4.4.7 | `chartjs/chart.umd.js` (npm `dist/chart.umd.js`) | `KBLLiCX9xXRp6y97sFXpQpJE5ZmSBRHuR36ChJm2Mss=` | MIT, `chartjs/LICENSE.md` |

To upgrade: download the new version's file from `https://cdn.jsdelivr.net/npm/<package>@<version>/<path>`,
compare its hash with the published one, then update this table.
