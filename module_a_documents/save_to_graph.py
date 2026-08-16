"""
save_to_graph.py — Модуль А: збереження виявлених сутностей у Neo4j
══════════════════════════════════════════════════════════════════════
Другий етап конвеєру обробки документів (підрозділ 3.2, рисунок 3.5):
приймає вже розпізнані NER-моделлю сутності (посадові особи, організації),
отримані process_all_docs.py, і записує зв'язки Officer -[:WORKS_AT]-> Organization
у графову базу даних Neo4j через оператор MERGE, що запобігає дублюванню
вузлів і зв'язків при повторних запусках на тих самих документах.

Використання:
  from save_to_graph import save_entities
  save_entities(driver, persons=["Немченко А.М."], orgs=["Селидівська міська рада"])
"""

from neo4j import GraphDatabase

MERGE_QUERY = """
MERGE (o:Organization {name: $org})
MERGE (p:Officer {name: $person})
MERGE (p)-[:WORKS_AT]->(o)
"""


def save_entities(driver: GraphDatabase.driver, persons: list[str], orgs: list[str]) -> None:
    """
    Записує у Neo4j усі комбінації (посадова особа × організація),
    виявлені в одному документі. Використання декартового добутку
    persons × orgs є свідомим спрощенням: документ (розпорядження,
    договір) типово згадує невелику кількість осіб і організацій,
    які юридично пов'язані між собою в межах цього документа.
    """
    with driver.session() as session:
        for org in orgs:
            for person in persons:
                session.run(MERGE_QUERY, person=person, org=org)
