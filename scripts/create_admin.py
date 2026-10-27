"""Create the first admin: python -m scripts.create_admin --email you@example.com --name "Your Name"
The password is read interactively (or from SLA_ADMIN_PASSWORD) - never hard-coded."""

import argparse
import getpass
import os
import sys

from app.core.config import get_settings
from app.core.exceptions import ConflictError
from app.core.security import validate_password_strength
from app.db.session import make_engine, make_session_factory
from app.models.enums import Role
from app.services import auth_service, icp_service


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--email", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--role", default="admin", choices=[r.value for r in Role])
    a = p.parse_args()
    password = os.environ.get("SLA_ADMIN_PASSWORD") or getpass.getpass("Password: ")
    try:
        validate_password_strength(password)
    except ValueError as exc:
        print(f"Weak password: {exc}")
        return 2
    factory = make_session_factory(make_engine(get_settings()))
    with factory() as s:
        icp_service.ensure_default(s)
        try:
            u = auth_service.create_user(s, email=a.email, full_name=a.name, password=password, role=Role(a.role), actor_id=None)
        except ConflictError as exc:
            print(exc.message)
            return 1
        print(f"Created {u.role.value} user {u.email}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
