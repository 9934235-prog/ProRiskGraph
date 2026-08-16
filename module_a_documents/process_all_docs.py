"""
process_all_docs.py — Модуль А: NER-аналіз документів органів місцевого
самоврядування
══════════════════════════════════════════════════════════════════════
Фінальна (консолідована) версія програмного модуля.

Перший і другий етапи конвеєру обробки документів (підрозділ 3.2,
рисунок 3.5): витягує текст із PDF-документів, за потреби застосовує
OCR (для сканованих документів без текстового шару) і виконує
розпізнавання іменованих сутностей (NER). Збереження виявлених
зв'язків "посадова особа — організація" у Neo4j виконує окремий
модуль save_to_graph.py (третій-четвертий етапи конвеєру).

Послідовність обробки одного документа:
  1. Спроба прямого витягу тексту (PyMuPDF).
  2. Якщо текстовий шар відсутній (скан) — рендер сторінки в зображення
     (300 DPI) і розпізнавання тексту через Tesseract OCR (ukr+rus).
  3. Виділення всіх сутностей PER (особи) та ORG (організації) —
     не лише першої знайденої, оскільки документ може містити кількох
     посадових осіб і кілька організацій.
  4. Передача виявлених сутностей у save_to_graph.save_entities()
     для запису у графову базу Neo4j.

Вимоги:
  pip install pymupdf pytesseract pillow neo4j transformers torch
  Встановлений Tesseract OCR (шлях вказано в TESSERACT_CMD).

Запуск:
  python process_all_docs.py
"""

import os
import io
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
from neo4j import GraphDatabase
from transformers import pipeline

from save_to_graph import save_entities

# ─── НАЛАШТУВАННЯ ────────────────────────────────────────────────────────────

NEO4J_URI      = "bolt://localhost:7687"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "12password"

TESSERACT_CMD  = r"D:\Tesseract-OCR\tesseract.exe"
OCR_LANG       = "ukr+rus"
OCR_DPI        = 300

DOCUMENTS_FOLDER = r"D:\АЛЬОНА\УНІВЕР\ІІ_Семестр\Нова папка\documents"

NER_MODEL      = "Babelscape/wikineural-multilingual-ner"
NER_TEXT_LIMIT = 512  # обмеження довжини тексту, що подається в модель

pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

# ─── ВИТЯГ ТЕКСТУ (з fallback на OCR) ─────────────────────────────────────────

def extract_text_with_ocr(file_path: str) -> tuple[str, str]:
    """
    Повертає (текст, метод), де метод — 'text' (прямий витяг)
    або 'ocr' (документ виявився сканом без текстового шару).
    """
    doc = fitz.open(file_path)
    text = ""
    for page in doc:
        text += page.get_text()

    if text.strip():
        return text, "text"

    print("   → Скан, запускаю OCR...")
    ocr_text = ""
    for page in doc:
        mat = fitz.Matrix(OCR_DPI / 72, OCR_DPI / 72)
        pix = page.get_pixmap(matrix=mat)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        ocr_text += pytesseract.image_to_string(img, lang=OCR_LANG) + "\n"

    return ocr_text, "ocr"

# ─── ОБРОБКА ОДНОГО ДОКУМЕНТА ────────────────────────────────────────────────

def process_pdf(file_path: str, ner_pipeline, driver) -> None:
    filename = os.path.basename(file_path)
    try:
        text, method = extract_text_with_ocr(file_path)

        if not text.strip():
            print(f"⚠️  Не вдалося витягти текст (навіть OCR): {filename}")
            return

        entities = ner_pipeline(text[:NER_TEXT_LIMIT])

        # Беремо ВСІХ осіб і всі організації, а не лише першу знайдену —
        # документ (наприклад, розпорядження або договір) може згадувати
        # кількох посадових осіб і кілька організацій одночасно.
        persons = [e["word"] for e in entities if e["entity_group"] == "PER"]
        orgs    = [e["word"] for e in entities if e["entity_group"] == "ORG"]

        if not persons:
            persons = ["Невідомий"]
        if not orgs:
            orgs = ["Невідома організація"]

        save_entities(driver, persons, orgs)

        icon = "📄" if method == "text" else "🔍"
        print(f"✅ {icon} {filename} [{method.upper()}]")
        print(f"   Особи ({len(persons)}): {persons}")
        print(f"   Організації ({len(orgs)}): {orgs}")

    except Exception as e:
        print(f"❌ Помилка з файлом {filename}: {e}")

# ─── ГОЛОВНА ФУНКЦІЯ ─────────────────────────────────────────────────────────

def main():
    print("╔══════════════════════════════════════════════════════╗")
    print("║   process_all_docs — Модуль А: аналіз документів    ║")
    print("╚══════════════════════════════════════════════════════╝\n")

    print("Завантаження моделі NER (це займе хвилину)...")
    ner_pipeline = pipeline("ner", model=NER_MODEL, aggregation_strategy="simple")
    print("Модель завантажена.\n")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    if not os.path.exists(DOCUMENTS_FOLDER):
        print(f"Помилка: Папку не знайдено: {DOCUMENTS_FOLDER}")
        driver.close()
        return

    pdf_files = [f for f in os.listdir(DOCUMENTS_FOLDER) if f.endswith(".pdf")]
    print(f"Знайдено {len(pdf_files)} PDF файлів\n")
    print("=" * 60)

    for filename in sorted(pdf_files):
        full_path = os.path.join(DOCUMENTS_FOLDER, filename)
        process_pdf(full_path, ner_pipeline, driver)
        print()

    driver.close()
    print("=" * 60)
    print("Готово! Всі дані записані в базу Neo4j.")


if __name__ == "__main__":
    main()
