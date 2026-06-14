from neo4j import GraphDatabase

# Налаштування підключення до твого запущенного локального сервера
URI = "neo4j://localhost:7687"
AUTH = ("neo4j", "12password")  # Якщо при створенні бази в Neo4j Desktop ти вказувала свій пароль, заміни password123 на нього

def run_anti_corruption_pipeline():
    try:
        with GraphDatabase.driver(URI, auth=AUTH) as driver:
            with driver.session() as session:
                print("Зв'язок встановлено. Очищення бази даних для створення нового каркаса...")
                session.run("MATCH (n) DETACH DELETE n")
                
                print("Створення онтологічної структури комплаєнсу...")
                query = """
                CREATE (officer:Officer {name: 'Іванов Іван Іванович', position: 'Голова департаменту ЖКГ'})
                CREATE (company:Company {name: 'ТОВ МегаБуд', edrpou: '12345678'})
                CREATE (doc:Document {title: 'Розпорядження №125 про ремонт дороги', type: 'Розпорядження'})
                CREATE (tender:Tender {tender_id: 'UA-2026-06-08-01', budget: 5000000})
                CREATE (addr:Address {full_address: 'м. Одеса, вул. Канатна, 83'})
                
                CREATE (officer)-[:SIGNED]->(doc)
                CREATE (doc)-[:ASSOCIATED_WITH]->(tender)
                CREATE (tender)-[:WINNER_IS]->(company)
                CREATE (officer)-[:REGISTERED_AT]->(addr)
                CREATE (company)-[:HAS_HQ_AT]->(addr)
                
                RETURN officer, company, doc, tender, addr
                """
                session.run(query)
                print("\n" + "="*50)
                print("УСПІХ! Каркас системи антикорупційного моніторингу розгорнуто.")
                print("Тестові сутності та зв'язки успішно завантажені в Neo4j.")
                print("="*50)
                
    except Exception as e:
        print(f"\nПомилка підключення або виконання: {e}")
        print("Перевірте, чи горить зелений статус RUNNING біля бази в Neo4j Desktop.")

if __name__ == "__main__":
    run_anti_corruption_pipeline()