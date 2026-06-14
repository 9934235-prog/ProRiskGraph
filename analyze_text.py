from transformers import pipeline

# Використовуємо перевірену модель, яка точно працює без паролів
model_name = "Babelscape/wikineural-multilingual-ner"

print("Завантаження моделі (це може зайняти трохи часу)...")
# Модель завантажиться один раз і залишиться у папці venv
ner_pipeline = pipeline("ner", model=model_name, aggregation_strategy="simple")

# Текст для тесту
text = "Селідівська міська рада в особі начальника Селідівської міської військової адміністрації Немченка Анатолія Миколайовича"

# Аналіз
entities = ner_pipeline(text)

print("\n--- Знайдені сутності ---")
for entity in entities:
    print(f"Слово: {entity['word']} | Тип: {entity['entity_group']} | Впевненість: {round(entity['score'], 2)}")