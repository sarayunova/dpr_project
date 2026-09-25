"""User administration from the command line.

There's no sign-up page or reset-by-email (no outbound SMTP, per
docs/07_non_functional_requirements.md), so whoever runs the server
manages accounts here:

    python -m app.users create someone@ongc.co.in
    python -m app.users set-password someone@ongc.co.in
    python -m app.users deactivate someone@ongc.co.in
    python -m app.users activate someone@ongc.co.in
    python -m app.users list

Inside Docker: `docker compose exec app python -m app.users create ...`.
Passwords are always prompted for (never taken as an argument), so they
don't end up in shell history.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from app.auth import MIN_PASSWORD_LENGTH, hash_password, normalize_email
from app.database import SessionLocal
from app.models import User, UserSession


def _prompt_password() -> str:
    while True:
        password = getpass.getpass("Password: ")
        if len(password) < MIN_PASSWORD_LENGTH:
            print(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
            continue
        if getpass.getpass("Repeat password: ") != password:
            print("Passwords didn't match.")
            continue
        return password


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.users")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "set-password", "deactivate", "activate"):
        sub.add_parser(name).add_argument("email")
    sub.add_parser("list")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        if args.command == "list":
            for user in db.query(User).order_by(User.email):
                print(f"{user.email}\t{'active' if user.is_active else 'deactivated'}")
            return 0

        email = normalize_email(args.email)
        user = db.query(User).filter_by(email=email).one_or_none()

        if args.command == "create":
            if user is not None:
                print(f"{email} already exists -- use set-password to change it.")
                return 1
            db.add(User(email=email, password_hash=hash_password(_prompt_password())))
            db.commit()
            print(f"Created {email}.")
            return 0

        if user is None:
            print(f"No user {email}.")
            return 1

        if args.command == "set-password":
            user.password_hash = hash_password(_prompt_password())
        else:
            user.is_active = args.command == "activate"
        # Any credential/status change logs the user out everywhere.
        db.query(UserSession).filter_by(user_id=user.id).delete()
        db.commit()
        print(f"Updated {email}.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
