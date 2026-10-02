"""SQLAlchemy declarative base.

Importing this module registers every ORM model on ``Base.metadata`` (see the
bottom import): that is what Alembic autogenerate and
``Base.metadata.create_all`` rely on. Application code imports the base from
here and a specific model from its own module, e.g.
``from app.models.user_account import UserAccount``.
"""

from sqlalchemy.orm import declarative_base

Base = declarative_base()

# Import every model module so that simply importing ``app.db.base`` registers
# them all on ``Base.metadata``.
import app.models  # noqa: E402,F401

__all__ = ["Base"]
