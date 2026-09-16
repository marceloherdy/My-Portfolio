import pytest
from pyspark.sql import SparkSession


@pytest.fixture(scope="session")
def spark():
    """SparkSession local para os testes de src/pipeline/.

    Requer uma JVM (JDK) instalada e um pyspark capaz de subir uma sessão
    local (o `databricks-connect` do .venv do projeto bloqueia sessões
    locais de propósito — use um ambiente com `pyspark` puro para rodar
    estes testes). Sem isso, os testes que dependem desta fixture são
    pulados automaticamente em vez de falhar.
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
        pytest.skip(f"SparkSession local indisponível neste ambiente (JDK ausente ou databricks-connect ativo): {exc}")
        return
    yield session
    session.stop()
