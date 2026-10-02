"""Administrative CLI: `python -m app.cli <command>`.

Used to bootstrap the first administrator (public registration always creates
patients) and to manage roles without touching the database by hand.
"""

import argparse
import os
import sys

from pydantic import ValidationError

from app import repositories
from app.core.roles import ADMIN, ROLE_LABELS, ROLES
from app.db.session import SessionLocal
from app.models.user_profile import split_display_name
from app.schemas.user_auth import UserRegister
from app.schemas.user_profile import UserProfileCreate
from app.services.auth import hash_password


def _validation_error_message(exc: ValidationError) -> str:
    messages = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()))
        message = error.get("msg", "Invalid value")
        messages.append(f"{location}: {message}" if location else message)
    return "; ".join(messages)


def bootstrap_admin() -> int:
    """Creates the first administrator from env vars, once.

    This command is intended for deployment pipelines after migrations have run
    and before the ASGI server starts. It intentionally does not expose an HTTP
    setup surface, and it no-ops when any administrator already exists.
    """
    email = os.getenv("BOOTSTRAP_ADMIN_EMAIL")
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD")
    # The env var stays a single display name; the profile stores first/last.
    first_name, last_name = split_display_name(os.getenv("BOOTSTRAP_ADMIN_NAME") or "Clinic Administrator")
    phone = os.getenv("BOOTSTRAP_ADMIN_PHONE") or None

    if not email and not password:
        return 0
    if not email or not password:
        print(
            "BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD must both be set",
            file=sys.stderr,
        )
        return 1

    try:
        payload = UserRegister(email=email, password=password)
    except ValidationError as exc:
        print(f"Invalid bootstrap admin configuration: {_validation_error_message(exc)}", file=sys.stderr)
        return 1

    with SessionLocal() as db:
        if repositories.get_all_users(db, role=ADMIN):
            return 0

        existing = repositories.get_user_by_email(db, str(payload.email))
        if existing is not None:
            repositories.set_user_role(db, existing, ADMIN)
            repositories.revoke_user_refresh_tokens(db, existing.id)
            user = existing
            detail = "existing account promoted to admin; via bootstrap-admin"
        else:
            user = repositories.create_user_account(db, payload, hash_password(password), role=ADMIN)
            repositories.create_user_profile(
                db,
                user,
                UserProfileCreate(first_name=first_name, last_name=last_name, phone=phone),
            )
            detail = "role=admin; via bootstrap-admin"

        repositories.log_audit(
            db,
            action="user.bootstrap_admin",
            actor_email="bootstrap",
            entity="user",
            entity_id=user.id,
            detail=detail,
        )
    return 0

def set_role(email: str, role: str) -> int:
    """Grants a role to an existing account (patient, staff or admin)."""
    with SessionLocal() as db:
        user = repositories.get_user_by_email(db, email)
        if user is None:
            print(f"No account found for {email}", file=sys.stderr)
            return 1
        previous = user.role
        repositories.set_user_role(db, user, role)
        repositories.revoke_user_refresh_tokens(db, user.id)
        repositories.log_audit(
            db,
            action="user.role_changed",
            actor_email=email,
            entity="user",
            entity_id=user.id,
            detail=f"{previous} -> {role}; via CLI",
        )
    print(f"{email} is now {ROLE_LABELS.get(role, role)} ({previous} -> {role})")
    return 0


def create_user(email: str, password: str, full_name: str, phone: str | None, role: str) -> int:
    """Creates an account with an explicit role — used to bootstrap staff/admins.

    ``full_name`` is a single display string (the ``--name`` flag); it is split
    into the profile's ``first_name``/``last_name`` columns.
    """
    first_name, last_name = split_display_name(full_name)

    with SessionLocal() as db:
        if repositories.get_user_by_email(db, email):
            print(f"{email} already exists; use set-role instead", file=sys.stderr)
            return 1

        payload = UserRegister(email=email, password=password)
        user = repositories.create_user_account(db, payload, hash_password(password), role=role)
        repositories.create_user_profile(
            db,
            user,
            UserProfileCreate(first_name=first_name, last_name=last_name, phone=phone),
        )
        repositories.log_audit(
            db,
            action="user.created",
            actor_email=email,
            entity="user",
            entity_id=user.id,
            detail=f"role={role}; via CLI",
        )

    print(f"{ROLE_LABELS.get(role, role)} {email} created")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description="Clinic Assistant administration")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "bootstrap-admin",
        help="Create the first admin from BOOTSTRAP_ADMIN_* env vars; safe to run repeatedly",
    )

    create = subparsers.add_parser(
        "create-user",
        aliases=["create-admin"],
        help="Create an account with a given role (alias: create-admin)",
    )
    create.add_argument("--email", required=True)
    create.add_argument("--password", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--phone", default=None)
    create.add_argument("--role", choices=ROLES, default=ADMIN, help="patient, staff or admin")

    promote = subparsers.add_parser(
        "set-role",
        aliases=["promote-admin"],
        help="Change an existing account's role (alias: promote-admin)",
    )
    promote.add_argument("--email", required=True)
    promote.add_argument("--role", choices=ROLES, default=ADMIN)

    args = parser.parse_args(argv)

    if args.command == "bootstrap-admin":
        return bootstrap_admin()
    if args.command in ("create-user", "create-admin"):
        return create_user(args.email, args.password, args.name, args.phone, args.role)
    if args.command in ("set-role", "promote-admin"):
        return set_role(args.email, args.role)
    parser.error(f"unknown command {args.command}")  # pragma: no cover
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())