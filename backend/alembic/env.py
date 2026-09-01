"""Alembic environment.

- URL 由 ``app.core.config.settings`` 注入（不写死在 alembic.ini）
- ``target_metadata`` 来自 ``app.db.base.Base``（导入 ``app.models`` 注册全部模型）
- 支持 ``-x db=test`` 切换到测试库（Q14：测试必须使用独立测试数据库）
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

from app import models  # noqa: F401  — 注册全部模型到 Base.metadata
from app.core.config import settings
from app.db.base import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolve_url() -> str:
    """Resolve the DB URL, honouring ``-x db=test``.

    The database name is swapped at the path level (last path segment);
    a naive ``str.replace`` would also rewrite the password (e.g. a DB
    password that contains the DB name).
    """
    url = settings.sqlalchemy_database_uri
    x_args = context.get_x_argument(as_dictionary=True)
    if x_args.get("db") == "test":
        from app.core.config import TEST_DB_SUFFIX

        base = settings.database_name
        if not base.endswith(TEST_DB_SUFFIX):
            base = f"{base}{TEST_DB_SUFFIX}"
        scheme_rest, _, query = url.partition("?")
        head, _, _db = scheme_rest.rpartition("/")
        url = f"{head}/{base}" + (f"?{query}" if query else "")
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    context.configure(
        url=_resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    config.set_main_option("sqlalchemy.url", _resolve_url())
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
