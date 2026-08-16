"""
prozorro_to_neo4j.py — Модуль Б: завантаження тендерів Prozorro у Neo4j
══════════════════════════════════════════════════════════════════════
Фінальна (консолідована) версія програмного модуля.

Завантажує тендери конкретного органу місцевого самоврядування (ОМС)
через внутрішній пошуковий endpoint сайту Prozorro та записує їх у
графову базу даних Neo4j.

Примітка щодо API:
  Публічний API Prozorro (public-api.prozorro.gov.ua) не підтримує
  серверну фільтрацію тендерів за ЄДРПОУ замовника. Робочим рішенням
  є внутрішній пошуковий endpoint фронтенду сайту (prozorro.gov.ua/api/
  search/tenders), який приймає POST-запит з фільтром buyer[0]=<ЄДРПОУ>.
  Цей endpoint не документований офіційно та не повертає поле
  procurementMethodType — обмеження, зафіксоване й розглянуте
  в підрозділі 2.2.

Запуск:
  python prozorro_to_neo4j.py
"""

import requests
import json
import time
from neo4j import GraphDatabase

# ─── НАЛАШТУВАННЯ ────────────────────────────────────────────────────────────

NEO4J_URI      = "bolt://localhost:7687"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "12password"

TARGET_EDRPOU  = "24604168"
TARGET_NAME    = "Кам'янська міська рада"

SEARCH_URL     = "https://prozorro.gov.ua/api/search/tenders"
PAGE_SIZE      = 10
MAX_PAGES      = 200

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "uk-UA,uk;q=0.9",
    "Content-Type":    "application/json",
    "Referer":         "https://prozorro.gov.ua/",
}

# ─── Cypher ──────────────────────────────────────────────────────────────────

MERGE_QUERY = """
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

# ─── Neo4j ───────────────────────────────────────────────────────────────────

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

# ─── ЗАПИТ ДО API (POST) ─────────────────────────────────────────────────────

def build_body(page: int) -> dict:
    """Формує тіло POST-запиту з фільтром за ЄДРПОУ замовника."""
    return {
        "buyer":  [TARGET_EDRPOU],
        "page":   page,
        "limit":  PAGE_SIZE,
    }

def fetch_page(page: int) -> tuple[list, int, dict]:
    """Повертає (тендери, загальна_кількість, сирий_json)."""
    body = build_body(page)
    try:
        r = requests.post(SEARCH_URL, json=body, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()

        tenders = []
        total   = 0

        if isinstance(data, list):
            tenders = data
        elif isinstance(data, dict):
            for key in ("data", "tenders", "results", "items", "list"):
                if key in data and isinstance(data[key], list):
                    tenders = data[key]
                    break
            for key in ("total", "count", "total_count", "totalCount"):
                if key in data:
                    total = int(data[key])
                    break

        return tenders, total, data

    except requests.HTTPError as e:
        print(f"    ✗ HTTP {e.response.status_code}: {e.response.text[:300]}")
        return [], 0, {}
    except Exception as e:
        print(f"    ✗ Помилка: {e}")
        return [], 0, {}

# ─── ОБРОБКА ТЕНДЕРА ─────────────────────────────────────────────────────────

def extract_fields(tender: dict) -> dict | None:
    buyer = (
        tender.get("procuringEntity") or
        tender.get("buyer") or
        tender.get("procuring_entity") or {}
    )

    if isinstance(buyer, dict):
        ident  = buyer.get("identifier") or {}
        edrpou = str(ident.get("id", buyer.get("edrpou", ""))).strip()
        bname  = buyer.get("name", TARGET_NAME)
    else:
        edrpou = str(tender.get("buyerEdrpou", tender.get("buyer_edrpou", ""))).strip()
        bname  = TARGET_NAME

    if not edrpou:
        edrpou = TARGET_EDRPOU

    value = tender.get("value") or tender.get("amount") or {}
    if isinstance(value, (int, float)):
        budget = float(value)
    elif isinstance(value, dict):
        budget = float(value.get("amount", 0) or 0)
    else:
        budget = 0.0

    tender_id = (
        tender.get("tenderID") or
        tender.get("tender_id") or
        tender.get("id") or ""
    )
    if not tender_id:
        return None

    return {
        "tender_id":    tender_id,
        "title":        tender.get("title") or tender.get("name", "без назви"),
        "budget":       budget,
        "status":       tender.get("status", ""),
        # Примітка: це поле стабільно порожнє для даного endpoint (див. підрозділ 2.2)
        "procedure":    tender.get("procurementMethodType") or tender.get("procedure", ""),
        "buyer_edrpou": edrpou,
        "buyer_name":   bname,
    }

def save_to_neo4j(session, fields: dict):
    session.run(MERGE_QUERY, **fields)

# ─── ГОЛОВНА ФУНКЦІЯ ─────────────────────────────────────────────────────────

def main():
    print("╔══════════════════════════════════════════════════════╗")
    print("║   prozorro_to_neo4j — Завантаження тендерів ОМС     ║")
    print("╚══════════════════════════════════════════════════════╝\n")
    print(f"  ЄДРПОУ  : {TARGET_EDRPOU}  ({TARGET_NAME})")
    print(f"  Endpoint: POST {SEARCH_URL}\n")

    print("[1] Перевірка endpoint...")
    body = build_body(1)
    try:
        r = requests.post(SEARCH_URL, json=body, headers=HEADERS, timeout=20)
        print(f"    HTTP статус: {r.status_code}")
        if r.status_code != 200:
            print("    ✗ Помилка. Перевір доступність endpoint.")
            return
    except Exception as e:
        print(f"    ✗ {e}")
        return

    driver = connect_neo4j()
    if not driver:
        return

    total_saved   = 0
    total_fetched = 0

    print("[2] Завантаження тендерів...\n")
    print(f"  {'Стор.':6} {'Отримано':>9} {'Збережено':>10}  {'Всього':>8}")
    print("  " + "─" * 42)

    with driver.session() as session:
        for page in range(1, MAX_PAGES + 1):
            tenders, total, raw = fetch_page(page)

            if page == 1 and total:
                print(f"  Всього на сервері: {total} тендерів\n")

            if not tenders:
                if page == 1:
                    print("  ⚠ Перша сторінка порожня. Перевір ЄДРПОУ та доступність API.")
                else:
                    print(f"  Сторінка {page}: порожня — завершення.")
                break

            page_saved = 0
            for t in tenders:
                fields = extract_fields(t)
                if fields:
                    save_to_neo4j(session, fields)
                    page_saved += 1

            total_fetched += len(tenders)
            total_saved   += page_saved

            print(f"  {page:6}   {len(tenders):>8}   {page_saved:>9}  {total_saved:>8}")

            if len(tenders) < PAGE_SIZE:
                print(f"\n  Остання сторінка.")
                break

            time.sleep(0.25)

    print("\n" + "═" * 55)
    print(f"  Отримано : {total_fetched}")
    print(f"  Збережено: {total_saved}")
    print("═" * 55)

    if total_saved > 0:
        print(f"""
  ✓ Готово! Перевірка у Neo4j:
  MATCH (o:Organization {{edrpou:'{TARGET_EDRPOU}'}})-[:ANNOUNCED]->(t)
  RETURN o.name, count(t) AS тендери, sum(t.budget) AS бюджет
""")
    else:
        print("\n  ⚠ Нуль тендерів збережено. Перевір параметри запиту.\n")

    driver.close()


if __name__ == "__main__":
    main()
