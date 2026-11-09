"""The layering rule in docs/ARCHITECTURE.md, enforced: an app imports only from apps below it.

The contract lives in pyproject.toml ([tool.importlinter]); this runs it with every test run, so a
wrong-way import fails the build instead of waiting for a reviewer to notice.
"""

import contextlib
import io
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from importlinter.cli import lint_imports


class LayerTests(SimpleTestCase):
    def test_apps_import_only_from_the_apps_below_them(self):
        report = io.StringIO()
        with contextlib.redirect_stdout(report):
            result = lint_imports(
                config_filename=str(Path(settings.BASE_DIR, "pyproject.toml")), no_cache=True
            )
        self.assertEqual(result, 0, report.getvalue())
