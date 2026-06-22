"""Guard: the suite must run against an isolated test DB, never production.

Regression test for the data-loss incident where the session fixture's
drop_all() wiped the production database because tests ran against it.
"""
from conftest import TEST_DATABASE_URL, engine
from sqlalchemy.engine import make_url

from showcat.core.database import DATABASE_URL as PROD_DATABASE_URL


def test_test_engine_is_not_prod() -> None:
    assert str(engine.url) != str(make_url(PROD_DATABASE_URL))


def test_test_db_name_is_suffixed() -> None:
    assert (make_url(TEST_DATABASE_URL).database or "").endswith("_test")


def test_test_db_differs_from_prod_db_name() -> None:
    prod_db = make_url(PROD_DATABASE_URL).database
    test_db = make_url(TEST_DATABASE_URL).database
    assert test_db != prod_db
