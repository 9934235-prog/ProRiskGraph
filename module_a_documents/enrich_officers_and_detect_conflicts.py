"""
enrich_officers_and_detect_conflicts.py  —  Доопрацювання Модуля А
══════════════════════════════════════════════════════════════════════
Що робить:
  1. Бере вручну зібраний реєстр посадових осіб (officers.csv) з адресами
     реєстрації (зібраними з відкритих джерел, напр. Опендатабот) і записує
     ці адреси у вузли Officer, які вже є в графі (REGISTERED_AT -> Address).
  2. Після цього виконує автоматичний Cypher-пошук збігу адреси
     Officer і Company — той самий механізм, що вже перевірений
     у demo_scenarios.py, але тепер на реальних вузлах графа.

Формат officers.csv (роздільник ;, кодування cp1251 — як у enrich_graph.py):
  Officer;Address
  Немченко Анатолій Миколайович;м. Селидове, вул. Шахтарська, 12

Запуск:
  python enrich_officers_and_detect_conflicts.py
"""

import pandas as pd
from neo4j import GraphDatabase

# ─── НАЛАШТУВАННЯ ────────────────────────────────────────────────────────────

FILE_PATH      = "officers.csv"
NEO4J_URI      = "bolt://localhost:7687"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "12password"

# ─── CYPHER ───────────────────────────────────────────────────────────────────

SET_OFFICER_ADDRESS_QUERY = """
MATCH (o:Officer {name: $officer_name})
MERGE (a:Address {full_address: $address})
MERGE (o)-[:REGISTERED_AT]->(a)
RETURN count(o) AS updated_count
"""

FIND_CONFLICTS_QUERY = """
MATCH (o:Officer)-[:REGISTERED_AT]->(a:Address)<-[:HAS_HQ_AT]-(c:Company)
RETURN o.name AS Посадова_особа, c.name AS Компанія, a.full_address AS Спільна_адреса
"""

# ─── ФУНКЦІЇ ──────────────────────────────────────────────────────────────────

def enrich_officers(session, df: pd.DataFrame):
    print("[1] Записуємо адреси посадових осіб у граф...\n")
    updated = 0
    not_found = 0

    for _, row in df.iterrows():
        officer_name = str(row.get("Officer", "")).strip()
        address = str(row.get("Address", "")).strip()

        if not officer_name or not address:
            continue

        result = session.run(
            SET_OFFICER_ADDRESS_QUERY,
            officer_name=officer_name,
            address=address,
        )
        count = result.single()["updated_count"]

        if count > 0:
            updated += 1
            print(f"  ✅ {officer_name} → {address}")
        else:
            not_found += 1
            print(f"  ⚠️  Не знайдено в графі (немає вузла Officer): {officer_name}")

    print(f"\n  Оновлено: {updated} | Не знайдено в графі: {not_found}\n")


def find_conflicts(session):
    print("[2] Шукаємо збіги адрес (потенційний конфлікт інтересів)...\n")
    rows = session.run(FIND_CONFLICTS_QUERY).data()

    if not rows:
        print("  Збігів адрес не знайдено — або даних ще недостатньо,")
        print("  або (що добре) конфліктів немає.\n")
        return

    print(f"  ⚠ Знайдено {len(rows)} потенційних збігів:\n")
    for r in rows:
        print(f"  • {r['Посадова_особа']}  ↔  {r['Компанія']}")
        print(f"    Спільна адреса: {r['Спільна_адреса']}\n")


def main():
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  Доопрацювання Модуля А — адреси + виявлення конфліктів ║")
    print("╚══════════════════════════════════════════════════════════╝\n")

    try:
        df = pd.read_csv(FILE_PATH, sep=";", encoding="cp1251")
        print(f"✅ Файл '{FILE_PATH}' зчитано: {len(df)} рядків.\n")
    except Exception as e:
        print(f"❌ Не вдалося прочитати {FILE_PATH}: {e}")
        return

    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
    except Exception as e:
        print(f"❌ Помилка підключення до Neo4j: {e}")
        return

    with driver.session() as session:
        enrich_officers(session, df)
        find_conflicts(session)

    driver.close()
    print("🚀 Готово!")


if __name__ == "__main__":
    main()
