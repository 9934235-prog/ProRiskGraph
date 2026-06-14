from neo4j import GraphDatabase
from transformers import pipeline

# 1. Підключення до бази Neo4j
uri = "bolt://localhost:7687"
driver = GraphDatabase.driver(uri, auth=("neo4j", "12password"))

# 2. Налаштування ШІ
ner_pipeline = pipeline("ner", model="Babelscape/wikineural-multilingual-ner", aggregation_strategy="simple")

def save_to_neo4j(person, org):
    query = """
    MERGE (p:Officer {name: $person})
    MERGE (o:Organization {name: $org})
    MERGE (p)-[:WORKS_AT]->(o)
    """
    with driver.session() as session:
        session.run(query, person=person, org=org)
        print(f"Зв'язок успішно записано: {person} працює в {org}")

# 3. Аналіз тексту
text = "Селідівська міська рада в особі начальника адміністрації Немченка Анатолія Миколайовича"
entities = ner_pipeline(text)

# Витягуємо дані
person = next((e['word'] for e in entities if e['entity_group'] == 'PER'), "Невідомий")
org = next((e['word'] for e in entities if e['entity_group'] == 'ORG'), "Невідома організація")

# 4. Запис
save_to_neo4j(person, org)
driver.close()