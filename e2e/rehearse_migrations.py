"""Rehearse the database migrations: every row must survive.

Build a throwaway database with an older release, then migrate it with the current code:

    python e2e/rehearse_migrations.py build --from v0.1.0 --database-url postgresql://.../rehearsal

Or check a copy of a real database (never the original: make the copy first):

    python e2e/rehearse_migrations.py check --database-url postgresql://.../copy_of_live
    python e2e/rehearse_migrations.py check --sqlite path/to/copy.sqlite3

Either way: snapshot every row, run `migrate` with the current code, snapshot again, and compare
(e2e/db_compare.py). "build" checks out the old release in a temporary git worktree and seeds it
with that release's own demo seed. Exit status 0 only if every row is identical.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from db_compare import compare  # noqa: E402
from db_snapshot import snapshot  # noqa: E402

THROWAWAY_KEY = "rehearsal-only-key-never-deployed-0123456789-abcdefghijklmnopqrstuv"


def env_for(database_url=None, sqlite=None):
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.dev",
        "DJANGO_SECRET_KEY": os.environ.get("DJANGO_SECRET_KEY", THROWAWAY_KEY),
        "REDIS_URL": "",
        "DEMO_MODE": "1",
    }
    if database_url:
        env["DATABASE_URL"] = database_url
    if sqlite:
        env["DATABASE_URL"] = ""
        env["SQLITE_PATH"] = str(sqlite)
    return env


def run(args, cwd, env):
    print("  $", " ".join(map(str, args)))
    subprocess.run([sys.executable, *map(str, args)], cwd=cwd, env=env, check=True)


def migrate_and_compare(target, env):
    before = snapshot(target)
    print(f"before: {sum(before['counts'].values())} rows in {len(before['counts'])} tables")
    run(["manage.py", "migrate", "--noinput"], ROOT, env)
    after = snapshot(target)
    problems = compare(before, after)
    print(
        f"after: {sum(after['counts'].values())} rows; new tables: {sorted(set(after['counts']) - set(before['counts']))}"
    )
    print("IDENTICAL" if not problems else "DIFFERENCES:\n  " + "\n  ".join(problems))
    return not problems, before, after


def build(args):
    if not args.database_url.startswith("postgres"):
        raise SystemExit("build needs an empty PostgreSQL database (--database-url).")
    import psycopg

    with psycopg.connect(args.database_url) as conn:
        tables = conn.execute(
            "select count(*) from pg_tables where schemaname='public'"
        ).fetchone()[0]
    if tables:
        raise SystemExit("The database isn't empty. Give a new, empty database for the rehearsal.")
    folder = Path(tempfile.mkdtemp(prefix="edunexa-rehearsal-"))
    old = folder / args.release
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(old), args.release], cwd=ROOT, check=True
    )
    try:
        env = env_for(args.database_url)
        run(["manage.py", "migrate", "--noinput"], old, env)
        run(["manage.py", "seed_demo", "--size", args.size], old, env)
        ok, before, after = migrate_and_compare(f"postgres:{args.database_url}", env)
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(old)], cwd=ROOT, check=False)
        shutil.rmtree(folder, ignore_errors=True)
    report(args, ok, before, after)


def check(args):
    if args.sqlite:
        target, env = f"sqlite:{args.sqlite}", env_for(sqlite=Path(args.sqlite).resolve())
    else:
        target, env = f"postgres:{args.database_url}", env_for(args.database_url)
    ok, before, after = migrate_and_compare(target, env)
    report(args, ok, before, after)


def report(args, ok, before, after):
    if args.report:
        Path(args.report).write_text(
            json.dumps({"ok": ok, "before": before, "after": after}, indent=1), encoding="utf-8"
        )
    sys.exit(0 if ok else 1)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    built = commands.add_parser("build", help="seed an older release, then migrate it")
    built.add_argument("--from", dest="release", default="v0.1.0")
    built.add_argument("--database-url", required=True)
    built.add_argument("--size", default="small", choices=["small", "full"])
    built.add_argument("--report")
    checked = commands.add_parser("check", help="migrate a copy of an existing database")
    target = checked.add_mutually_exclusive_group(required=True)
    target.add_argument("--database-url")
    target.add_argument("--sqlite")
    checked.add_argument("--report")
    args = parser.parse_args()
    build(args) if args.command == "build" else check(args)


if __name__ == "__main__":
    main()
