from collections.abc import Iterator

import pytest
from testcontainers.community.postgres import PostgresContainer


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine", driver="psycopg") as pg:
        yield pg.get_connection_url()
