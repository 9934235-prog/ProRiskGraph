"""
prozorro_to_neo4j_v7.py  —  Завантаження тендерів Prozorro у Neo4j
══════════════════════════════════════════════════════════════════════
ЗМІНА v7: використовує реальний пошуковий endpoint сайту Prozorro
  https://prozorro.gov.ua/api/search/tenders?buyer[0]=24604168
(знайдений через DevTools браузера)

Запуск:
  python prozorro_to_neo4j_v7.py
"""

import requests
import time
from neo4j import GraphDatabase

# ─── НАЛАШТУВАННЯ ────────────────────────────────────────────────────────────

NEO4J_URI      = "bolt://localhost:7687"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "12password"

TARGET_EDRPOU  = "24604168"
TARGET_NAME    = "Кам'янська міська рада"

SEARCH_URL     = "https://prozorro.gov.ua/api/search/tenders"
PAGE_SIZE      = 10   # стандарт для цього endpoint
MAX_PAGES      = 200  # до 2000 тендерів

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "uk-UA,uk;q=0.9",
    "Referer": "https://prozorro.gov.ua/",
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

# ─── ЗАПИТ ДО API ────────────────────────────────────────────────────────────

def fetch_page(page: int) -> tuple[list, int]:
    """
    Повертає (список тендерів, загальна кількість).
    Сторінки нумеруються з 1.
    """
    params = {
        "buyer[0]": TARGET_EDRPOU,
        "page":     page,
        "limit":    PAGE_SIZE,
    }
    try:
        r = requests.get(SEARCH_URL, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()

        # Розбираємо різні можливі структури відповіді
        tenders = []
        total   = 0

        if isinstance(data, list):
            tenders = data
        elif isinstance(data, dict):
            # Шукаємо список тендерів у відомих ключах
            for key in ("data", "tenders", "results", "items", "list"):
                if key in data and isinstance(data[key], list):
                    tenders = data[key]
                    break

            # Загальна кількість
            for key in ("total", "count", "total_count", "totalCount"):
                if key in data:
                    total = int(data[key])
                    break

        return tenders, total

    except requests.HTTPError as e:
        print(f"    ✗ HTTP помилка (сторінка {page}): {e}")
        return [], 0
    except Exception as e:
        print(f"    ✗ Помилка (сторінка {page}): {e}")
        return [], 0

# ─── ОБРОБКА ТЕНДЕРА ─────────────────────────────────────────────────────────

def extract_fields(tender: dict) -> dict | None:
    """Витягує поля з тендера. Структура може відрізнятися від public-api."""

    # Замовник
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

    # Деякі search API не повертають ЄДРПОУ у тілі (вже відфільтровано запитом)
    # тому якщо поле порожнє — довіряємо фільтру і використовуємо TARGET_EDRPOU
    if not edrpou:
        edrpou = TARGET_EDRPOU

    # Бюджет
    value  = tender.get("value") or tender.get("amount") or {}
    if isinstance(value, (int, float)):
        budget = float(value)
    elif isinstance(value, dict):
        budget = float(value.get("amount", 0) or 0)
    else:
        budget = 0.0

    # ID тендера
    tender_id = (
        tender.get("tenderID") or
        tender.get("tender_id") or
        tender.get("id") or
        ""
    )

    if not tender_id:
        return None   # без ID не можна зберегти

    return {
        "tender_id":    tender_id,
        "title":        tender.get("title") or tender.get("name", "без назви"),
        "budget":       budget,
        "status":       tender.get("status", ""),
        "procedure":    tender.get("procurementMethodType") or tender.get("procedure", ""),
        "buyer_edrpou": edrpou,
        "buyer_name":   bname,
    }

def save_to_neo4j(session, fields: dict):
    session.run(MERGE_QUERY, **fields)

# ─── ДІАГНОСТИКА: що взагалі повертає API ────────────────────────────────────

def print_raw_sample(data):
    """Виводить структуру першого тендера для діагностики."""
    import json
    if isinstance(data, list) and data:
        sample = data[0]
    elif isinstance(data, dict):
        for key in ("data", "tenders", "results", "items"):
            if key in data and data[key]:
                sample = data[key][0]
                break
        else:
            sample = data
    else:
        return
    print("\n  [Структура першого тендера]")
    text = json.dumps(sample, ensure_ascii=False, indent=2)
    print("  " + "\n  ".join(text.split("\n")[:30]))
    print("  ...\n")

# ─── ГОЛОВНА ФУНКЦІЯ ─────────────────────────────────────────────────────────

def main():
    print("╔══════════════════════════════════════════════════════╗")
    print("║   prozorro_to_neo4j_v7  —  Завантаження тендерів   ║")
    print("╚══════════════════════════════════════════════════════╝\n")
    print(f"  ЄДРПОУ  : {TARGET_EDRPOU}  ({TARGET_NAME})")
    print(f"  Endpoint: {SEARCH_URL}\n")

    # ── Перевірка API ────────────────────────────────────────────
    print("[1] Перевірка endpoint...")
    try:
        r = requests.get(
            SEARCH_URL,
            params={"buyer[0]": TARGET_EDRPOU, "page": 1, "limit": 3},
            headers=HEADERS,
            timeout=20
        )
        print(f"    HTTP статус : {r.status_code}")
        print(f"    Content-Type: {r.headers.get('Content-Type','?')}")

        if r.status_code != 200:
            print(f"    ✗ Сервер повернув помилку: {r.text[:300]}")
            return

        raw = r.json()
        print(f"    ✓ Отримано JSON, тип: {type(raw).__name__}")
        print_raw_sample(raw)

    except Exception as e:
        print(f"    ✗ Помилка підключення: {e}")
        return

    # ── Підключення Neo4j ────────────────────────────────────────
    driver = connect_neo4j()
    if not driver:
        return

    total_saved   = 0
    total_fetched = 0
    grand_total   = None

    print("[2] Завантаження тендерів...\n")
    print(f"  {'Стор.':6} {'Отримано':>9} {'Збережено':>10}  {'Всього':>8}")
    print("  " + "─" * 42)

    with driver.session() as session:
        for page in range(1, MAX_PAGES + 1):
            tenders, total = fetch_page(page)

            if grand_total is None and total:
                grand_total = total
                print(f"  Всього тендерів на сервері: {total}\n")

            if not tenders:
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

    # ── Підсумок ─────────────────────────────────────────────────
    print("\n" + "═" * 55)
    print("  ПІДСУМОК")
    print("═" * 55)
    print(f"  Отримано з API   : {total_fetched}")
    print(f"  Збережено Neo4j  : {total_saved}")
    print("═" * 55)

    if total_saved == 0:
        print("""
  ⚠  Нуль. Скопіюй і надішли [Структура першого тендера]
     вище — вона покаже як насправді виглядають дані.
""")
    else:
        print(f"""
  ✓ Готово!

  Перевірка у Neo4j Browser:
  MATCH (o:Organization {{edrpou:'{TARGET_EDRPOU}'}})-[:ANNOUNCED]->(t)
  RETURN o.name AS Замовник, count(t) AS Тендери, sum(t.budget) AS Бюджет
""")

    driver.close()


if __name__ == "__main__":
    main()
