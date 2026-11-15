"""Operational commands.

    python -m app.cli generate-env-secrets        # print fresh JWT_SECRET / ENCRYPTION_KEYS / HASH_PEPPER
    python -m app.cli create-superadmin --email ops@example.com --name "Ops Lead"   # prompts for password
"""

import argparse
import getpass
import secrets
import sys

from app.core.crypto import generate_fernet_key


def _generate_env_secrets(_: argparse.Namespace) -> int:
    print(f"JWT_SECRET={secrets.token_urlsafe(48)}")
    print(f"ENCRYPTION_KEYS={generate_fernet_key()}")
    print(f"HASH_PEPPER={secrets.token_urlsafe(32)}")
    return 0


def _create_superadmin(args: argparse.Namespace) -> int:
    from app.core.errors import AppError
    from app.db.session import get_sessionmaker
    from app.models.enums import RoleName
    from app.services.users import create_user

    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Confirm password: "):
            print("Passwords do not match", file=sys.stderr)
            return 1
    with get_sessionmaker()() as db:
        try:
            user = create_user(
                db, email=args.email, full_name=args.name, password=password, role=RoleName.SUPER_ADMIN
            )
            db.commit()
        except AppError as exc:
            db.rollback()
            print(f"Error: {exc.message}", file=sys.stderr)
            return 1
    print(f"Created SUPER_ADMIN {user.email} ({user.id})")
    return 0


def _run_jobs(_args) -> int:
    from app.workers import run_once

    print(run_once())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("generate-env-secrets", help="Print new random secrets for .env").set_defaults(func=_generate_env_secrets)

    p = sub.add_parser("create-superadmin", help="Create a Super Admin user")
    p.add_argument("--email", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--password-stdin", action="store_true", help="Read password from stdin (for automation)")
    p.set_defaults(func=_create_superadmin)

    sub.add_parser("run-jobs", help="Run the background jobs once (payment expiry)").set_defaults(func=_run_jobs)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
