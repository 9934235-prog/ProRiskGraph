import pandas as pd
from neo4j import GraphDatabase

# Налаштування підключення
FILE_PATH = "data.csv"
URI = "bolt://localhost:7687"
USER = "neo4j"
PASSWORD = "12password" # Переконайся, що пароль збігається з твоїм у Neo4j Desktop

def enrich_graph():
    try:
        # Читаємо файл з кодуванням cp1251
        df = pd.read_csv(FILE_PATH, sep=';', encoding='cp1251')
        print("✅ Файл 'data.csv' успішно зчитано.")
        
        driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
        
        with driver.session() as session:
            for _, row in df.iterrows():
                # Пропускаємо порожні рядки (nan)
                if pd.isna(row['EDRPOU']):
                    continue
                
                # Перетворюємо ЄДРПОУ на ціле число, а потім на рядок (прибирає .0)
                try:
                    edrpou_val = str(int(row['EDRPOU']))
                except ValueError:
                    continue # Якщо це не число, пропускаємо рядок
                
                address = str(row.get('Address', ''))
                beneficiary = str(row.get('Beneficiary', ''))
                
                # Запит до бази
                query = """
                MATCH (c:Company {edrpou: $edrpou})
                SET c.address = $address,
                    c.beneficiary = $beneficiary
                RETURN count(c) as updated_count
                """
                
                result = session.run(query, edrpou=edrpou_val, address=address, beneficiary=beneficiary)
                count = result.single()["updated_count"]
                
                if count > 0:
                    print(f"✅ Оновлено: ЄДРПОУ {edrpou_val}")
                else:
                    print(f"⚠️ Не знайдено в базі: {edrpou_val}")
        
        driver.close()
        print("🚀 Граф успішно збагачено!")
        
    except Exception as e:
        print(f"❌ Сталася помилка: {e}")

if __name__ == "__main__":
    enrich_graph()