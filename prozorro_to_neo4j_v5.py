"""
prozorro_to_neo4j_v5.py  —  Завантаження тендерів Prozorro у Neo4j
══════════════════════════════════════════════════════════════════════
ЗМІНА v5: використовує пошуковий API Prozorro з фільтром по ЄДРПОУ.
Замість сліпого перебору мільйонів тендерів — цільовий запит по
конкретному замовнику (buyer.identifier.id == TARGET_EDRPOU).

Стратегія:
  1. Спробувати пошуковий endpoint /api/2.5/tenders з параметром edrpou
  2. Якщо не спрацює — fallback через dateModified (від найновіших)
  3. Зберегти тільки тендери з потрібним ЄДРПОУ у Neo4j

Запуск:
  python prozorro_to_neo4j_v5.py
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

# Правильний публічний API Prozorro
API_BASE       = "https://public-api.prozorro.gov.ua/api/2.5"

PAGE_SIZE      = 100
MAX_PAGES      = 500    # збільшено: переглядаємо до 50 000 тендерів

# Пошук від найсвіжіших — тендери ОМС зазвичай свіжі
# Якщо потрібно шукати старіші — зменш дату
DATE_FROM      = "2019-01-01T00:00:00+02:00"

# ─── Cypher-запити ───────────────────────────────────────────────────────────

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

# ─── ПІДКЛЮЧЕННЯ ─────────────────────────────────────────────────────────────

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

# ─── ЗАПИТ ДО API ────────────────────────────────────────────────────────────

def fetch_page(offset, use_edrpou_filter=True) -> tuple[list[dict], str | None]:
    """
    Повертає (список тендерів, наступний offset або None).
    use_edrpou_filter=True — спробувати фільтр по ЄДРПОУ (не всі версії API підтримують).
    """
    url = f"{API_BASE}/tenders"
    params = {
        "limit":  PAGE_SIZE,
        "opt_fields": "tenderID,title,value,status,procurementMethodType,procuringEntity",
    }

    if use_edrpou_filter:
        # Деякі дзеркала API підтримують цей параметр
        params["edrpou"] = TARGET_EDRPOU
    
    if offset:
        params["offset"] = offset
    else:
        # Починаємо з найновіших через dateModified
        params["dateModified[gte]"] = DATE_FROM

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        tenders = data.get("data", [])
        # next_page містить наступний offset
        next_page = data.get("next_page", {})
        next_offset = next_page.get("offset") if next_page else None
        return tenders, next_offset
    except requests.RequestException as e:
        print(f"    ✗ Помилка API: {e}")
        return [], None

# ─── ОБРОБКА ТЕНДЕРА ─────────────────────────────────────────────────────────

def extract_fields(tender: dict) -> dict | None:
    buyer  = tender.get("procuringEntity", {})
    ident  = buyer.get("identifier", {})
    edrpou = str(ident.get("id", "")).strip()

    if edrpou != TARGET_EDRPOU:
        return None

    value  = tender.get("value") or {}
    budget = value.get("amount", 0.0)

    return {
        "tender_id":    tender.get("tenderID", ""),
        "title":        tender.get("title", "без назви"),
        "budget":       float(budget) if budget else 0.0,
        "status":       tender.get("status", ""),
        "procedure":    tender.get("procurementMethodType", ""),
        "buyer_edrpou": edrpou,
        "buyer_name":   buyer.get("name", TARGET_NAME),
    }

def save_to_neo4j(session, fields: dict):
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
    print("║   prozorro_to_neo4j_v5  —  Завантаження тендерів   ║")
    print("╚══════════════════════════════════════════════════════╝\n")
    print(f"  Фільтр ЄДРПОУ : {TARGET_EDRPOU}  ({TARGET_NAME})")
    print(f"  API            : {API_BASE}")
    print(f"  Пошук з дати  : {DATE_FROM}\n")

    driver = connect_neo4j()
    if not driver:
        return

    total_fetched = 0
    total_saved   = 0
    total_skipped = 0

    # Крок 1: перевірити, чи API підтримує фільтр по edrpou
    print("[1] Перевірка підтримки фільтра по ЄДРПОУ...")
    test_tenders, _ = fetch_page(None, use_edrpou_filter=True)
    
    # Якщо серед перших результатів є наш ЄДРПОУ — фільтр працює
    edrpou_filter_works = any(
        str(t.get("procuringEntity", {}).get("identifier", {}).get("id", "")).strip() == TARGET_EDRPOU
        for t in test_tenders
    )
    
    if edrpou_filter_works:
        print("    ✓ Фільтр по ЄДРПОУ працює — завантаження тільки потрібних тендерів\n")
    else:
        print("    ℹ Фільтр по ЄДРПОУ не підтримується API — сканування всіх тендерів")
        print(f"      (до {MAX_PAGES * PAGE_SIZE} тендерів починаючи з {DATE_FROM})\n")

    print("[2] Завантаження тендерів...\n")
    print(f"  {'Стор.':6} {'Отримано':>9} {'Збережено':>10} {'Пропущено':>10}  {'Всього збережено':>16}")
    print("  " + "─" * 60)

    offset = None
    consecutive_empty = 0

    with driver.session() as session:
        for page in range(MAX_PAGES):
            tenders, next_offset = fetch_page(offset, use_edrpou_filter=edrpou_filter_works)

            if not tenders:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    print(f"\n  Завершення: {consecutive_empty} порожні відповіді підряд.")
                    break
                time.sleep(1)
                continue
            
            consecutive_empty = 0
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

            marker = " ←" if page_saved > 0 else ""
            print(f"  {page+1:6}   {len(tenders):>8}   {page_saved:>9}   {page_skipped:>9}  {total_saved:>16}{marker}")

            # Якщо немає наступної сторінки — все зібрано
            if not next_offset:
                print(f"\n  Досягнуто кінця даних (offset відсутній).")
                break

            offset = next_offset

            if len(tenders) < PAGE_SIZE:
                print(f"\n  Остання сторінка (отримано {len(tenders)} < {PAGE_SIZE}).")
                break

            time.sleep(0.3)

    # ─── ПІДСУМОК ────────────────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("  ПІДСУМОК")
    print("═" * 60)
    print(f"  Всього отримано з API   : {total_fetched}")
    print(f"  Збережено у Neo4j       : {total_saved}  ← тільки {TARGET_EDRPOU}")
    print(f"  Відфільтровано (інші)   : {total_skipped}")
    print("═" * 60)

    if total_saved == 0:
        print("""
  ⚠  Жодного тендера не збережено.
  
  Можливі причини:
  1. Тендери Кам'янської ради старіші за DATE_FROM — зміни в скрипті:
       DATE_FROM = "2015-01-01T00:00:00+02:00"
  
  2. Перевір ЄДРПОУ вручну у браузері:
       https://prozorro.gov.ua/uk/search/tender?buyer=24604168
  
  3. Перевір через API (відкрий у браузері):
       https://public-api.prozorro.gov.ua/api/2.5/tenders?limit=5&opt_fields=tenderID,procuringEntity
""")
    else:
        print(f"""
  ✓ Готово! Запусти risk_classifier.py для аналізу ризиків.

  Перевірка у Neo4j Browser:
  MATCH (org:Organization {{edrpou: '{TARGET_EDRPOU}'}})-[:ANNOUNCED]->(t:Tender)
  RETURN org.name AS Замовник,
         count(t) AS Кількість_тендерів,
         sum(t.budget) AS Загальний_бюджет
  ORDER BY Кількість_тендерів DESC
""")

    driver.close()


if __name__ == "__main__":
    main()