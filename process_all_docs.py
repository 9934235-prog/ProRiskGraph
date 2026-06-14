import os
import fitz  # PyMuPDF для читання PDF
from neo4j import GraphDatabase
from transformers import pipeline

# 1. Налаштування бази даних
# Переконайся, що Neo4j запущено на твоєму комп'ютері
uri = "bolt://localhost:7687"
driver = GraphDatabase.driver(uri, auth=("neo4j", "12password"))

# 2. Завантаження моделі ШІ
print("Завантаження моделі NER (це займе хвилину)...")
ner_pipeline = pipeline("ner", model="Babelscape/wikineural-multilingual-ner", aggregation_strategy="simple")

def process_pdf(file_path):
    try:
        # Читання PDF
        doc = fitz.open(file_path)
        text = ""
        for page in doc:
            text += page.get_text()
        
        # Аналіз сутностей
        entities = ner_pipeline(text)
        
        # Витягуємо дані (PER - особи, ORG - організації)
        person = next((e['word'] for e in entities if e['entity_group'] == 'PER'), "Невідомий")
        org = next((e['word'] for e in entities if e['entity_group'] == 'ORG'), "Невідома організація")
        
        # Запис у Neo4j
        # MERGE створює вузол тільки якщо його ще немає, тому дублікатів не буде
        query = """
        MERGE (p:Officer {name: $person})
        MERGE (o:Organization {name: $org})
        MERGE (p)-[:WORKS_AT]->(o)
        """
        with driver.session() as session:
            session.run(query, person=person, org=org)
        print(f"✅ Успішно оброблено: {os.path.basename(file_path)} -> {person} | {org}")
        
    except Exception as e:
        print(f"❌ Помилка з файлом {file_path}: {e}")

# 3. Обробка всіх файлів у папці
folder_path = r"D:\АЛЬОНА\УНІВЕР\ІІ_Семестр\Нова папка\documents"

if os.path.exists(folder_path):
    print(f"Починаю обробку папки: {folder_path}")
    for filename in os.listdir(folder_path):
        if filename.endswith(".pdf"):
            full_path = os.path.join(folder_path, filename)
            process_pdf(full_path)
else:
    print(f"Помилка: Папку не знайдено за адресою {folder_path}")

driver.close()
print("Готово! Всі дані в базі.")