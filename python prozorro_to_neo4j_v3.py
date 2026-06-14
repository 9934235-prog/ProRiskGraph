"""
prozorro_to_neo4j_v3.py
Ключове виправлення: сортування від НОВИХ до старих через offset від кінця.
API Prozorro не підтримує sort DESC напряму, тому беремо останню сторінку.
"""

import requests
import time
from neo4j import GraphDatabase

# ─── НАЛАШТУВАННЯ ──────────────────────────────────────────────────────
NEO4J_URI      = "bolt://localhost:7687"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "12password"
BASE_URL       = "https://public-api.prozorro.gov.ua/api/2.5"
MAX_SAVED      = 15

# ─── CYPHER ────────────────────────────────────────────────────────────
WRITE_TENDER = """
MERGE (buyer:Organization {edrpou: $buyer_edrpou})
SET buyer.name = $buyer_name
MERGE (t:Tender {tender_id: $tender_id})
SET t.title = $title, t.budget = $budget, t.status = $status
MERGE (buyer)-[:ANNOUNCED]->(t)
"""

WRITE_WINNER = """
MATCH (t:Tender {tender_id: $tender_id})
MERGE (c:Company {edrpou: $edrpou})
ON CREATE SET c.name = $name, c.city = $city
ON MATCH  SET c.name = $name
MERGE (t)-[:WINNER_IS]->(c)
"""

# ─── КРОК 1: знаходимо offset останньої сторінки ───────────────────────
def get_last_offset() -> str | None:
    """
    Prozorro API сортує від старих до нових.
    Щоб отримати НОВІ тендери — треба дістатись кінця списку.
    Робимо це через параметр 'descending=1' (підтримується з API 2.5).
    """
    print("[1] Пошук нових тендерів (descending=1)...")
    params = {"limit": 100, "descending": 1}
    try:
        r = requests.get(f"{BASE_URL}/tenders", params=params, timeout=20)
        r.raise_for_status()
        body = r.json()
        ids = [item["id"] for item in body.get("data", [])]
        print(f"    Отримано: {len(ids)} ID (найновіші)")
        return ids, body.get("next_page", {}).get("offset")
    except Exception as e:
        print(f"    ✗ Помилка: {e}")
        return [], None


def fetch_details(tid: str) -> dict | None:
    try:
        r = requests.get(f"{BASE_URL}/tenders/{tid}", timeout=20)
        return r.json().get("data") if r.status_code == 200 else None
    except:
        return None


def extract(details: dict) -> dict | None:
    awards = details.get("awards", [])
    active = [a for a in awards if a.get("status") == "active"]
    if not active:
        return None

    procuring = details.get("procuringEntity", {})
    winners = []
    for award in active:
        for sup in award.get("suppliers", []):
            winners.append({
                "edrpou": sup.get("identifier", {}).get("id", "00000000"),
                "name":   sup.get("name", "невідомо"),
                "city":   sup.get("address", {}).get("locality", ""),
            })

    return {
        "tender_id":    details.get("tenderID") or details.get("id"),
        "title":        (details.get("title") or "")[:120],
        "status":       details.get("status", ""),
        "budget":       details.get("value", {}).get("amount", 0),
        "buyer_name":   procuring.get("name", "невідомо"),
        "buyer_edrpou": procuring.get("identifier", {}).get("id", "00000000"),
        "winners":      winners,
    }


def save(session, rec):
    session.run(WRITE_TENDER,
                buyer_edrpou=rec["buyer_edrpou"],
                buyer_name=rec["buyer_name"],
                tender_id=rec["tender_id"],
                title=rec["title"],
                budget=rec["budget"],
                status=rec["status"])
    for w in rec["winners"]:
        session.run(WRITE_WINNER,
                    tender_id=rec["tender_id"],
                    edrpou=w["edrpou"],
                    name=w["name"],
                    city=w["city"])


def analytics(driver):
    print("\n" + "═"*60)
    print("  АНАЛІЗ РИЗИКІВ")
    print("═"*60)
    queries = [
        ("Топ компаній за кількістю перемог", """
            MATCH (t:Tender)-[:WINNER_IS]->(c:Company)
            RETURN c.name AS Компанія, COUNT(t) AS Перемог,
                   SUM(t.budget) AS ЗагальнаСума
            ORDER BY Перемог DESC LIMIT 10
        """),
        ("Найбільші тендери", """
            MATCH (buyer:Organization)-[:ANNOUNCED]->(t:Tender)-[:WINNER_IS]->(c:Company)
            RETURN t.tender_id AS ID, t.budget AS Бюджет,
                   buyer.name AS Замовник, c.name AS Переможець
            ORDER BY Бюджет DESC LIMIT 10
        """),
    ]
    with driver.session() as s:
        for title, q in queries:
            print(f"\n▶ {title}:")
            rows = s.run(q).data()
            if not rows:
                print("  (немає даних)")
                continue
            keys = list(rows[0].keys())
            for row in rows:
                print("  " + " | ".join(f"{str(row.get(k,''))[:35]:35}" for k in keys))


def main():
    print("╔══════════════════════════════════════════════════════╗")
    print("║   PROZORRO → NEO4J  v3                              ║")
    print("╚══════════════════════════════════════════════════════╝")

    print("\n[0] Підключення до Neo4j...")
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
        print("    ✓ Підключено")
    except Exception as e:
        print(f"    ✗ {e}")
        return

    # Отримуємо найновіші тендери
    ids, next_offset = get_last_offset()

    if not ids:
        print("✗ Не вдалося отримати список тендерів")
        return

    print(f"\n[2] Обробка {len(ids)} найновіших тендерів...")
    print(f"    Шукаємо ті, де awards.status = 'active'\n")

    saved   = 0
    checked = 0

    with driver.session() as session:
        for tid in ids:
            if saved >= MAX_SAVED:
                break

            details = fetch_details(tid)
            checked += 1

            if not details:
                continue

            rec = extract(details)
            status = details.get("status", "?")
            awards_count = len(details.get("awards", []))

            if rec is None:
                award_statuses = [a.get("status") for a in details.get("awards", [])]
                print(f"  [{checked:3}] пропуск | {status:12} | "
                      f"awards: {str(award_statuses)[:35]:35} | "
                      f"{details.get('tenderID','')[:20]}")
            else:
                save(session, rec)
                saved += 1
                winners_str = ", ".join(w["name"][:25] for w in rec["winners"])
                print(f"  [{checked:3}] ✓ ЗБЕРЕЖЕНО | "
                      f"{rec['tender_id'][:25]:25} | "
                      f"{rec['budget']:>12,.0f} грн | "
                      f"{winners_str[:35]}")

            time.sleep(0.1)

    print(f"\n{'═'*60}")
    print(f"  Перевірено: {checked} | Збережено: {saved}")
    print(f"{'═'*60}")

    if saved > 0:
        analytics(driver)
        print("\n  Neo4j Browser: MATCH (n)-[r]->(m) RETURN n, r, m LIMIT 200")
    else:
        print("\n  ⚠ Нічого не збережено.")
        print("  Всі 100 найновіших тендерів не мають active awards.")
        print("  Спробуй збільшити вибірку або перевір tender_sample.json")

    driver.close()


if __name__ == "__main__":
    main()