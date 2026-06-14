"""
prozorro_to_neo4j_v2.py  —  виправлена версія
═══════════════════════════════════════════════
Головні виправлення порівняно з v1:
  1. Шукаємо тендери зі статусом 'complete' або 'unsuccessful'
     (тільки в них є визначені переможці з awards.status='active')
  2. Додаємо перебір сторінок (offset) щоб не застрягти на перших 15
  3. Пошук без фільтра ДК-коду (він ламає пагінацію в деяких версіях API)
  4. Детальний лог кожного кроку
"""

import requests
import time
from neo4j import GraphDatabase

# ─── НАЛАШТУВАННЯ ──────────────────────────────────────────────────────
NEO4J_URI      = "bolt://localhost:7687"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "12password"

BASE_URL   = "https://public-api.prozorro.gov.ua/api/2.5"
MAX_SAVED  = 15      # скільки тендерів З ПЕРЕМОЖЦЯМИ зберегти
PAGE_SIZE  = 50      # скільки брати за один запит до API

# ─── CYPHER-ЗАПИТИ ─────────────────────────────────────────────────────
WRITE_TENDER = """
MERGE (buyer:Organization {edrpou: $buyer_edrpou})
SET buyer.name = $buyer_name

MERGE (t:Tender {tender_id: $tender_id})
SET t.title    = $title,
    t.budget   = $budget,
    t.status   = $status,
    t.procedure = $procedure

MERGE (buyer)-[:ANNOUNCED]->(t)
"""

WRITE_WINNER = """
MATCH (t:Tender {tender_id: $tender_id})
MERGE (c:Company {edrpou: $edrpou})
ON CREATE SET c.name    = $name,
              c.city    = $city,
              c.address = $address
ON MATCH  SET c.name    = $name
MERGE (t)-[:WINNER_IS]->(c)
MERGE (buyer)-[:PAID_TO]->(c)
"""

# ─── PROZORRO API ──────────────────────────────────────────────────────

def fetch_tender_ids(page_size: int, offset: str | None) -> tuple[list, str | None]:
    """Одна сторінка списку тендерів. Повертає (список id, наступний offset)."""
    params = {"limit": page_size}
    if offset:
        params["offset"] = offset

    try:
        r = requests.get(f"{BASE_URL}/tenders", params=params, timeout=20)
        r.raise_for_status()
        body = r.json()
        ids        = [item["id"] for item in body.get("data", [])]
        next_off   = body.get("next_page", {}).get("offset")
        return ids, next_off
    except Exception as e:
        print(f"  ⚠ Помилка отримання списку: {e}")
        return [], None


def fetch_details(tender_id: str) -> dict | None:
    """Повні дані одного тендера."""
    try:
        r = requests.get(f"{BASE_URL}/tenders/{tender_id}", timeout=20)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json().get("data")
    except Exception as e:
        print(f"  ⚠ Помилка деталей {tender_id}: {e}")
        return None


def extract(details: dict) -> dict | None:
    """
    Витягує потрібні поля.
    Повертає None якщо тендер без активних переможців.
    """
    awards = details.get("awards", [])
    active = [a for a in awards if a.get("status") == "active"]
    if not active:
        return None                                    # ← ключова перевірка

    procuring = details.get("procuringEntity", {})
    return {
        "tender_id": details.get("tenderID") or details.get("id"),
        "title":     (details.get("title") or "без назви")[:120],
        "status":    details.get("status", ""),
        "procedure": details.get("procurementMethodType", ""),
        "budget":    details.get("value", {}).get("amount", 0),
        "buyer_name":   procuring.get("name", "невідомо"),
        "buyer_edrpou": procuring.get("identifier", {}).get("id", "00000000"),
        "winners": [
            {
                "edrpou":   sup.get("identifier", {}).get("id", "00000000"),
                "name":     sup.get("name", "невідомо"),
                "address":  sup.get("address", {}).get("streetAddress", ""),
                "city":     sup.get("address", {}).get("locality", ""),
                "amount":   award.get("value", {}).get("amount", 0),
            }
            for award in active
            for sup in award.get("suppliers", [])
        ],
    }


# ─── NEO4J ─────────────────────────────────────────────────────────────

def save(session, rec: dict):
    session.run(
        WRITE_TENDER,
        buyer_edrpou = rec["buyer_edrpou"],
        buyer_name   = rec["buyer_name"],
        tender_id    = rec["tender_id"],
        title        = rec["title"],
        budget       = rec["budget"],
        status       = rec["status"],
        procedure    = rec["procedure"],
    )
    for w in rec["winners"]:
        session.run(
            WRITE_WINNER,
            tender_id = rec["tender_id"],
            buyer     = rec["buyer_edrpou"],   # для зв'язку PAID_TO
            edrpou    = w["edrpou"],
            name      = w["name"],
            address   = w["address"],
            city      = w["city"],
        )


# ─── АНАЛІТИКА ─────────────────────────────────────────────────────────

ANALYTICS = [
    ("Топ компаній за сумою тендерів", """
        MATCH (t:Tender)-[:WINNER_IS]->(c:Company)
        RETURN c.name AS Компанія, c.edrpou AS ЄДРПОУ,
               COUNT(t) AS Тендерів, SUM(t.budget) AS Сума
        ORDER BY Сума DESC LIMIT 10
    """),
    ("Тендери без конкуренції (1 переможець, бюджет > 0)", """
        MATCH (t:Tender)-[:WINNER_IS]->(c:Company)
        WITH t, COUNT(c) AS winners
        WHERE winners = 1 AND t.budget > 0
        MATCH (t)-[:WINNER_IS]->(c:Company)
        RETURN t.tender_id AS ID, t.title AS Назва,
               t.budget AS Бюджет, c.name AS Переможець
        ORDER BY t.budget DESC LIMIT 10
    """),
]

def analytics(driver):
    print("\n" + "═"*60)
    print("  АНАЛІЗ РИЗИКІВ")
    print("═"*60)
    with driver.session() as s:
        for title, q in ANALYTICS:
            print(f"\n▶ {title}:")
            rows = s.run(q).data()
            if not rows:
                print("  (немає даних)")
                continue
            keys = list(rows[0].keys())
            for row in rows:
                line = "  " + " | ".join(
                    f"{str(row.get(k,''))[:35]:35}" for k in keys
                )
                print(line)


# ─── ГОЛОВНА ФУНКЦІЯ ───────────────────────────────────────────────────

def main():
    print("╔══════════════════════════════════════════════════════╗")
    print("║   PROZORRO → NEO4J  v2  (виправлена версія)         ║")
    print("╚══════════════════════════════════════════════════════╝")

    # Підключення до Neo4j
    print("\n[0] Підключення до Neo4j...")
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
        print("    ✓ Підключено")
    except Exception as e:
        print(f"    ✗ Помилка: {e}")
        print("    Перевір: Neo4j Desktop запущений? Пароль вірний?")
        return

    saved   = 0
    checked = 0
    offset  = None

    print(f"\n[1] Пошук тендерів з активними переможцями...")
    print(f"    Ціль: {MAX_SAVED} тендерів\n")

    with driver.session() as session:
        while saved < MAX_SAVED:
            ids, offset = fetch_tender_ids(PAGE_SIZE, offset)

            if not ids:
                print("  Більше тендерів немає (кінець списку API)")
                break

            for tid in ids:
                if saved >= MAX_SAVED:
                    break

                details = fetch_details(tid)
                checked += 1

                if details is None:
                    continue

                rec = extract(details)
                status = details.get("status", "?")

                if rec is None:
                    # Показуємо тільки якщо є awards але всі не active
                    awards = details.get("awards", [])
                    statuses = [a.get("status") for a in awards]
                    print(f"  [{checked:4}] пропуск  {status:15} "
                          f"awards={statuses or 'порожньо':30} "
                          f"{details.get('tenderID','?')[:25]}")
                    time.sleep(0.15)
                    continue

                # Зберігаємо
                try:
                    save(session, rec)
                    saved += 1
                    winners_str = ", ".join(
                        w["name"][:30] for w in rec["winners"]
                    )
                    print(f"  [{checked:4}] ✓ ЗБЕРЕЖЕНО  "
                          f"{rec['tender_id'][:25]:25}  "
                          f"{rec['budget']:>12,.0f} грн  "
                          f"→ {winners_str}")
                except Exception as e:
                    print(f"  [{checked:4}] ✗ Помилка запису: {e}")

                time.sleep(0.15)

            if not offset:
                print("\n  Досягнуто кінця списку API")
                break

    print(f"\n{'═'*60}")
    print(f"  Перевірено: {checked} тендерів")
    print(f"  Збережено:  {saved} тендерів з переможцями")
    print(f"{'═'*60}")

    if saved > 0:
        analytics(driver)
        print("\n  Для візуалізації у Neo4j Browser:")
        print("  MATCH (n)-[r]->(m) RETURN n, r, m LIMIT 200")
    else:
        print("\n  ⚠ Нічого не збережено.")
        print("  Спочатку запусти diagnose_prozorro.py щоб побачити")
        print("  реальну структуру відповіді API.")

    driver.close()


if __name__ == "__main__":
    main()