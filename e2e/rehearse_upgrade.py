"""Rehearse upgrading from the single-app version (before Phase 1), end to end.

    python e2e/rehearse_upgrade.py --database-url postgresql://.../empty_db [--walkthrough]

1. Check out the last single-app commit in a temporary git worktree, build a SQLite database with
   its own demo seed, and export it with `dumpdata school` (docs/UPGRADING.md, step 2).
2. With the current code: convert the export, migrate the empty target database and load it
   (steps 3 and 4).
3. With --walkthrough: run e2e/walkthrough.py on the upgraded data, signing in with the password
   the old seed printed.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY_COMMIT = "623ca60"  # the last commit of the single-app version
THROWAWAY_KEY = "rehearsal-only-key-never-deployed-0123456789-abcdefghijklmnopqrstuv"


def python(args, cwd, env, capture=False):
    print("  $", " ".join(map(str, args)))
    result = subprocess.run(
        [sys.executable, "-X", "utf8", *map(str, args)],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=capture,
        text=True,
        encoding="utf-8",
    )
    return result.stdout if capture else None


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--database-url", required=True, help="an empty PostgreSQL database")
    parser.add_argument("--walkthrough", action="store_true")
    args = parser.parse_args()

    folder = Path(tempfile.mkdtemp(prefix="edunexa-upgrade-"))
    old = folder / "single-app"
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(old), LEGACY_COMMIT], cwd=ROOT, check=True
    )
    try:
        legacy_env = {
            **os.environ,
            "DJANGO_SECRET_KEY": THROWAWAY_KEY,
            "DEBUG": "1",
            "DATABASE_URL": "",
            "DJANGO_SETTINGS_MODULE": "config.settings",
        }
        python(["manage.py", "migrate", "--noinput"], old, legacy_env)
        printed = python(["manage.py", "seed_demo"], old, legacy_env, capture=True)
        password = re.search(r"Demo password for all accounts: (\S+)", printed).group(1)
        legacy, upgraded = folder / "legacy.json", folder / "upgraded.json"
        python(["manage.py", "dumpdata", "school", "--indent", "2", "-o", legacy], old, legacy_env)

        env = {
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "config.settings.dev",
            "DJANGO_SECRET_KEY": os.environ.get("DJANGO_SECRET_KEY", THROWAWAY_KEY),
            "DATABASE_URL": args.database_url,
            "REDIS_URL": "",
        }
        python(["manage.py", "convert_legacy_data", legacy, upgraded], ROOT, env)
        python(["manage.py", "migrate", "--noinput"], ROOT, env)
        python(["manage.py", "loaddata", upgraded], ROOT, env)
        print(f"Upgraded data loaded. The old seed's password: {password}")
        if args.walkthrough:
            python([ROOT / "e2e" / "walkthrough.py", password], ROOT, env)
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(old)], cwd=ROOT, check=False)
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    main()
