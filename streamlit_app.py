from __future__ import annotations
"""
PhaDataPro AI Чат-бот — полная реализация с поддержкой всех модулей, каналов,
синонимов, контекста и пошаговых инструкций.
"""

import json
import math
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import streamlit as st

# =============================================================================
# КОНФИГУРАЦИЯ
# =============================================================================

_BASE = Path(__file__).parent

DATA_DIR = _BASE / 'data'
LOG_DIR  = _BASE / 'logs'
HISTORY_FILE = DATA_DIR / 'chat_history.json'
LOG_FILE     = LOG_DIR  / 'chat_history.log'

KB_FILES = [
    _BASE / 'modules_guide.md',
    _BASE / 'prompt.md',
    _BASE / 'ТЗ PDP ИИ.docx',
    _BASE / 'Вопросы для ИИ маршрутизатор.docx',
    _BASE / 'Инструкция для пользователей PhadataPro (1).pdf',
]

# Ключ загружается из Streamlit Secrets (Cloud) или переменной окружения (локально).
# Для локальной работы создайте файл .streamlit/secrets.toml:
# Файл secrets.toml добавлен в .gitignore и не попадает в GitHub.
def _load_api_key() -> str:
    key = ""
    try:
        key = st.secrets.get("OPENAI_API_KEY", "") or ""
    except Exception:
        pass
    if not key:
        key = os.getenv("OPENAI_API_KEY", "")
    return key

OPENAI_API_KEY: str = _load_api_key()

OPENAI_COMPLETION_URL = 'https://api.openai.com/v1/chat/completions'
OPENAI_EMBEDDING_URL  = 'https://api.openai.com/v1/embeddings'
COMPLETION_MODEL  = 'gpt-4o'
EMBEDDING_MODEL   = 'text-embedding-3-small'
MAX_TOKENS        = 2000
RELEVANCE_THRESHOLD = 0.12

# =============================================================================
# СИНОНИМЫ КАНАЛОВ, МОДУЛЕЙ, ТИПОВ АНАЛИЗА
# =============================================================================

# Нормализованные ключи каналов → списки синонимов (в нижнем регистре)
CHANNEL_SYNONYMS: Dict[str, List[str]] = {
    # ── АПТЕЧНЫЕ ДАННЫЕ ────────────────────────────────────────────────────────
    'sell_out': [
        # Latin
        'sell out', 'sell-out', 'sellout', 'sel out', 'sel-out',
        # Cyrillic transliterations
        'сел аут', 'сел-аут', 'селл аут', 'селл-аут', 'сэлл аут', 'сэл аут',
        # Russian synonyms
        'розничные продажи', 'розница', 'ретейл', 'retail',
        'аптечные продажи', 'продажи в аптеках',
    ],
    'sell_in': [
        # Latin
        'sell in', 'sell-in', 'sellin', 'sel in', 'sel-in',
        # Cyrillic transliterations
        'сел ин', 'сел-ин', 'селл ин', 'селл-ин', 'сэлл ин', 'сэл ин',
        # Russian synonyms
        'закупки', 'оптовые продажи', 'оптовая', 'опт',
        'закупки аптек', 'входящие закупки',
    ],
    'sell_out_ecom': [
        'sell out + e-com', 'sell out + ecom', 'sell out ecom',
        'sell out e com', 'sell out e-com', 'sel out ecom',
        'аут + ком', 'аут+ком', 'розница + онлайн', 'розница+онлайн',
        'продажи + онлайн', 'офлайн + онлайн',
    ],
    'placement': [
        'перемещение', 'движение', 'movement', 'transfer',
        'логистика', 'перемещение товара', 'передача товара',
        'внутреннее перемещение', 'межфилиальное перемещение',
    ],
    'stock': [
        'остатки', 'остаток', 'stock', 'наличие', 'запасы',
        'inventory', 'товарные остатки', 'складские остатки',
        'наличие товара', 'запас товара', 'товар в наличии',
    ],
    'ecom': [
        'e-com', 'ecom', 'e-commerce', 'ecommerce', 'е-ком', 'еком',
        'электронная коммерция', 'онлайн', 'интернет-аптека',
        'онлайн продажи', 'интернет продажи', 'онлайн аптека',
        'интернет торговля', 'цифровой канал',
    ],
    # ── ДАННЫЕ ДИСТРИБЬЮТОРА ───────────────────────────────────────────────────
    'sell_in_tender': [
        'sell in + tender', 'sell in tender', 'sellin tender',
        'sel in + tender', 'sel in tender',
        'сел ин + тендер', 'сел ин тендер', 'селл ин + тендер',
        'закупки + тендер', 'закупки с тендером', 'тендерные закупки',
        'sell in+tender',
    ],
    'tender': [
        'tender', 'тендер', 'госзакупка', 'государственная закупка',
        'гос закупка', 'гос. закупка', 'тендерная закупка',
        'государственный тендер', 'госзакупки', 'гос. закупки',
        'закупки для государства', 'закупки для больниц',
    ],
    'import_channel': [
        'импорт', 'import', 'ввоз', 'иностранный товар', 'таможня',
        'ввоз товара', 'импортные товары', 'иностранные товары',
        'международные поставки', 'зарубежные поставки',
    ],
    'dist_stock': [
        'остатки дистрибьютора', 'складские остатки дистрибьютора',
        'наличие у дистрибьютора', 'склад дистрибьютора',
        'запасы дистрибьютора',
    ],
}

MODULE_SYNONYMS: Dict[str, List[str]] = {
    'pharmacy_data': [
        'аптечные данные', 'аптечные', 'аптека', 'аптечный',
        'pharmacy data', 'pharmacy', 'розничный', 'ас', 'аптечная сеть',
        'данные аптек', 'аптечный канал',
    ],
    'distributor_data': [
        'данные дистрибьютора', 'дистрибьютор', 'дистрибьюторские данные',
        'distributor data', 'distributor', 'дс', 'дистр',
        'оптовик', 'wholesale', 'данные оптовика',
    ],
}

ANALYSIS_SYNONYMS: Dict[str, List[str]] = {
    'sales_breakdown': [
        'анализ продаж в разрезе', 'продажи по регионам', 'продажи по ас',
        'sales breakdown', 'разрез', 'в разрезе', 'детализация продаж',
        'продажи по менеджерам', 'продажи по дистрибьюторам',
    ],
    'plan_vs_fact': [
        'сравнение плана с фактом', 'план факт', 'plan vs fact',
        'выполнение плана', 'план и факт', 'план-факт', 'планфакт',
        'сравнить план', 'план/факт',
    ],
    'percent_plan': [
        'процент выполнения плана', '% выполнения', 'процент плана',
        'выполнение плана в процентах', 'степень выполнения',
    ],
    'growth': [
        'прирост продаж', 'growth', 'динамика', 'темп роста',
        'рост продаж', 'прирост', 'изменение продаж', 'динамика продаж',
        'прирост упаковок', 'прирост суммы',
    ],
    'share': [
        'доля товара', 'доля рынка', 'share', 'market share',
        'рыночная доля', 'доля продаж', 'доля упаковок', 'доля суммы',
        'процент от рынка',
    ],
    'high_potential': [
        'высокопотенциальные точки', 'категория спа', 'спа',
        'потенциальные точки', 'приоритетные аптеки', 'стратегические аптеки',
    ],
    'categorization': [
        'категоризация аптек', 'categorization', 'abc анализ', 'abc-анализ',
        'абс анализ', 'сегментация аптек', 'классификация аптек',
        'категория а', 'категория b', 'категория c',
    ],
    'login': [
        'личный кабинет', 'войти', 'войти в систему', 'вход в систему',
        'как зайти', 'как войти', 'авторизация', 'авторизоваться',
        'sign in', 'signin', 'зайти в систему', 'открыть систему',
        'как открыть', 'как попасть в систему',
    ],
}

# Привязка канала к модулю (для авто-определения)
CHANNEL_MODULE_MAP: Dict[str, str] = {
    'sell_out':       'pharmacy_data',
    'sell_in':        'pharmacy_data',
    'sell_out_ecom':  'pharmacy_data',
    'placement':      'pharmacy_data',
    'stock':          'pharmacy_data',
    'ecom':           'pharmacy_data',
    'sell_in_tender': 'distributor_data',
    'tender':         'distributor_data',
    'import_channel': 'distributor_data',
    'dist_stock':     'distributor_data',
    # dist_sell_in определяется контекстом
}

# Отображаемые имена каналов
CHANNEL_DISPLAY: Dict[str, str] = {
    'sell_out':       'Sell Out (розница)',
    'sell_in':        'Sell In (закупки аптек)',
    'sell_out_ecom':  'Sell Out + E-com',
    'placement':      'Перемещение',
    'stock':          'Остатки',
    'ecom':           'E-com (онлайн)',
    'sell_in_tender': 'Sell In + Tender',
    'tender':         'Tender (госзакупки)',
    'import_channel': 'Импорт',
    'dist_stock':     'Остатки дистрибьютора',
    'dist_sell_in':   'Sell In дистрибьютора',
}

MODULE_DISPLAY: Dict[str, str] = {
    'pharmacy_data':    'Аптечные данные',
    'distributor_data': 'Данные дистрибьютора',
}

# Каналы по модулям (для UI)
PHARMACY_CHANNELS    = ['sell_out', 'sell_in', 'sell_out_ecom', 'placement', 'stock', 'ecom']
DISTRIBUTOR_CHANNELS = ['dist_sell_in', 'sell_in_tender', 'tender', 'dist_stock', 'import_channel']

# =============================================================================
# НОРМАЛИЗАЦИЯ ТЕКСТА
# =============================================================================

def normalize(text: str) -> str:
    """Приводит текст к нижнему регистру, убирает диакритику и лишние символы."""
    text = text.lower().strip()
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def extract_channel(text: str, current_module: Optional[str] = None) -> Optional[str]:
    """Извлекает канал из текста с учётом текущего модуля для разрешения омонимии."""
    n = normalize(text)

    # Каналы с однозначной привязкой к модулю — проверяем в первую очередь
    unambiguous = [
        'sell_out_ecom', 'placement', 'ecom',
        'sell_in_tender', 'tender', 'import_channel', 'dist_stock',
    ]
    for key in unambiguous:
        for syn in CHANNEL_SYNONYMS.get(key, []):
            if normalize(syn) in n:
                return key

    # sell_out — явно (ищем раньше sell_in, чтобы "sell out" не матчил "sell")
    for syn in CHANNEL_SYNONYMS['sell_out']:
        if normalize(syn) in n:
            return 'sell_out'

    # sell_in / dist_sell_in — разрешаем по контексту модуля
    sell_in_hit = any(normalize(s) in n for s in CHANNEL_SYNONYMS['sell_in'])
    if sell_in_hit:
        if current_module == 'distributor_data':
            return 'dist_sell_in'
        return 'sell_in'  # по умолчанию — аптечный

    # stock / dist_stock — разрешаем по контексту
    stock_hit = any(normalize(s) in n for s in CHANNEL_SYNONYMS['stock'])
    if stock_hit:
        if current_module == 'distributor_data':
            return 'dist_stock'
        return 'stock'

    return None


def extract_module(text: str) -> Optional[str]:
    """Извлекает модуль из текста."""
    n = normalize(text)
    for key, synonyms in MODULE_SYNONYMS.items():
        for syn in synonyms:
            if normalize(syn) in n:
                return key
    return None


def extract_analysis(text: str) -> Optional[str]:
    """Извлекает тип анализа из текста."""
    n = normalize(text)
    for key, synonyms in ANALYSIS_SYNONYMS.items():
        for syn in synonyms:
            if normalize(syn) in n:
                return key
    return None


# Слова-маркеры «общего» вопроса (намерение посмотреть/получить данные без канала)
_GENERIC_WORDS = [
    # Отчёты и выгрузка
    'выгрузить', 'выгрузка', 'выгружать', 'экспорт', 'скачать',
    'отчет', 'отчёт', 'построить отчет', 'создать отчет',
    'как сделать', 'как выгрузить', 'как создать', 'как построить',
    # Просмотр данных
    'посмотреть', 'увидеть', 'просмотреть', 'показать', 'найти',
    'как посмотреть', 'как увидеть', 'как найти', 'как получить',
    'хочу посмотреть', 'хочу увидеть', 'хочу получить',
    'хочу знать', 'хочу данные',
    # Аналитические запросы
    'топ ', 'рейтинг', 'лучшие', 'худшие', 'первые по',
    'как я могу', 'как мне', 'могу ли', 'можно ли',
    'анализ продаж', 'данные по', 'статистика', 'в разрезе',
    'прирост', 'динамика', 'сравнить', 'план и факт', 'доля',
]

# Слова определительных/общих вопросов о системе — НЕ нуждаются в уточнении канала
_DEFINITION_WORDS = [
    'что такое', 'что означает', 'что это', 'что значит',
    'для чего', 'зачем нужен', 'зачем нужна',
    'объясни', 'объясните', 'расскажи', 'расскажите',
    'чем отличается', 'разница между', 'почему',
    'какие модули', 'какие каналы', 'какие функции',
]

def _is_generic_question(text: str) -> bool:
    """True если вопрос о доступе к данным/анализу без указания канала.
    Исключает вопросы о входе и определительные вопросы.
    """
    n = normalize(text)
    # Исключаем логин-вопросы
    if any(normalize(s) in n for s in ANALYSIS_SYNONYMS.get('login', [])):
        return False
    # Исключаем определительные вопросы («что такое», «расскажи» и т.п.)
    if any(normalize(w) in n for w in _DEFINITION_WORDS):
        return False
    return any(normalize(w) in n for w in _GENERIC_WORDS)


def _last_bot_was_clarifying() -> bool:
    """True если последнее сообщение бота было запросом уточнения."""
    conv = getattr(st.session_state, 'conversation', [])
    for msg in reversed(conv):
        if msg['role'] == 'assistant':
            c = msg['content'].lower()
            return any(w in c for w in ['уточните', 'какой модуль', 'какой канал',
                                        'какие данные', 'пожалуйста, уточните',
                                        'аптечные данные или', 'присутствует в обоих'])
    return False


def needs_clarification(text: str, context: Dict[str, Any]) -> Optional[str]:
    """
    Возвращает строку с вопросом для уточнения, если контекст недостаточен.
    Возвращает None, если всё понятно.
    """
    n = normalize(text)

    # Вопрос о входе/личном кабинете — никогда не требует уточнения, пропускаем
    login_hit = any(normalize(s) in n for s in ANALYSIS_SYNONYMS.get('login', []))
    if login_hit:
        return None

    # Определительный вопрос («что такое», «расскажи» и т.п.) — не требует уточнения канала,
    # LLM сам объяснит понятие в общем виде
    definition_hit = any(normalize(w) in n for w in _DEFINITION_WORDS)
    if definition_hit:
        return None

    # Упомянут sell_in / остатки без контекста модуля — оба канала есть в обоих модулях
    sell_in_hit = any(normalize(s) in n for s in CHANNEL_SYNONYMS['sell_in'])
    stock_hit   = any(normalize(s) in n for s in CHANNEL_SYNONYMS['stock'])
    ambiguous   = (sell_in_hit or stock_hit) and not context.get('module')

    # Упомянут явный канал без модуля — не запрашиваем уточнение если канал однозначен
    # (однозначные каналы автоматически привязываются к модулю в process_question)

    # Вопрос о «отчёте» или «анализе» без модуля и канала
    generic_report = (
        any(w in n for w in ['отчет', 'отчёт', 'report', 'создать', 'построить'])
        and not context.get('module')
        and not context.get('channel')
    )

    if ambiguous:
        channel_word = 'Sell In' if sell_in_hit else 'Остатки'
        return (
            f'Канал «{channel_word}» присутствует в обоих модулях. Уточните, пожалуйста:\n\n'
            '— **Аптечные данные** — закупки/остатки аптечных сетей\n'
            '— **Данные дистрибьютора** — закупки/склады дистрибьютора'
        )
    if generic_report:
        return (
            'Уточните, пожалуйста:\n\n'
            '— Какой **модуль**? Аптечные данные или Данные дистрибьютора?\n'
            '— Какой **канал**? (Sell Out, Sell In, Перемещение, Остатки, E-com, Тендер, Импорт...)'
        )
    # Общий вопрос без канала и модуля (передан через clarify_ctx с обнулённым контекстом)
    if not context.get('module') and not context.get('channel'):
        n_local = normalize(text)
        if any(normalize(w) in n_local for w in _GENERIC_WORDS):
            return (
                'Уточните, пожалуйста:\n\n'
                '— Какой **модуль**?\n'
                '  - **Аптечные данные** (Sell Out, Sell In, E-com, Перемещение, Остатки)\n'
                '  - **Данные дистрибьютора** (Sell In, Sell In+Tender, Tender, Импорт, Остатки)\n\n'
                '— Какой **канал** вас интересует?'
            )
    return None

# =============================================================================
# ФАЙЛЫ И ИСТОРИЯ
# =============================================================================

def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def log_entry(entry: Dict[str, Any]) -> None:
    try:
        ensure_dirs()
        with LOG_FILE.open('a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        pass  # логирование не должно ронять приложение


def load_history() -> List[Dict[str, Any]]:
    ensure_dirs()
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding='utf-8'))
        except Exception:
            return []
    return []


def save_history(history: List[Dict[str, Any]]) -> None:
    ensure_dirs()
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding='utf-8')


def init_session() -> None:
    if 'conversation' not in st.session_state:
        st.session_state.conversation = []
    if 'context' not in st.session_state:
        # module здесь None — устанавливается ТОЛЬКО из ключевых слов чата или быстрых кнопок
        st.session_state.context = {
            'module':        None,
            'channel':       None,
            'analysis_type': None,
        }
    if 'corpus' not in st.session_state:
        st.session_state.corpus = None
    if 'pending_input' not in st.session_state:
        st.session_state.pending_input = None
    if 'sidebar_module' not in st.session_state:
        st.session_state.sidebar_module = 'pharmacy_data'

# =============================================================================
# ЗАГРУЗКА БАЗЫ ЗНАНИЙ
# =============================================================================

try:
    from docx import Document as DocxDocument
except ImportError:
    DocxDocument = None

try:
    from pypdf import PdfReader
except ImportError:
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        PdfReader = None


def _read_docx(path: Path) -> str:
    if DocxDocument is None:
        return ''
    try:
        doc = DocxDocument(path)
        return '\n'.join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception:
        return ''


def _read_pdf(path: Path) -> str:
    if PdfReader is None:
        return ''
    try:
        reader = PdfReader(path)
        return '\n'.join(
            (page.extract_text() or '').strip()
            for page in reader.pages
        )
    except Exception:
        return ''


def _read_md(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8')
    except Exception:
        return ''


def load_kb_documents() -> List[Dict[str, str]]:
    docs: List[Dict[str, str]] = []
    for path in KB_FILES:
        if not path.exists():
            continue
        ext = path.suffix.lower()
        if ext == '.docx':
            text = _read_docx(path)
        elif ext == '.pdf':
            text = _read_pdf(path)
        elif ext == '.md':
            text = _read_md(path)
        else:
            continue
        if text.strip():
            docs.append({'source': path.name, 'text': text})
    if not docs:
        raise FileNotFoundError('Документы базы знаний не найдены. Убедитесь, что файлы в корне проекта.')
    return docs


def split_text(text: str, max_len: int = 900) -> List[str]:
    """Разбивает текст на перекрывающиеся фрагменты для embeddings."""
    text = text.replace('\r', '')
    paragraphs = [p.strip() for p in re.split(r'\n{2,}', text) if p.strip()]
    chunks: List[str] = []
    current: List[str] = []
    cur_len = 0

    for para in paragraphs:
        if len(para) > max_len:
            if current:
                chunks.append('\n\n'.join(current))
                current, cur_len = [], 0
            for i in range(0, len(para), max_len):
                chunks.append(para[i:i + max_len].strip())
            continue
        if cur_len + len(para) + 2 <= max_len:
            current.append(para)
            cur_len += len(para) + 2
        else:
            if current:
                chunks.append('\n\n'.join(current))
            current, cur_len = [para], len(para)

    if current:
        chunks.append('\n\n'.join(current))
    return chunks


def build_corpus(documents: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    corpus: List[Dict[str, Any]] = []
    for doc in documents:
        for idx, chunk in enumerate(split_text(doc['text']), 1):
            corpus.append({'id': f"{doc['source']}#{idx}", 'source': doc['source'], 'text': chunk})
    return corpus

# =============================================================================
# EMBEDDINGS И ПОИСК
# =============================================================================

def get_embeddings(texts: List[str], api_key: str) -> List[List[float]]:
    resp = requests.post(
        OPENAI_EMBEDDING_URL,
        json={'model': EMBEDDING_MODEL, 'input': texts},
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(f'Embeddings API {resp.status_code}: {resp.text[:300]}')
    return [item['embedding'] for item in resp.json().get('data', [])]


def cosine(a: List[float], b: List[float]) -> float:
    dot  = sum(x * y for x, y in zip(a, b))
    na   = math.sqrt(sum(x * x for x in a))
    nb   = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def get_relevant_chunks(
    question: str,
    corpus: List[Dict[str, Any]],
    api_key: str,
    top_k: int = 6,
    ctx_module: Optional[str] = None,
    ctx_channel: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if not corpus:
        return []

    q_emb = get_embeddings([question.lower()], api_key)[0]
    texts  = [item['text'] for item in corpus]
    c_embs = get_embeddings(texts, api_key)

    for item, emb in zip(corpus, c_embs):
        score = cosine(q_emb, emb)
        tl = item['text'].lower()

        # Бонус за совпадение с контекстом
        if ctx_module == 'pharmacy_data' and any(w in tl for w in ['аптечные', 'аптека', 'sell out', 'sell_out']):
            score *= 1.2
        if ctx_module == 'distributor_data' and any(w in tl for w in ['дистрибьютор', 'тендер', 'импорт']):
            score *= 1.2
        if ctx_channel:
            key_words = ctx_channel.replace('_', ' ')
            if key_words in tl:
                score *= 1.25

        item['score'] = score

    ranked = sorted(corpus, key=lambda x: x.get('score', 0), reverse=True)
    return [c for c in ranked[:top_k] if c.get('score', 0) >= RELEVANCE_THRESHOLD]

# =============================================================================
# SYSTEM PROMPT И OPENAI
# =============================================================================

def build_system_prompt(context: Dict[str, Any]) -> str:
    ctx_lines = []
    if context.get('module'):
        ctx_lines.append(f"Текущий модуль пользователя: **{MODULE_DISPLAY.get(context['module'], context['module'])}**")
    if context.get('channel'):
        ctx_lines.append(f"Текущий канал пользователя: **{CHANNEL_DISPLAY.get(context['channel'], context['channel'])}**")
    if context.get('analysis_type'):
        ctx_lines.append(f"Тип анализа: **{context['analysis_type']}**")
    ctx_block = ('\n'.join(ctx_lines) + '\n\n') if ctx_lines else ''

    return f"""Ты — AI-ассистент системы PhaDataPro (Pharmacy Data Processing), разработанной компанией Viortis.
Твоя задача: помогать пользователям работать с аналитической платформой PhaDataPro.

{ctx_block}ПРАВИЛА:
1. Отвечай ТОЛЬКО на русском языке.
2. Помогай только по вопросам PhaDataPro.
3. Давай ПОШАГОВЫЕ инструкции с нумерацией (1. 2. 3.).
4. Используй точные названия кнопок и полей интерфейса, выделяй их жирным.
5. Если контекст модуля/канала уже известен (см. выше) — используй его, не переспрашивай.
6. Если вопрос неясен — уточни конкретно: модуль? канал? тип анализа?
7. Если вопрос не про PhaDataPro — вежливо откажи: «Это выходит за пределы моей компетенции.»

ОБЯЗАТЕЛЬНЫЕ НАПОМИНАНИЯ В КАЖДОМ ОТВЕТЕ ПО ОТЧЁТАМ:
Когда даёшь инструкцию по построению отчёта или анализу — ОБЯЗАТЕЛЬНО напоминай в самом ответе:
- ⚠️ **Период** — обязательный шаг, без него данные не загрузятся. Всегда выделяй его отдельным пунктом.
- Напоминай выбрать нужные **Фильтры** (Регион, Аптечная сеть, Бренд, Менеджер и т.д.) — объясни какие фильтры актуальны для конкретного запроса.
- Напоминай выбрать нужные **Блоки** (столбцы отчёта: Упаковки, Сумма, Доля, % плана и т.д.) — объясни какие блоки нужны для конкретного анализа.
Эти напоминания должны быть частью пошаговой инструкции, а не отдельной припиской.

ПОДДЕРЖИВАЕМЫЕ МОДУЛИ:
— АПТЕЧНЫЕ ДАННЫЕ: Sell Out, Sell In, Sell Out + E-com, Перемещение, Остатки, E-com
— ДАННЫЕ ДИСТРИБЬЮТОРА: Sell In, Sell In + Tender, Tender, Остатки, Импорт

ВАЖНО: Каналы «Sell In» и «Остатки» есть в ОБОИХ модулях. Если модуль не ясен — уточни.
Синонимы: «сел ин» = «селл ин» = «sell in» = «закупки»; «тендер» = «госзакупка»; «импорт» = «ввоз» и т.д.

НЕРАСПОЗНАННЫЕ ТЕРМИНЫ:
Если пользователь называет модуль или канал, которого нет в системе (например «гео», «geo», «лок», «регион» как модуль и т.п.) — НЕ угадывай. Ответь:
«В системе PhaDataPro нет модуля/канала с таким названием. Доступные модули: **Аптечные данные** и **Данные дистрибьютора**. Уточните, что именно вас интересует?»

ВХОД / ЛИЧНЫЙ КАБИНЕТ:
Если пользователь спрашивает «как зайти», «личный кабинет», «войти в систему» и т.п. — давай инструкцию входа: сайт https://pdp.viortis.kz/ → Email → Пароль → SIGN IN."""


def ask_openai(messages: List[Dict[str, str]], api_key: str) -> str:
    resp = requests.post(
        OPENAI_COMPLETION_URL,
        json={'model': COMPLETION_MODEL, 'max_tokens': MAX_TOKENS, 'messages': messages, 'temperature': 0.6},
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        timeout=90,
    )
    if resp.status_code == 401:
        return '❌ Неверный API ключ. Проверьте значение OPENAI_API_KEY в Streamlit Secrets.'
    if resp.status_code == 429:
        return '⏱️ Превышен лимит запросов OpenAI. Подождите немного и повторите.'
    if resp.status_code != 200:
        return f'❌ Ошибка API (код {resp.status_code}). Попробуйте снова.'
    choices = resp.json().get('choices', [])
    if not choices:
        return '❌ Пустой ответ от сервера.'
    return choices[0].get('message', {}).get('content', '').strip()


def build_messages(
    system_prompt: str,
    conversation: List[Dict[str, Any]],
    question: str,
    chunks: List[Dict[str, Any]],
    context: Dict[str, Any],
) -> List[Dict[str, str]]:
    kb_text = '\n\n---\n\n'.join(
        f"[Источник: {c['source']}]\n{c['text']}" for c in chunks
    ) if chunks else 'Контекст из базы знаний не найден.'

    ctx_reminder = []
    if context.get('module'):
        ctx_reminder.append(f"Модуль: {MODULE_DISPLAY.get(context['module'], context['module'])}")
    if context.get('channel'):
        ctx_reminder.append(f"Канал: {CHANNEL_DISPLAY.get(context['channel'], context['channel'])}")

    user_msg = (
        ('Контекст сессии: ' + ', '.join(ctx_reminder) + '\n\n' if ctx_reminder else '') +
        f'МАТЕРИАЛЫ ИЗ БАЗЫ ЗНАНИЙ:\n{kb_text}\n\n'
        f'ВОПРОС ПОЛЬЗОВАТЕЛЯ: {question}\n\n'
        'Ответь пошагово на русском языке. '
        'Если это вопрос о построении отчёта или анализе — дай полную пошаговую инструкцию и '
        'ОБЯЗАТЕЛЬНО включи в неё отдельными пунктами: '
        '(а) выбор Периода с пометкой что он обязателен, '
        '(б) выбор нужных Фильтров — укажи конкретно какие фильтры актуальны, '
        '(в) выбор нужных Блоков — укажи конкретно какие блоки нужны для этого анализа. '
        'Если информации нет в материалах — скажи об этом и попроси уточнить.'
    )

    msgs: List[Dict[str, str]] = [{'role': 'system', 'content': system_prompt}]
    for entry in conversation[-8:]:
        msgs.append({'role': entry['role'], 'content': entry['content']})
    msgs.append({'role': 'user', 'content': user_msg})
    return msgs

# =============================================================================
# UI КОМПОНЕНТЫ
# =============================================================================

def apply_styles() -> None:
    st.markdown('''<style>
        .stChatMessage { border-radius: 12px; }
        .context-badge {
            display: inline-block;
            background: #1D9E75;
            color: white;
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 13px;
            margin: 2px 4px;
        }
    </style>''', unsafe_allow_html=True)


def render_context_badge(context: Dict[str, Any]) -> None:
    parts = []
    if context.get('module'):
        parts.append(MODULE_DISPLAY.get(context['module'], context['module']))
    if context.get('channel'):
        parts.append(CHANNEL_DISPLAY.get(context['channel'], context['channel']))
    if parts:
        badges = ''.join(f'<span class="context-badge">{p}</span>' for p in parts)
        st.markdown(f'Контекст сессии: {badges}', unsafe_allow_html=True)


def quick_buttons() -> Optional[str]:
    """Рендерит быстрые кнопки и возвращает выбранный вопрос (или None)."""
    module = st.session_state.get('sidebar_module', 'pharmacy_data')

    if module == 'pharmacy_data':
        questions = [
            'Как создать отчёт Sell Out?',
            'Как работает Sell In аптечных данных?',
            'Как сделать Sell Out + E-com?',
            'Как посмотреть остатки товара?',
            'Как сравнить план и факт продаж?',
            'Как проанализировать прирост продаж?',
            'Как сделать категоризацию аптек?',
            'Как войти в систему?',
        ]
    else:
        questions = [
            'Как создать отчёт Sell In дистрибьютора?',
            'Что такое Tender (тендер)?',
            'Как работает Sell In + Tender?',
            'Как посмотреть Импорт?',
            'Как посмотреть остатки дистрибьютора?',
            'Как сравнить план и факт?',
            'Как войти в систему?',
        ]

    st.markdown('**Быстрые вопросы:**')
    cols = st.columns(4)
    for i, q in enumerate(questions):
        if cols[i % 4].button(q, key=f'quick_{i}', use_container_width=True):
            return q
    return None

# =============================================================================
# ОБРАБОТКА ВОПРОСА
# =============================================================================

def process_question(question: str, force_module: Optional[str] = None) -> None:
    """Основная логика: извлечение контекста → поиск → ответ.

    force_module используется быстрыми кнопками, чтобы явно задать модуль
    (sidebar_module) не полагаясь на ключевые слова.
    """
    api_key = OPENAI_API_KEY
    ctx = st.session_state.context

    # Если модуль передан принудительно (быстрая кнопка) — устанавливаем
    if force_module:
        ctx['module'] = force_module

    # Обновляем контекст из ключевых слов вопроса
    mod = extract_module(question)
    if mod:
        ctx['module'] = mod

    ch = extract_channel(question, ctx.get('module'))
    if ch:
        ctx['channel'] = ch
        # Если канал однозначно привязан к модулю и модуль ещё не задан — выводим
        if ch in CHANNEL_MODULE_MAP and not ctx.get('module'):
            ctx['module'] = CHANNEL_MODULE_MAP[ch]

    at = extract_analysis(question)
    if at:
        ctx['analysis_type'] = at

    # Добавляем вопрос в историю
    ts = datetime.now().strftime('%H:%M:%S')
    st.session_state.conversation.append({'role': 'user', 'content': question, 'timestamp': ts})

    # Определяем, нужно ли уточнение.
    # Если вопрос «общий» (нет канала/модуля в текущем сообщении) И бот не спрашивал
    # уточнение последним → не наследуем старый контекст, заставляем уточнить.
    ch_in_msg  = extract_channel(question, None)   # только из текущего текста
    mod_in_msg = extract_module(question)
    answering_clarification = _last_bot_was_clarifying()

    if _is_generic_question(question) and not ch_in_msg and not mod_in_msg and not answering_clarification:
        # Спрашиваем, какой именно канал/модуль имеет в виду пользователь
        clarify_ctx: Dict[str, Any] = {'module': None, 'channel': None}
    else:
        clarify_ctx = ctx

    clarify = needs_clarification(question, clarify_ctx)
    if clarify:
        answer = f'Пожалуйста, уточните:\n\n{clarify}'
        st.session_state.conversation.append({'role': 'assistant', 'content': answer, 'timestamp': ts})
        save_history(st.session_state.conversation)
        return

    # Поиск в базе знаний
    try:
        chunks = get_relevant_chunks(
            question, st.session_state.corpus, api_key,
            ctx_module=ctx.get('module'), ctx_channel=ctx.get('channel'),
        )
    except Exception as e:
        chunks = []
        st.warning(f'Поиск в базе знаний недоступен: {e}')

    # Запрос к OpenAI
    system_prompt = build_system_prompt(ctx)
    messages = build_messages(
        system_prompt,
        st.session_state.conversation[:-1],
        question, chunks, ctx,
    )

    try:
        answer = ask_openai(messages, api_key)
    except Exception as e:
        answer = f'❌ Ошибка при обращении к OpenAI: {e}'

    ts2 = datetime.now().strftime('%H:%M:%S')
    st.session_state.conversation.append({'role': 'assistant', 'content': answer, 'timestamp': ts2})

    log_entry({
        'timestamp': datetime.now().isoformat(),
        'user_input': question,
        'context': ctx,
        'response': answer,
        'sources': [c['source'] for c in chunks],
    })
    save_history(st.session_state.conversation)

# =============================================================================
# ГЛАВНОЕ ПРИЛОЖЕНИЕ
# =============================================================================

def main() -> None:
    if not OPENAI_API_KEY:
        st.error(
            "⚠️ **OPENAI_API_KEY не найден.**\n\n"
            "**Streamlit Cloud:** App settings → Secrets → добавьте:\n"
            "```\nOPENAI_API_KEY = \"your_openai_api_key_here\"\n```\n\n"
            "**Локально:** создайте файл `.streamlit/secrets.toml` со строкой:\n"
            "```\nOPENAI_API_KEY = \"your_openai_api_key_here\"\n```"
        )
        st.stop()

    init_session()

    st.set_page_config(
        page_title='PhaDataPro AI',
        page_icon='🏥',
        layout='wide',
        initial_sidebar_state='expanded',
    )
    apply_styles()

    # ── Заголовок ──────────────────────────────────────────────────────────────
    col_title, col_new, col_status = st.columns([4, 1, 1])
    with col_title:
        st.markdown('# 🏥 PhaDataPro AI Ассистент')
    with col_new:
        st.markdown('<br>', unsafe_allow_html=True)
        if st.button('✏️ Новый чат', use_container_width=True, type='primary'):
            st.session_state.conversation = []
            st.session_state.context = {'module': None, 'channel': None, 'analysis_type': None}
            st.rerun()
    with col_status:
        st.markdown('<br><span style="background:#1D9E75;color:white;padding:6px 14px;border-radius:20px;font-size:13px">🟢 ОНЛАЙН</span>', unsafe_allow_html=True)
    st.markdown('---')

    # ── Боковая панель ─────────────────────────────────────────────────────────
    with st.sidebar:
        st.subheader('📦 Выберите модуль')
        st.caption('Определяет набор быстрых вопросов. Контекст чата обновляется автоматически по ключевым словам.')

        sidebar_module = st.radio(
            'Модуль',
            options=['pharmacy_data', 'distributor_data'],
            format_func=lambda x: MODULE_DISPLAY[x],
            index=0 if st.session_state.sidebar_module != 'distributor_data' else 1,
            key='_sidebar_module_radio',
            label_visibility='collapsed',
        )
        st.session_state.sidebar_module = sidebar_module

        st.markdown('---')
        if st.button('✏️ Новый чат', use_container_width=True, type='primary'):
            st.session_state.conversation = []
            st.session_state.context = {'module': None, 'channel': None, 'analysis_type': None}
            st.rerun()

        if st.button('🗑️ Очистить и сохранить историю', use_container_width=True):
            save_history(st.session_state.conversation)
            st.session_state.conversation = []
            st.session_state.context = {'module': None, 'channel': None, 'analysis_type': None}
            st.success('История сохранена')
            st.rerun()

        if st.button('💾 Загрузить историю из файла', use_container_width=True):
            loaded = load_history()
            if loaded:
                st.session_state.conversation = loaded
                st.success(f'Загружено {len(loaded)} сообщений')
                st.rerun()
            else:
                st.info('История пуста или файл не найден')

    # ── Основная область ───────────────────────────────────────────────────────

    # Загрузка корпуса (один раз)
    if st.session_state.corpus is None:
        with st.spinner('📚 Загружаю базу знаний...'):
            try:
                docs = load_kb_documents()
                st.session_state.corpus = build_corpus(docs)
                st.success(f'✅ База знаний загружена: {len(st.session_state.corpus)} фрагментов из {len(docs)} документов')
            except Exception as e:
                st.error(f'❌ {e}')
                return

    # Бейджи контекста
    render_context_badge(st.session_state.context)

    # ── История чата ───────────────────────────────────────────────────────────
    for msg in st.session_state.conversation:
        with st.chat_message(msg['role']):
            st.markdown(msg['content'])
            if msg.get('timestamp'):
                st.caption(msg['timestamp'])

    # ── Быстрые кнопки ─────────────────────────────────────────────────────────
    with st.expander('💡 Быстрые вопросы', expanded=len(st.session_state.conversation) == 0):
        quick = quick_buttons()
        if quick:
            # Быстрая кнопка явно несёт модуль из sidebar — сохраняем его
            st.session_state.pending_input = quick
            st.session_state.pending_module = st.session_state.sidebar_module
            st.rerun()

    # ── Ввод вопроса ───────────────────────────────────────────────────────────
    user_input = st.chat_input('Введите ваш вопрос о PhaDataPro...')

    # Обрабатываем либо ввод пользователя, либо нажатую быструю кнопку
    question_to_process: Optional[str] = None
    force_mod: Optional[str] = None

    if user_input and user_input.strip():
        question_to_process = user_input.strip()
    elif st.session_state.pending_input:
        question_to_process = st.session_state.pending_input
        force_mod = st.session_state.pop('pending_module', None)
        st.session_state.pending_input = None

    if question_to_process:
        with st.spinner('💭 Ищу ответ...'):
            process_question(question_to_process, force_module=force_mod)
        st.rerun()


if __name__ == '__main__':
    main()
