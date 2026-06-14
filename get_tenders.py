import requests
from neo4j import GraphDatabase

# Налаштування Neo4j
URI = "bolt://localhost:7687"
USER = "neo4j"
PASSWORD = "12password"

def save_tender_to_graph(edrpou, tender_id, title):
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    with driver.session() as session:
        # Створюємо тендер і зв'язок із замовником
        query = """
        MATCH (c:Company {edrpou: $edrpou})
        MERGE (t:Tender {id: $id})
        ON CREATE SET t.title = $title
        MERGE (c)-[:ANNOUNCED]->(t)
        """
        session.run(query, edrpou=edrpou, id=tender_id, title=str(title))
    driver.close()

def save_winner_to_graph(tender_id, winner_name, winner_edrpou):
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    with driver.session() as session:
        # Створюємо переможця і зв'язок з тендером
        query = """
        MATCH (t:Tender {id: $tender_id})
        MERGE (w:Company {edrpou: $winner_edrpou})
        ON CREATE SET w.name = $winner_name
        MERGE (t)-[:WINNER_IS]->(w)
        """
        session.run(query, tender_id=tender_id, winner_name=winner_name, winner_edrpou=winner_edrpou)
    driver.close()

def get_prozorro_tenders(edrpou):
    base_url = "https://public.api.openprocurement.org/api/2.5/tenders"
    params = {'query': f'procuringEntity.identifier.id:{edrpou}'}
    
    print(f"🔄 Пошук тендерів для ЄДРПОУ {edrpou}...")
    response = requests.get(base_url, params=params)
    tenders = response.json().get('data', [])
    
    print(f"🔄 Завантаження {len(tenders)} тендерів...")
    for tender in tenders:
        tender_id = tender.get('id')
        save_tender_to_graph(edrpou, tender_id, tender.get('title', 'Без назви'))
        
        # Отримуємо деталі тендера для пошуку переможця
        details_url = f"{base_url}/{tender_id}"
        details_response = requests.get(details_url).json()
        details = details_response.get('data', {})
        
        awards = details.get('awards', [])
        for award in awards:
            # Шукаємо активного переможця
            if award.get('status') == 'active':
                supplier = award.get('suppliers', [{}])[0]
                winner_id = supplier.get('identifier', {}).get('id')
                winner_name = supplier.get('name')
                
                if winner_id:
                    save_winner_to_graph(tender_id, winner_name, winner_id)
                    print(f"🏆 Переможець для {tender_id}: {winner_name}")

    print("✅ Готово! Дані про тендери та переможців у базі.")

if __name__ == "__main__":
    get_prozorro_tenders("04052962")