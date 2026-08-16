"""
add_winners.py  —  Довантаження переможців тендерів (Модуль Б, доопрацювання)
══════════════════════════════════════════════════════════════════════
Що робить:
  Для кожного тендера, вже завантаженого у Neo4j, робить додатковий запит
  до офіційного API Prozorro за tender_id, бере звідти блок "awards"
  (рішення про переможця) і записує:
    - вузол Company (edrpou, name, address)
    - зв'язок (Tender)-[:WINNER_IS]->(Company)
    - зв'язок (Organization)-[:PAID_TO]->(Company)
    - зв'язок (Company)-[:HAS_HQ_AT]->(Address)

Важливо щодо структури даних:
  У цій базі тендери записані БЕЗ лейбла Tender — натомість кожен вузол
  одразу отримав лейбл рівня ризику (LowRisk / MediumRisk / HighRisk),
  а властивість з ідентифікатором тендера зберігається як tender_id.
  Тому всі запити шукають вузол за умовою
  (t:LowRisk OR t:MediumRisk OR t:HighRisk), а не за (t:Tender).

Чому окремий запит, а не з тих самих даних:
  /api/search/tenders (який вже використовує prozorro_to_neo4j_v8.py) не містить
  блок awards. Цей блок є лише в детальній картці тендера —
  /api/2.5/tenders/{id}. Тому довантажуємо його по одному для кожного тендера.

Запуск:
  python add_winners.py
"""

import requests
import time
from neo4j import GraphDatabase

# ─── НАЛАШТУВАННЯ ────────────────────────────────────────────────────────────

NEO4J_URI      = "bolt://localhost:7687"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "12password"

API_BASE = "https://public-api.prozorro.gov.ua/api/2.5"

# Скільки секунд чекати між запитами, щоб не перевантажувати API
REQUEST_DELAY = 0.3

# Скільки тендерів обробити за цей запуск (None — без обмеження, всі одразу).
# Для першого тестового прогону краще лишити невелике число (50-100),
# щоб одразу побачити, чи все працює коректно, перш ніж запускати на всіх 1481.
LIMIT = 50

# ─── CYPHER ───────────────────────────────────────────────────────────────────

# Беремо ID всіх тендерів, які вже є в базі і ще не мають переможця.
# У цій базі тендери записані без лейбла Tender — замість нього
# вузол одразу отримав лейбл рівня ризику (LowRisk / MediumRisk / HighRisk).
GET_TENDERS_WITHOUT_WINNER = """
MATCH (t)
WHERE (t:LowRisk OR t:MediumRisk OR t:HighRisk)
  AND NOT (t)-[:WINNER_IS]->(:Company)
RETURN t.tender_id AS tender_id
"""

SAVE_WINNER_QUERY = """
MATCH (t)
WHERE (t:LowRisk OR t:MediumRisk OR t:HighRisk) AND t.tender_id = $tender_id
MATCH (buyer:Organization)-[:ANNOUNCED]->(t)
MERGE (c:Company {edrpou: $company_edrpou})
  SET c.name = $company_name
MERGE (t)-[:WINNER_IS]->(c)
MERGE (buyer)-[:PAID_TO]->(c)
WITH c
WHERE $address IS NOT NULL AND $address <> ''
MERGE (a:Address {full_address: $address})
MERGE (c)-[:HAS_HQ_AT]->(a)
"""

# ─── ФУНКЦІЇ ──────────────────────────────────────────────────────────────────

def connect_neo4j():
    print("[0] Підключення до Neo4j...")
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
        print("    ✓ Підключено\n")
        return driver
    except Exception as e:
        print(f"    ✗ Помилка: {e}")
        return None


def fetch_tender_detail(tender_id: str, retries: int = 3) -> dict | None:
    """
    Робить запит до офіційного API за конкретним тендером і повертає його дані.
    При тимчасових мережевих помилках (таймаут, 429, 5xx) повторює спробу
    до `retries` разів з невеликою паузою — на вибірці 1481 тендера
    окремі поодинокі збої мережі є нормою, а не системною помилкою.
    """
    url = f"{API_BASE}/tenders/{tender_id}"
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, timeout=20)
            if r.status_code == 200:
                return r.json().get("data", {})
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(1.5 * attempt)
                continue
            return None
        except requests.exceptions.RequestException:
            if attempt < retries:
                time.sleep(1.5 * attempt)
                continue
            return None
    return None


def extract_winner(tender_data: dict) -> dict | None:
    """
    Шукає в тендері активне award (рішення про переможця) і витягує
    дані компанії-переможця: ЄДРПОУ, назву, адресу.
    """
    awards = tender_data.get("awards", [])
    if not awards:
        return None

    # Беремо award зі статусом active (затверджене рішення),
    # якщо такого немає — беремо останній за списком
    active_awards = [a for a in awards if a.get("status") == "active"]
    award = active_awards[-1] if active_awards else awards[-1]

    suppliers = award.get("suppliers", [])
    if not suppliers:
        return None

    supplier = suppliers[0]
    identifier = supplier.get("identifier", {}) or {}
    edrpou = str(identifier.get("id", "")).strip()
    if not edrpou:
        return None

    name = supplier.get("name", "")

    address_obj = supplier.get("address", {}) or {}
    street = address_obj.get("streetAddress", "")
    locality = address_obj.get("locality", "") or address_obj.get("region", "")
    full_address = ", ".join(filter(None, [locality, street])).strip()

    return {
        "company_edrpou": edrpou,
        "company_name": name,
        "address": full_address,
    }


def save_winner(session, tender_id: str, winner: dict):
    session.run(
        SAVE_WINNER_QUERY,
        tender_id=tender_id,
        company_edrpou=winner["company_edrpou"],
        company_name=winner["company_name"],
        address=winner["address"],
    )


# ─── ГОЛОВНА ФУНКЦІЯ ──────────────────────────────────────────────────────────

def main():
    print("╔══════════════════════════════════════════════════════╗")
    print("║   add_winners  —  Довантаження переможців тендерів  ║")
    print("╚══════════════════════════════════════════════════════╝\n")

    driver = connect_neo4j()
    if not driver:
        return

    with driver.session() as session:
        tender_ids = [r["tender_id"] for r in session.run(GET_TENDERS_WITHOUT_WINNER).data()]

    if LIMIT is not None:
        tender_ids = tender_ids[:LIMIT]

    print(f"[1] Тендерів без переможця у базі: {len(tender_ids)}"
          f"{f' (обмежено LIMIT={LIMIT})' if LIMIT is not None else ''}\n")
    if not tender_ids:
        print("    Усі тендери вже мають переможця, або база порожня.")
        driver.close()
        return

    found = 0
    no_award = 0
    errors = 0

    print(f"  {'№':6} {'Tender ID':30} {'Результат'}")
    print("  " + "─" * 60)

    with driver.session() as session:
        for i, tender_id in enumerate(tender_ids, 1):
            data = fetch_tender_detail(tender_id)

            if data is None:
                errors += 1
                print(f"  {i:6}   {tender_id[:28]:30} ✗ помилка запиту")
                time.sleep(REQUEST_DELAY)
                continue

            winner = extract_winner(data)

            if winner is None:
                no_award += 1
                print(f"  {i:6}   {tender_id[:28]:30} — без переможця (award відсутній)")
            else:
                save_winner(session, tender_id, winner)
                found += 1
                addr_note = winner["address"] or "адреса невідома"
                print(f"  {i:6}   {tender_id[:28]:30} ✓ {winner['company_name'][:30]} | {addr_note[:30]}")

            if i % 100 == 0:
                print(f"\n  ── Прогрес: {i}/{len(tender_ids)} "
                      f"(знайдено {found}, без переможця {no_award}, помилок {errors}) ──\n")

            time.sleep(REQUEST_DELAY)

    print("\n" + "═" * 60)
    print(f"  Знайдено переможців      : {found}")
    print(f"  Без рішення про переможця: {no_award}")
    print(f"  Помилок запиту           : {errors}")
    print("═" * 60)

    if found > 0:
        print(f"""
  ✓ Готово! Перевірка у Neo4j Browser:

  // Переможці тендерів
  MATCH (t:Tender)-[:WINNER_IS]->(c:Company)
  RETURN t.tender_id, t.title, c.name, c.edrpou
  LIMIT 50

  // Компанії з відомою адресою
  MATCH (c:Company)-[:HAS_HQ_AT]->(a:Address)
  RETURN c.name, a.full_address
  LIMIT 50
""")

    driver.close()


if __name__ == "__main__":
    main()
