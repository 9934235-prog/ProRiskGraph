import requests
import time
from neo4j import GraphDatabase

# ─── НАЛАШТУВАННЯ ──────────────────────────────────────────────────────
NEO4J_URI      = "bolt://localhost:7687"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "12password"

BASE_URL   = "https://public-api.prozorro.gov.ua/api/2.5"
MAX_SAVED  = 15     # Скільки тендерів З ПЕРЕМОЖЦЯМИ зберегти
PAGE_SIZE  = 50     # Скільки брати за один запит

# ─── CYPHER-ЗАПИТИ ─────────────────────────────────────────────────────
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
ON CREATE SET c.name = $name
MERGE (t)-[:WINNER_IS]->(c)
"""

# ─── ФУНКЦІЇ ──────────────────────────────────────────────────────────

def fetch_tender_ids(page_size: int, offset: str | None) -> tuple[list, str | None]:
    # Сортування -dateModified дає нам найсвіжіші тендери
    params = {"limit": page_size, "sort": "-dateModified"}
    if offset:
        params["offset"] = offset

    try:
        r = requests.get(f"{BASE_URL}/tenders", params=params, timeout=20)
        r.raise_for_status()
        body = r.json()
        ids = [item["id"] for item in body.get("data", [])]
        next_off = body.get("next_page", {}).get("offset")
        return ids, next_off
    except Exception as e:
        print(f"  ⚠ Помилка API: {e}")
        return [], None

def fetch_details(tender_id: str) -> dict | None:
    try:
        r = requests.get(f"{BASE_URL}/tenders/{tender_id}", timeout=20)
        return r.json().get("data") if r.status_code == 200 else None
    except:
        return None

def extract(details: dict) -> dict | None:
    awards = details.get("awards", [])
    active = [a for a in awards if a.get("status") == "active"]
    if not active: return None

    procuring = details.get("procuringEntity", {})
    return {
        "tender_id": details.get("tenderID"),
        "title": (details.get("title") or "без назви")[:120],
        "status": details.get("status", ""),
        "budget": details.get("value", {}).get("amount", 0),
        "buyer_name": procuring.get("name", "невідомо"),
        "buyer_edrpou": procuring.get("identifier", {}).get("id", "00000000"),
        "winners": [{"edrpou": sup.get("identifier", {}).get("id", "00000000"), "name": sup.get("name", "невідомо")}
                    for award in active for sup in award.get("suppliers", [])]
    }

def main():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    saved, checked, offset = 0, 0, None
    
    print("Починаємо пошук сучасних тендерів...")
    with driver.session() as session:
        while saved < MAX_SAVED:
            ids, offset = fetch_tender_ids(PAGE_SIZE, offset)
            if not ids: break
            
            for tid in ids:
                if saved >= MAX_SAVED: break
                details = fetch_details(tid)
                checked += 1
                rec = extract(details) if details else None
                
                if rec:
                    session.run(WRITE_TENDER, **rec)
                    for w in rec["winners"]:
                        session.run(WRITE_WINNER, tender_id=rec["tender_id"], **w)
                    saved += 1
                    print(f"✓ ЗБЕРЕЖЕНО: {rec['tender_id']} | Переможців: {len(rec['winners'])}")
                else:
                    print(f"  Пропуск {tid[:10]}...")
                
                time.sleep(0.2)
    
    driver.close()
    print(f"\nГотово! Збережено {saved} тендерів.")

if __name__ == "__main__":
    main()