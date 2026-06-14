import fitz  # Це і є бібліотека PyMuPDF

# Шлях до твого файлу
pdf_path = "Договір № 18 від 23.03.2026.pdf"

try:
    # Відкриваємо PDF
    doc = fitz.open(pdf_path)

    # Читаємо текст із першої сторінки (індекс 0 означає першу сторінку)
    text = doc[0].get_text()

    print("--- Текст із договору ---")
    print(text[:500])  # Виводимо перші 500 символів, щоб перевірити
    
    doc.close()
except Exception as e:
    print(f"Сталася помилка при читанні файлу: {e}")