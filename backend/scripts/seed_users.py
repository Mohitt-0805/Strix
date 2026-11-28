"""Seed initial admin and investigator accounts without hard-coded passwords.

Reads STRIX_ADMIN_PASSWORD and STRIX_INVESTIGATOR_PASSWORD from the environment.
If either variable is unset, generates a random 16-byte URL-safe password and prints
it once to stdout. Existing usernames are skipped without modification.
"""

import os
import secrets
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import select  # noqa: E402

from backend.app.config import Settings, get_settings  # noqa: E402
from backend.app.db import create_db_engine, create_session_factory, init_db  # noqa: E402
from backend.app.models import User  # noqa: E402
from backend.app.security import hash_password  # noqa: E402

SEED_ACCOUNTS = (
    ("admin", "admin", "System Admin", "STRIX_ADMIN_PASSWORD"),
    ("investigator", "investigator", "Lead Investigator", "STRIX_INVESTIGATOR_PASSWORD"),
)


def seed_users(settings: Settings | None = None) -> dict[str, str]:
    """Ensure default admin and investigator users exist; return generated passwords."""
    cfg = settings or get_settings()
    engine = create_db_engine(cfg.db_path)
    init_db(engine)
    session_factory = create_session_factory(engine)
    generated: dict[str, str] = {}

    try:
        with session_factory() as db:
            for username, role, full_name, env_var in SEED_ACCOUNTS:
                existing = db.execute(
                    select(User).where(User.username == username)
                ).scalar_one_or_none()
                if existing is not None:
                    print(f"User '{username}' already exists; skipping.")
                    continue

                env_password = os.environ.get(env_var, "").strip()
                if env_password:
                    password = env_password
                    source_note = f"from {env_var}"
                else:
                    password = secrets.token_urlsafe(16)
                    generated[username] = password
                    source_note = f"generated once: {password}"

                user = User(
                    username=username,
                    password_hash=hash_password(password),
                    role=role,
                    full_name=full_name,
                    active=True,
                )
                db.add(user)
                db.commit()
                print(f"Created user '{username}' (role={role}, password {source_note})")
    finally:
        engine.dispose()

    return generated


def main() -> int:
    """CLI entrypoint for seeding initial users."""
    seed_users()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
