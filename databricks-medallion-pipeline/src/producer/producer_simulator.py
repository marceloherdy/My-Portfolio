import json
import argparse
import os
import random
import time
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

def generate_simulated_data(output_dir: str = "/Volumes/databricks_course_ws_new/landing/events_volume", num_files: int = 5):
    """
    Gera arquivos JSON Lines com variações controladas de qualidade de dados.

    O conjunto gerado inclui valores nulos, ausência de atributos, evolução de
    schema, inconsistência de tipos, eventos fora de ordem e duplicidade
    conflitante para exercitar o pipeline.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    tz_local = ZoneInfo("America/Sao_Paulo")

    for file_nr in range(num_files):
        records = []
        batch_size = random.randint(10, 25)
        batch_id = uuid4().hex

        for i in range(batch_size):
            # Registro base utilizado como referência para os cenários de teste.
            event_timestamp = datetime.now(tz_local)
            record = {
                "event_id": f"evt_{batch_id}_{i}",
                "batch_id": batch_id,
                "user_id": f"usr_{100 + i}",
                "track_id": f"trk_{50 + i}",
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

            # Simula eventos atrasados e eventos com timestamp no futuro.
            if i % 6 == 0 and i != 0:
                delayed_timestamp = event_timestamp - timedelta(days=2)
                record["timestamp"] = delayed_timestamp.strftime("%Y-%m-%dT%H:%M:%S%z")
            elif i % 11 == 0:
                future_timestamp = event_timestamp + timedelta(days=1)
                record["timestamp"] = future_timestamp.strftime("%Y-%m-%dT%H:%M:%S%z")

            # Simula atributos vazios em vez de nulos ou ausentes.
            if i % 10 == 0 and i != 0:
                record["track_id"] = ""
                record["platform"] = ""

            records.append(record)

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
            time.sleep(5) 

    print("Processo de simulação finalizado com sucesso!")

# Permite executar o gerador diretamente no ambiente local ou no job Databricks.
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gera eventos JSON Lines para o landing zone.")
    parser.add_argument("--output-dir", default="/Volumes/databricks_course_ws_new/landing/events_volume")
    parser.add_argument("--num-files", type=int, default=5)
    args = parser.parse_args()
    generate_simulated_data(output_dir=args.output_dir, num_files=args.num_files)