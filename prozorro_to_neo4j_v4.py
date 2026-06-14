"""
prozorro_to_neo4j_v4.py  —  Завантаження тендерів Prozorro у Neo4j
══════════════════════════════════════════════════════════════════════
Завантажує тендери конкретного ОМС з Prozorro API і записує у Neo4j.

ЗМІНА v3: доданий фільтр TARGET_EDRPOU — зберігаються тільки тендери,
де buyer.identifier.id == TARGET_EDRPOU (Кам'янська міська рада).

Запуск:
  python prozorro_to_neo4j_v4.py
"""

import requests
import time
from neo4j import GraphDatabase

# ─── НАЛАШТУВАННЯ ────────────────────────────────────────────────────────────

NEO4J_URI      = "bolt://localhost:7687"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "12password"

# ▶ ФІЛЬТР: зберігати тільки тендери цього ОМС
TARGET_EDRPOU  = "24604168"          # Кам'янська міська рада
TARGET_NAME    = "Кам'янська міська рада"

# Prozorro API
API_BASE       = "https://public-api.prozorro.gov.ua/api/2.5"
PAGE_SIZE      = 100                 # тендерів на сторінку (максимум API)
MAX_PAGES      = 20                  # ліміт сторінок (20×100 = 2000 тендерів)

# ─── ЗАПИТИ ДО Neo4j ─────────────────────────────────────────────────────────

MERGE_TENDER_QUERY = """
MERGE (org:Organization {edrpou: $buyer_edrpou})
  SET org.name = $buyer_name

MERGE (t:Tender {tender_id: $tender_id})
  SET t.title        = $title,
      t.budget       = $budget,
      t.status       = $status,
      t.procedure    = $procedure,
      t.buyer_edrpou = $buyer_edrpou,
      t.buyer_name   = $buyer_name

MERGE (org)-[:ANNOUNCED]->(t)
"""

# ─── ФУНКЦІЇ ─────────────────────────────────────────────────────────────────

def connect_neo4j():
    print("[0] Підключення до Neo4j...")
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
        print("    ✓ Підключено\n")
        return driver
    except Exception as e:
        print(f"    ✗ Помилка підключення: {e}")
        return None


def fetch_tenders_page(offset: int) -> list[dict]:
    """Завантажує одну сторінку тендерів з Prozorro API."""
    url = f"{API_BASE}/tenders"
    params = {
        "limit":  PAGE_SIZE,
        "offset": offset,
        "opt_fields": "tenderID,title,value,status,procurementMethodType,procuringEntity",
    }
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", [])
    except requests.RequestException as e:
        print(f"    ✗ Помилка API (offset={offset}): {e}")
        return []


def extract_fields(tender: dict) -> dict | None:
    """
    Витягує потрібні поля з сирого об'єкта тендера.
    Повертає None, якщо buyer_edrpou не відповідає TARGET_EDRPOU.
    """
    buyer   = tender.get("procuringEntity", {})
    ident   = buyer.get("identifier", {})
    edrpou  = str(ident.get("id", "")).strip()

    # ▶ ФІЛЬТР ПО ЄДРПОУ — ключова зміна v3
    if edrpou != TARGET_EDRPOU:
        return None

    value  = tender.get("value") or {}
    budget = value.get("amount", 0.0)

    return {
        "tender_id":   tender.get("tenderID", ""),
        "title":       tender.get("title", "без назви"),
        "budget":      float(budget) if budget else 0.0,
        "status":      tender.get("status", ""),
        "procedure":   tender.get("procurementMethodType", ""),
        "buyer_edrpou": edrpou,
        "buyer_name":   buyer.get("name", TARGET_NAME),
    }


def save_to_neo4j(session, fields: dict):
    """Зберігає один тендер у Neo4j."""
    session.run(
        MERGE_TENDER_QUERY,
        buyer_edrpou = fields["buyer_edrpou"],
        buyer_name   = fields["buyer_name"],
        tender_id    = fields["tender_id"],
        title        = fields["title"],
        budget       = fields["budget"],
        status       = fields["status"],
        procedure    = fields["procedure"],
    )


# ─── ГОЛОВНА ФУНКЦІЯ ─────────────────────────────────────────────────────────

def main():
    print("╔══════════════════════════════════════════════════════╗")
    print("║   prozorro_to_neo4j_v4  —  Завантаження тендерів   ║")
    print("╚══════════════════════════════════════════════════════╝\n")
    print(f"  Фільтр ЄДРПОУ : {TARGET_EDRPOU}  ({TARGET_NAME})\n")

    driver = connect_neo4j()
    if not driver:
        return

    total_fetched = 0
    total_saved   = 0
    total_skipped = 0

    print("[1] Завантаження тендерів з Prozorro API...\n")
    print(f"  {'Сторінка':8} {'Отримано':>9} {'Збережено':>10} {'Пропущено':>10}")
    print("  " + "─" * 45)

    with driver.session() as session:
        for page in range(MAX_PAGES):
            offset  = page * PAGE_SIZE
            tenders = fetch_tenders_page(offset)

            if not tenders:
                print(f"\n  Сторінка {page+1}: порожня — завершення завантаження.")
                break

            page_saved   = 0
            page_skipped = 0

            for t in tenders:
                fields = extract_fields(t)
                if fields is None:
                    page_skipped += 1
                    continue
                save_to_neo4j(session, fields)
                page_saved += 1

            total_fetched += len(tenders)
            total_saved   += page_saved
            total_skipped += page_skipped

            print(f"  {page+1:8}   {len(tenders):>8}   {page_saved:>9}   {page_skipped:>9}")

            # API не повернув повну сторінку — більше даних немає
            if len(tenders) < PAGE_SIZE:
                print(f"\n  Остання сторінка (отримано {len(tenders)} < {PAGE_SIZE}).")
                break

            time.sleep(0.3)   # щоб не перевантажувати API

    # Підсумок
    print("\n" + "═" * 55)
    print(f"  ПІДСУМОК")
    print("═" * 55)
    print(f"  Всього отримано з API   : {total_fetched}")
    print(f"  Збережено у Neo4j       : {total_saved}  ← тільки {TARGET_EDRPOU}")
    print(f"  Відфільтровано (інші)   : {total_skipped}")
    print("═" * 55)

    if total_saved == 0:
        print("\n  ⚠  Жодного тендера не збережено.")
        print(f"     Перевір: чи є тендери з buyer.identifier.id == '{TARGET_EDRPOU}'")
        print(f"     на сторінці: https://prozorro.gov.ua/api/2.5/tenders?edrpou={TARGET_EDRPOU}")
    else:
        print(f"\n  ✓ Готово! Запусти risk_classifier.py для аналізу ризиків.")
        print("""
  Перевірка у Neo4j Browser:
  MATCH (org:Organization {edrpou: '24604168'})-[:ANNOUNCED]->(t:Tender)
  RETURN org.name AS Замовник, count(t) AS Кількість_тендерів
        """)

    driver.close()


if __name__ == "__main__":
    main()