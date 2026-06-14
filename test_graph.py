from neo4j import GraphDatabase

# Налаштування підключення до твого Neo4j з твоїм паролем
driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "12password"))

def create_test_data(tx):
    query = """
    CREATE (o:Officer {name: 'Іванов І.І.'})
    CREATE (c:Company {name: 'ТОВ МегаБуд'})
    CREATE (o)-[:SIGNED]->(:Document {title: 'Розпорядження №1'})-[:ASSOCIATED_WITH]->(:Tender {id: 'UA-2026'})-[:WINNER_IS]->(c)
    RETURN o.name, c.name
    """
    tx.run(query)

# Запуск функції
try:
    with driver.session() as session:
        session.execute_write(create_test_data)
        print("Тестові дані успішно записані в базу!")
except Exception as e:
    print(f"Помилка при записі: {e}")
finally:
    driver.close()