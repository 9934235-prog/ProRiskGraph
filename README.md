# ProRiskGraph v1.0
### Система автоматизованого виявлення корупційних ризиків у закупівлях ОМС

**Дипломна робота** | НУ «Одеська Політехніка» | Галіцина Олена, група ЗАІ-201  
**Науковий керівник:** Воронкова М.О.  
**Спеціальність:** 122 Комп'ютерні науки

---

## Що робить система

Автоматично аналізує тендери конкретного органу місцевого самоврядування (ОМС) з відкритої системи Prozorro, виявляє корупційні ризики та будує граф зв'язків у базі даних Neo4j.

**Два модулі:**
- **Модуль А** — аналіз PDF-документів ОМС: витяг сутностей (NER), побудова графу Officer → Organization → Address
- **Модуль Б** — масова обробка тендерів Prozorro: завантаження через API, класифікація ризиків, граф-візуалізація

---

## Вимоги до системи

| Компонент | Мінімум | Рекомендовано |
|-----------|---------|---------------|
| ОС | Windows 10 | Windows 10/11 |
| RAM | 8 ГБ | 16 ГБ |
| Диск (вільно) | 5 ГБ | 10 ГБ |
| Python | 3.10+ | 3.12+ |
| Інтернет | Потрібен (перший запуск) | — |

---

## Крок 1 — Встановити Neo4j Desktop

1. Завантажити з [neo4j.com/download](https://neo4j.com/download/)
2. Встановити та запустити
3. Створити нову базу даних:
   - Name: `proriskgraph`
   - Password: `12password`
4. Натиснути **Start** → дочекатися зеленого індикатора

> ⚠️ Пароль має бути саме `12password` — інакше треба змінити константу `NEO4J_PASSWORD` у кожному скрипті.

---

## Крок 2 — Підготувати Python-середовище

Відкрити PowerShell і виконати по черзі:

```powershell
# Перейти в папку проекту
cd D:\АЛЬОНА\УНІВЕР\ІІ_Семестр\Нова папка

# Створити віртуальне середовище
python -m venv venv

# Активувати
.\venv\Scripts\Activate.ps1

# Встановити залежності
pip install neo4j requests transformers torch sentencepiece PyMuPDF
```

> ⏱ Встановлення займає 5–10 хвилин. Моделі (~3 ГБ) завантажуються автоматично при першому запуску скриптів.

---

## Крок 3 — Завантажити тендери Prozorro у Neo4j

```powershell
python prozorro_to_neo4j_v8.py
```

**Що відбувається:**
- Скрипт звертається до API Prozorro через POST-запит
- Завантажує всі тендери Кам'янської МР (ЄДРПОУ 24604168)
- Записує у Neo4j (~1 481 тендер, ~2 хвилини)

**Щоб завантажити тендери іншого ОМС** — змінити один рядок у скрипті:
```python
TARGET_EDRPOU = "24604168"   # ← замінити на ЄДРПОУ потрібного ОМС
```

ЄДРПОУ будь-якого ОМС можна знайти на [prozorro.gov.ua](https://prozorro.gov.ua/uk/search/tender) у розділі пошуку за замовником.

---

## Крок 4 — Класифікувати ризики

```powershell
python risk_classifier_v3.py
```

**Що відбувається:**
- Завантажує модель xlm-roberta (~1.5 ГБ, тільки перший раз)
- Класифікує кожен тендер за гібридною методикою (правила + NLP)
- Записує risk_score (0.0–1.0) та risk_level у Neo4j
- Виводить підсумковий звіт і топ ризикових тендерів

> ⏱ Перший запуск: ~5 хв (завантаження моделі) + ~2 хв (класифікація).  
> Повторний запуск: ~2 хв (модель з кешу).

---

## Крок 5 — Переглянути граф у Neo4j Browser

1. Відкрити Neo4j Desktop → натиснути **Open**
2. Вставити запит і натиснути Ctrl+Enter:

**Граф ризикових тендерів:**
```cypher
MATCH (o:Organization)-[:ANNOUNCED]->(t:Tender)
WHERE t.risk_score >= 0.70
RETURN o, t
LIMIT 80
```

**Топ ризиків у таблиці:**
```cypher
MATCH (t:Tender)
WHERE t.risk_score >= 0.75
RETURN t.tender_id, t.title, t.budget, t.risk_level, t.risk_score
ORDER BY t.risk_score DESC, t.budget DESC
LIMIT 50
```

**Розподіл по категоріях:**
```cypher
MATCH (t:Tender)
WHERE t.risk_category IS NOT NULL
RETURN t.risk_category AS категорія,
       count(t) AS кількість,
       sum(t.budget) AS загальний_бюджет
ORDER BY кількість DESC
```

**Кольорова візуалізація** — виконати спочатку:
```cypher
MATCH (t:Tender) WHERE t.risk_score >= 0.90 SET t:HighRisk;
MATCH (t:Tender) WHERE 0.70 <= t.risk_score < 0.90 SET t:MediumRisk;
MATCH (t:Tender) WHERE t.risk_score < 0.70 SET t:LowRisk;
```
Потім у браузері клікнути на мітку `HighRisk` → встановити червоний колір.

---

## Крок 6 (опційно) — Аналіз PDF-документів ОМС

Помістити PDF-документи (акти, розпорядження, договори) у папку:
```
D:\АЛЬОНА\УНІВЕР\ІІ_Семестр\Нова папка\documents\
```

Запустити:
```powershell
python process_all_docs.py
```

Потім перевірити виявлені зв'язки:
```cypher
MATCH (o:Officer)-[:REGISTERED_AT]->(a:Address)<-[:HAS_HQ_AT]-(c:Company)
RETURN o.name AS Посадова_особа, c.name AS Компанія, a.full_address AS Спільна_адреса
```

---

## Крок 7 (опційно) — A/B демонстраційні сценарії

```powershell
python demo_scenarios.py
```

Вставляє два синтетичних кейси і одразу класифікує:
- **Сценарій А** — легітимна закупівля → 🟢 ПОМІРНИЙ
- **Сценарій Б** — підозрілий тендер з конфліктом інтересів → 🔴 КРИТИЧНИЙ

---

## Структура файлів проекту

```
Нова папка/
├── prozorro_to_neo4j_v8.py     # Завантаження тендерів Prozorro
├── risk_classifier_v3.py       # Класифікація ризиків (гібридна)
├── nlp_analyzer.py             # NER-аналіз тексту PDF
├── save_to_graph.py            # Збереження у Neo4j (базовий)
├── process_all_docs.py         # Пакетна обробка PDF
├── demo_scenarios.py           # A/B демонстраційні сценарії
├── prozorro_debug.py           # Діагностика API (утиліта)
├── README.md                   # Цей файл
├── venv/                       # Python-середовище
└── documents/                  # Папка для PDF-документів ОМС
```

---

## Графова модель (схема)

```
Officer ──SIGNED──► Document ──ASSOCIATED_WITH──► Tender ──WINNER_IS──► Company
   │                                                  │                     │
REGISTERED_AT                                    ANNOUNCED            HAS_HQ_AT
   │                                                  │                     │
   ▼                                            Organization               ▼
Address ◄──────────────────────────────────────────────────────── Address
   ▲                                          (збіг адрес = конфлікт інтересів)
```

**6 типів вузлів:** Officer, Document, Tender, Company, Address, Payment  
**9 типів зв'язків:** SIGNED, ANNOUNCED, WINNER_IS, REGISTERED_AT, HAS_HQ_AT, ASSOCIATED_WITH, HAS_PAYMENT, RECEIVED_PAYMENT, AUTHORIZED_PAYMENT

---

## Методика класифікації ризиків

| Статус тендера | Бюджет | Score | Рівень |
|----------------|--------|-------|--------|
| unsuccessful | > 500 000 грн | 0.90 | 🔴 КРИТИЧНИЙ |
| unsuccessful | ≤ 500 000 грн | 0.70 | 🟠 СЕРЕДНІЙ |
| cancelled | будь-який | 0.60 | 🟡 ПОМІРНИЙ |
| complete | > 1 000 000 грн | 0.80 | 🔴 ВИСОКИЙ |
| complete | 500 тис – 1 млн | 0.55 | 🟠 СЕРЕДНІЙ |
| complete | ≤ 500 000 грн | 0.10 | 🟢 НИЗЬКИЙ |

Додатково: для тендерів > 500 000 грн застосовується NLP-аналіз назви через `xlm-roberta-large-xnli`. Розмите формулювання підвищує score на 0.10.

---

## Можливі проблеми

**Neo4j не підключається:**
```
✗ Помилка підключення
```
→ Відкрити Neo4j Desktop і переконатися що база запущена (зелений індикатор).

**Помилка завантаження моделі:**
```
OSError: Can't load model
```
→ Перевірити інтернет-з'єднання. Модель завантажується з huggingface.co (~1.5 ГБ).

**PowerShell не дозволяє активувати venv:**
```
cannot be loaded because running scripts is disabled
```
→ Виконати: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`

**Мало RAM — скрипт падає під час класифікації:**
→ Зменшити `BATCH_SIZE = 4` у файлі `risk_classifier_v3.py`

---

## Результати на реальних даних

Протестовано на тендерах Кам'янської (Дніпродзержинської) міської ради:

- **1 481** тендер завантажено
- **228,6 млн грн** — загальний обсяг закупівель
- **71** тендер з критичним/високим ризиком (score ≥ 0.75)
- **96** тендерів без переможця (unsuccessful)
- **130 млн грн** — сума ризикових закупівель (56,9%)

---
