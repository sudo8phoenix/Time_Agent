"""Create the isolated local integration-test database when it does not exist."""
from __future__ import annotations

import psycopg
from psycopg import sql


DATABASE = "progress_test"


def main() -> None:
    with psycopg.connect(
        "postgresql://progress:progress@127.0.0.1:5432/progress", autocommit=True
    ) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (DATABASE,)
        ).fetchone()
        if not exists:
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DATABASE)))
            print(f"Created isolated database {DATABASE}.")
        else:
            print(f"Isolated database {DATABASE} is ready.")


if __name__ == "__main__":
    main()
