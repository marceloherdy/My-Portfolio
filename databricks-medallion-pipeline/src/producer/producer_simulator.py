import json
import argparse
import os
import random
import time
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

# Pools de usuários e faixas: o id é sorteado (e não derivado do índice do registro) para que
# usuários ouçam várias faixas e faixas tenham vários ouvintes. Os pesos decrescentes criam
# faixas/usuários populares, tornando rankings e métricas de atividade informativos.
USER_POOL = [f"usr_{100 + n}" for n in range(100)]
USER_WEIGHTS = [1 / (n + 5) for n in range(len(USER_POOL))]
TRACK_POOL = [f"trk_{50 + n}" for n in range(60)]
TRACK_WEIGHTS = [1 / (n + 2) for n in range(len(TRACK_POOL))]


def build_record(i: int, event_timestamp: datetime, batch_id: str) -> dict:
    """Monta um único registro do lote, aplicando os cenários de qualidade por índice ``i``."""
    record = {
        "event_id": f"evt_{batch_id}_{i}",
        "batch_id": batch_id,
        "user_id": random.choices(USER_POOL, weights=USER_WEIGHTS)[0],
        "track_id": random.choices(TRACK_POOL, weights=TRACK_WEIGHTS)[0],
        "platform": "spotify_clone",
        "duration_played_sec": 180 + i,
        "timestamp": event_timestamp.strftime("%Y-%m-%dT%H:%M:%S%z")
    }

    # Simula um atributo obrigatório ausente em parte dos registros.
    if i % 3 == 0:
        record["user_id"] = None

    # Simula evolução de schema com um atributo adicional.
    if i % 4 == 0:
        record["device_type"] = random.choice(["mobile", "desktop", "smart_tv"])

    # Simula a ausência completa de uma chave do payload.
    if i % 7 == 0 and "user_id" in record:
        del record["user_id"]

    # Simula uma inconsistência de tipo em um registro específico.
    if i == 9:
        record["duration_played_sec"] = "INVALID_DURATION"

    # Simula um valor fora do domínio esperado para a duração.
    if i % 5 == 0 and i != 0:
        record["duration_played_sec"] = -10

    # Simula eventos atrasados e eventos com timestamp no futuro. O divisor do atraso (13) é
    # coprimo com os demais cenários para não coincidir sempre com user_id nulo (i % 3) ou
    # device_type presente (i % 4).
    if i % 13 == 0 and i != 0:
        delayed_timestamp = event_timestamp - timedelta(days=2)
        record["timestamp"] = delayed_timestamp.strftime("%Y-%m-%dT%H:%M:%S%z")
    elif i % 11 == 0:
        future_timestamp = event_timestamp + timedelta(days=1)
        record["timestamp"] = future_timestamp.strftime("%Y-%m-%dT%H:%M:%S%z")

    # Simula atributos vazios em vez de nulos ou ausentes.
    if i % 10 == 0 and i != 0:
        record["track_id"] = ""
        record["platform"] = ""

    return record


def generate_simulated_data(
    output_dir: str = "/Volumes/databricks_course_ws_new/landing/events_volume",
    num_files: int = 5,
    min_records: int = 10,
    max_records: int = 25,
    interval_sec: int = 5,
):
    """
    Gera arquivos JSON Lines com variações controladas de qualidade de dados.

    O conjunto gerado inclui valores nulos, ausência de atributos, evolução de
    schema, inconsistência de tipos, eventos fora de ordem e duplicidade
    conflitante para exercitar o pipeline.

    ``interval_sec`` precisa ser >= 1: o nome do arquivo tem resolução de
    segundos, então um intervalo menor sobrescreveria o arquivo anterior.
    """
    if min_records > max_records:
        raise ValueError("min_records não pode ser maior que max_records")
    if interval_sec < 1:
        raise ValueError("interval_sec precisa ser >= 1 (o nome do arquivo tem resolução de segundos)")

    os.makedirs(output_dir, exist_ok=True)

    tz_local = ZoneInfo("America/Sao_Paulo")

    for file_nr in range(num_files):
        records = []
        batch_size = random.randint(min_records, max_records)
        batch_id = uuid4().hex

        for i in range(batch_size):
            event_timestamp = datetime.now(tz_local)
            records.append(build_record(i, event_timestamp, batch_id))

        # Inclui uma duplicata conflitante para testar a regra de desempate da Silver.
        if len(records) > 0:
            duplicate_record = records[0].copy()
            duplicate_record["duration_played_sec"] = 999999
            duplicate_record["user_id"] = "usr_conflict"
            records.append(duplicate_record)

        # Identifica o lote com o horário local de São Paulo.
        timestamp_str = datetime.now(tz_local).strftime("%Y-%m-%dT%H%M%S%z")
        file_path = os.path.join(output_dir, f"eventos_com_caos_{timestamp_str}.json")

        # Persiste um registro JSON por linha para facilitar a ingestão incremental.
        with open(file_path, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        print(f"Arquivo {file_nr + 1}/{num_files} salvo com sucesso em: {file_path}")

        # Mantém um intervalo entre lotes para simular uma fonte incremental.
        if file_nr < num_files - 1:
            time.sleep(interval_sec)

    print("Processo de simulação finalizado com sucesso!")

# Permite executar o gerador diretamente no ambiente local ou no job Databricks.
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gera eventos JSON Lines para o landing zone.")
    parser.add_argument("--output-dir", default="/Volumes/databricks_course_ws_new/landing/events_volume")
    parser.add_argument("--num-files", type=int, default=5)
    parser.add_argument("--min-records", type=int, default=10, help="Mínimo de registros por arquivo")
    parser.add_argument("--max-records", type=int, default=25, help="Máximo de registros por arquivo")
    parser.add_argument("--interval-sec", type=int, default=5, help="Pausa entre arquivos (>= 1)")
    args = parser.parse_args()
    generate_simulated_data(
        output_dir=args.output_dir,
        num_files=args.num_files,
        min_records=args.min_records,
        max_records=args.max_records,
        interval_sec=args.interval_sec,
    )