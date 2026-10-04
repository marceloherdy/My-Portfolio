import pytest
from pyspark.sql import SparkSession


@pytest.fixture(scope="session")
def spark():
    """Local SparkSession for the src/pipeline/ tests.

    Requires an installed JVM (JDK) and a pyspark able to start a local
    session (the project's .venv `databricks-connect` blocks local sessions
    on purpose; use an environment with plain `pyspark` to run these tests).
    Without that, the tests that depend on this fixture are skipped
    automatically instead of failing.
    """
    try:
        session = (
            SparkSession.builder
            .master("local[1]")
            .appName("pytest")
            .config("spark.sql.shuffle.partitions", "1")
            .getOrCreate()
        )
    except Exception as exc:
        pytest.skip(f"Local SparkSession unavailable in this environment (missing JDK or databricks-connect active): {exc}")
        return
    yield session
    session.stop()
