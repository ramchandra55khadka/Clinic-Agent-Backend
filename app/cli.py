"""Administrative CLI: `python -m app.cli <command>`.

Used to bootstrap the first administrator (registration always creates patients)
and to manage roles without touching the database by hand.
"""

import argparse
import sys

from app.database import crud
from app.database.database import SessionLocal
from app.database.schema import UserRegister
from app.services.auth import hash_password


def promote_admin(email: str) -> int:
    with SessionLocal() as db:
        user = crud.get_user_by_email(db, email)
        if user is None:
            print(f"No account found for {email}", file=sys.stderr)
            return 1
        crud.set_user_role(db, user, "admin")
        crud.log_audit(db, action="admin.promoted", actor_email=email, entity="user", entity_id=user.id, detail="via CLI")
    print(f"{email} is now an admin")
    return 0


def create_admin(email: str, password: str, full_name: str, phone: str | None) -> int:
    with SessionLocal() as db:
        if crud.get_user_by_email(db, email):
            print(f"{email} already exists; use promote-admin instead", file=sys.stderr)
            return 1

        payload = UserRegister(full_name=full_name, email=email, password=password, phone=phone)
        user = crud.create_user_account(db, payload, hash_password(password))
        crud.set_user_role(db, user, "admin")
        crud.log_audit(db, action="admin.created", actor_email=email, entity="user", entity_id=user.id, detail="via CLI")

    print(f"Admin {email} created")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description="Clinic Assistant administration")
    subparsers = parser.add_subparsers(dest="command", required=True)

    promote = subparsers.add_parser("promote-admin", help="Grant the admin role to an existing account")
    promote.add_argument("--email", required=True)

    create = subparsers.add_parser("create-admin", help="Create a new administrator account")
    create.add_argument("--email", required=True)
    create.add_argument("--password", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--phone", default=None)

    args = parser.parse_args(argv)

    if args.command == "promote-admin":
        return promote_admin(args.email)
    if args.command == "create-admin":
        return create_admin(args.email, args.password, args.name, args.phone)
    parser.error(f"unknown command {args.command}")  # pragma: no cover
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())