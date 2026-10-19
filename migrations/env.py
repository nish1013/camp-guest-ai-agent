from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from camp_agent.config import Settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

url = config.get_main_option("sqlalchemy.url") or Settings().database_url
engine = create_engine(url)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
