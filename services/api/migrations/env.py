from alembic import context
from app.database import create_database_engine
from app.settings import Settings

if context.is_offline_mode():
    context.configure(
        url=Settings().database_url, literal_binds=True, dialect_opts={"paramstyle": "named"}
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    supplied_connection = context.config.attributes.get("connection")
    if supplied_connection is not None:
        context.configure(connection=supplied_connection)
        with context.begin_transaction():
            context.run_migrations()
    else:
        engine = create_database_engine(Settings())
        with engine.connect() as connection:
            context.configure(connection=connection)
            with context.begin_transaction():
                context.run_migrations()
        engine.dispose()
