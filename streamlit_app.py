from __future__ import annotations
# PhaDataPro AI Чат-бот v3

import json
import math
import os
import re
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import streamlit as st

# =============================================================================
# КОНФИГУРАЦИЯ
# =============================================================================

_BASE = Path(__file__).parent

DATA_DIR     = _BASE / 'data'
LOG_DIR      = _BASE / 'logs'
HISTORY_FILE = DATA_DIR / 'chat_history.json'
LOG_FILE     = LOG_DIR  / 'chat_history.log'

KB_FILES = [
    _BASE / 'modules_guide.md',
    _BASE / 'prompt.md',
    _BASE / 'ТЗ PDP ИИ.docx',
    _BASE / 'Вопросы для ИИ маршрутизатор.docx',
    _BASE / 'Инструкция для пользователей PhaDataPro (1).pdf',
]

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

COMPLETION_MODEL    = 'gpt-4o'
NORMALIZATION_MODEL = 'gpt-4o-mini'
EMBEDDING_MODEL     = 'text-embedding-3-small'
MAX_TOKENS          = 2000
NORM_MAX_TOKENS     = 500
RELEVANCE_THRESHOLD = 0.12

# =============================================================================
# КОНТАКТЫ ТЕХНИЧЕСКИХ МЕНЕДЖЕРОВ
# =============================================================================

TECH_MANAGERS_BLOCK = """\
**Технические менеджеры Viortis:**
- **Ардакулы Арсен**: techmanager04@viortis.kz | +7 708 218 10 53
- **Хисматулина Тахмина**: techmanager07@viortis.kz | +7 708 268 80 17"""

CONTACT_ANSWER = f"""\
Для связи с техническим менеджером:

{TECH_MANAGERS_BLOCK}

Они помогут с любыми техническими вопросами по системе PhaDataPro."""

FALLBACK_SUFFIX = f"""\

---
💬 **Нужна дополнительная помощь?** Обратитесь к техническому менеджеру:
{TECH_MANAGERS_BLOCK}"""

# =============================================================================
# АУТЕНТИФИКАЦИЯ
# =============================================================================

def _load_credentials() -> Dict[str, Dict[str, str]]:
    """
    Загружает логины/пароли ТОЛЬКО из st.secrets → секция [auth].
    Если секция не настроена — возвращает пустой словарь;
    main() покажет понятную ошибку в UI без раскрытия секретов.
    """
    creds: Dict[str, Dict[str, str]] = {}
    try:
        auth = st.secrets.get("auth", {})
        if not auth:
            return creds
        admin_login    = str(auth.get("admin_login", "admin")).strip()
        admin_password = str(auth.get("admin_password", "")).strip()
        if admin_login and admin_password:
            creds[admin_login] = {"password": admin_password, "role": "admin"}
        i = 1
        while f"user{i}_login" in auth:
            login    = str(auth.get(f"user{i}_login",    "")).strip()
            password = str(auth.get(f"user{i}_password", "")).strip()
            if login and password:
                creds[login] = {"password": password, "role": "user"}
            i += 1
    except Exception:
        pass
    return creds


def render_login_page() -> None:
    """Страница входа."""
    st.markdown("""
    <style>
      section[data-testid="stSidebar"] { display: none; }
      .block-container { max-width: 420px !important; padding-top: 3rem; }
    </style>""", unsafe_allow_html=True)

    st.markdown('<div style="text-align:center;font-size:3rem">🏥</div>', unsafe_allow_html=True)
    st.markdown('<h1 style="text-align:center">PhaDataPro AI</h1>', unsafe_allow_html=True)
    st.markdown('<p style="text-align:center;color:#666">Аналитический ассистент</p>', unsafe_allow_html=True)
    st.markdown('---')

    with st.form('login_form', clear_on_submit=False):
        login    = st.text_input('Логин', placeholder='Введите логин')
        password = st.text_input('Пароль', type='password', placeholder='Введите пароль')
        submit   = st.form_submit_button('Войти', use_container_width=True, type='primary')

    if submit:
        creds = _load_credentials()
        if not creds:
            st.error(
                '⚠️ **Авторизация не настроена.**\n\n'
                'Добавьте секцию `[auth]` в Streamlit Cloud Secrets '
                '(или в `.streamlit/secrets.toml` локально). '
                'Смотрите `.streamlit/secrets.toml.example` для примера.'
            )
        elif login in creds and creds[login]['password'] == password:
            st.session_state.logged_in  = True
            st.session_state.username   = login
            st.session_state.user_role  = creds[login]['role']
            st.session_state.session_id = str(uuid.uuid4())[:8]
            _log_system_event('session_start')
            st.rerun()
        else:
            st.error('❌ Неверный логин или пароль')

# =============================================================================
# СИНОНИМЫ КАНАЛОВ, МОДУЛЕЙ, АНАЛИЗОВ
# =============================================================================

CHANNEL_SYNONYMS: Dict[str, List[str]] = {
    'sell_out': [
        'sell out', 'sell-out', 'sellout', 'sel out', 'sel-out',
        'сел аут', 'сел-аут', 'селл аут', 'селл-аут', 'сэлл аут', 'сэл аут',
        'розничные продажи', 'розница', 'ретейл', 'retail',
        'аптечные продажи', 'продажи в аптеках',
    ],
    'sell_in': [
        'sell in', 'sell-in', 'sellin', 'sel in', 'sel-in',
        'сел ин', 'сел-ин', 'селл ин', 'селл-ин', 'сэлл ин', 'сэл ин',
        'закупки', 'оптовые продажи', 'оптовая', 'опт',
        'закупки аптек', 'входящие закупки',
    ],
    'sell_out_ecom': [
        'sell out + e-com', 'sell out + ecom', 'sell out ecom',
        'sell out e com', 'sell out e-com', 'sel out ecom',
        'аут + ком', 'аут+ком', 'розница + онлайн', 'розница+онлайн',
    ],
    'placement': [
        'перемещение', 'движение', 'movement', 'transfer',
        'логистика', 'перемещение товара', 'передача товара',
    ],
    'stock': [
        'остатки', 'остаток', 'stock', 'наличие', 'запасы',
        'inventory', 'товарные остатки', 'складские остатки',
    ],
    'ecom': [
        'e-com', 'ecom', 'e-commerce', 'ecommerce', 'е-ком', 'еком',
        'электронная коммерция', 'онлайн', 'интернет-аптека',
        'онлайн продажи', 'интернет продажи',
    ],
    'sell_in_tender': [
        'sell in + tender', 'sell in tender', 'sellin tender',
        'сел ин + тендер', 'сел ин тендер',
        'закупки + тендер', 'закупки с тендером', 'тендерные закупки',
    ],
    'tender': [
        'tender', 'тендер', 'госзакупка', 'государственная закупка',
        'гос закупка', 'гос. закупка',
    ],
    'import_channel': [
        'импорт', 'import', 'ввоз', 'иностранный товар', 'таможня',
    ],
    'dist_stock': [
        'остатки дистрибьютора', 'складские остатки дистрибьютора',
        'наличие у дистрибьютора', 'склад дистрибьютора',
    ],
}

MODULE_SYNONYMS: Dict[str, List[str]] = {
    'pharmacy_data': [
        'аптечные данные', 'аптечные', 'аптека', 'аптечный',
        'pharmacy data', 'pharmacy', 'розничный', 'ас', 'аптечная сеть',
    ],
    'distributor_data': [
        'данные дистрибьютора', 'дистрибьютор', 'дистрибьюторские данные',
        'distributor data', 'distributor', 'дс', 'дистр', 'оптовик',
    ],
}

ANALYSIS_SYNONYMS: Dict[str, List[str]] = {
    'sales_breakdown': [
        'анализ продаж в разрезе', 'продажи по регионам',
        'разрез', 'в разрезе', 'детализация продаж',
    ],
    'plan_vs_fact': [
        'сравнение плана с фактом', 'план факт', 'plan vs fact',
        'выполнение плана', 'план и факт', 'план-факт',
    ],
    'percent_plan': [
        'процент выполнения плана', '% выполнения', 'процент плана',
    ],
    'growth': [
        'прирост продаж', 'growth', 'динамика', 'темп роста',
        'рост продаж', 'прирост', 'изменение продаж',
    ],
    'share': [
        'доля товара', 'доля рынка', 'share', 'market share',
        'рыночная доля', 'доля продаж',
    ],
    'high_potential': [
        'высокопотенциальные точки', 'категория спа', 'спа',
        'потенциальные точки',
    ],
    'categorization': [
        'категоризация аптек', 'abc анализ', 'abc-анализ',
        'сегментация аптек', 'классификация аптек',
    ],
    'login': [
        'личный кабинет', 'войти', 'войти в систему', 'вход в систему',
        'как зайти', 'как войти', 'авторизация',
        'sign in', 'signin', 'зайти в систему',
    ],
}

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
}

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

PHARMACY_CHANNELS    = ['sell_out', 'sell_in', 'sell_out_ecom', 'placement', 'stock', 'ecom']
DISTRIBUTOR_CHANNELS = ['dist_sell_in', 'sell_in_tender', 'tender', 'dist_stock', 'import_channel']

# =============================================================================
# НОРМАЛИЗАЦИЯ (keyword-based)
# =============================================================================

def normalize(text: str) -> str:
    text = text.lower().strip()
    text = unicodedata.normalize('NFKD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def extract_channel(text: str, current_module: Optional[str] = None) -> Optional[str]:
    n = normalize(text)
    unambiguous = ['sell_out_ecom', 'placement', 'ecom', 'sell_in_tender', 'tender', 'import_channel', 'dist_stock']
    for key in unambiguous:
        for syn in CHANNEL_SYNONYMS.get(key, []):
            if normalize(syn) in n:
                return key
    for syn in CHANNEL_SYNONYMS['sell_out']:
        if normalize(syn) in n:
            return 'sell_out'
    sell_in_hit = any(normalize(s) in n for s in CHANNEL_SYNONYMS['sell_in'])
    if sell_in_hit:
        return 'dist_sell_in' if current_module == 'distributor_data' else 'sell_in'
    stock_hit = any(normalize(s) in n for s in CHANNEL_SYNONYMS['stock'])
    if stock_hit:
        return 'dist_stock' if current_module == 'distributor_data' else 'stock'
    return None


def extract_module(text: str) -> Optional[str]:
    n = normalize(text)
    for key, synonyms in MODULE_SYNONYMS.items():
        for syn in synonyms:
            if normalize(syn) in n:
                return key
    return None


def extract_analysis(text: str) -> Optional[str]:
    n = normalize(text)
    for key, synonyms in ANALYSIS_SYNONYMS.items():
        for syn in synonyms:
            if normalize(syn) in n:
                return key
    return None


_GENERIC_WORDS = [
    'выгрузить', 'выгрузка', 'экспорт', 'скачать',
    'отчет', 'отчёт', 'построить отчет', 'создать отчет',
    'как сделать', 'как выгрузить', 'как создать', 'как построить',
    'посмотреть', 'увидеть', 'просмотреть', 'показать', 'найти',
    'как посмотреть', 'как увидеть', 'как найти', 'как получить',
    'хочу посмотреть', 'хочу данные',
    'топ ', 'рейтинг', 'лучшие', 'худшие',
    'анализ продаж', 'данные по', 'статистика', 'в разрезе',
    'прирост', 'динамика', 'сравнить', 'план и факт', 'доля',
]

_DEFINITION_WORDS = [
    'что такое', 'что означает', 'что это', 'что значит',
    'для чего', 'зачем нужен', 'зачем нужна',
    'объясни', 'объясните', 'расскажи', 'расскажите',
    'чем отличается', 'разница между', 'почему',
    'какие модули', 'какие каналы',
]

_CONTACT_WORDS = [
    'как связаться', 'технический менеджер', 'тех менеджер', 'техподдержка',
    'поддержка', 'контакт', 'телефон менеджера', 'обратиться к менеджеру',
    'связаться с менеджером',
]

_HISTORY_WORDS = [
    'что обсуждали', 'история чата', 'полная выгрузка', 'покажи историю',
    'что было обсуждено', 'весь чат', 'всё что говорили', 'итог разговора',
    'суммируй разговор', 'краткое резюме чата',
]


def _is_contact_question(text: str) -> bool:
    n = normalize(text)
    return any(normalize(w) in n for w in _CONTACT_WORDS)


def _is_history_question(text: str) -> bool:
    n = normalize(text)
    return any(normalize(w) in n for w in _HISTORY_WORDS)


def _is_generic_question(text: str) -> bool:
    n = normalize(text)
    if any(normalize(s) in n for s in ANALYSIS_SYNONYMS.get('login', [])):
        return False
    if any(normalize(w) in n for w in _DEFINITION_WORDS):
        return False
    return any(normalize(w) in n for w in _GENERIC_WORDS)


def _last_bot_was_clarifying() -> bool:
    conv = getattr(st.session_state, 'conversation', [])
    for msg in reversed(conv):
        if msg['role'] == 'assistant':
            c = msg['content'].lower()
            return any(w in c for w in ['уточните', 'какой модуль', 'какой канал',
                                        'пожалуйста, уточните', 'аптечные данные или'])
    return False


def needs_clarification(text: str, context: Dict[str, Any]) -> Optional[str]:
    n = normalize(text)
    if any(normalize(s) in n for s in ANALYSIS_SYNONYMS.get('login', [])):
        return None
    if any(normalize(w) in n for w in _DEFINITION_WORDS):
        return None
    sell_in_hit = any(normalize(s) in n for s in CHANNEL_SYNONYMS['sell_in'])
    stock_hit   = any(normalize(s) in n for s in CHANNEL_SYNONYMS['stock'])
    ambiguous   = (sell_in_hit or stock_hit) and not context.get('module')
    generic_report = (
        any(w in n for w in ['отчет', 'отчёт', 'report', 'создать', 'построить'])
        and not context.get('module')
        and not context.get('channel')
    )
    if ambiguous:
        channel_word = 'Sell In' if sell_in_hit else 'Остатки'
        return (
            f'Канал «{channel_word}» присутствует в обоих модулях. Уточните:\n\n'
            '— **Аптечные данные** — закупки/остатки аптечных сетей\n'
            '— **Данные дистрибьютора** — закупки/склады дистрибьютора'
        )
    if generic_report:
        return (
            'Уточните, пожалуйста:\n\n'
            '— Какой **модуль**? Аптечные данные или Данные дистрибьютора?\n'
            '— Какой **канал**? (Sell Out, Sell In, Перемещение, Остатки, E-com, Тендер, Импорт...)'
        )
    if not context.get('module') and not context.get('channel'):
        if any(normalize(w) in n for w in _GENERIC_WORDS):
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


def _log_system_event(event_type: str) -> None:
    """Логирует системное событие (login, logout, new_chat)."""
    try:
        ensure_dirs()
        entry = {
            'event_type': event_type,
            'timestamp':  datetime.now().isoformat(),
            'username':   st.session_state.get('username', 'unknown'),
            'session_id': st.session_state.get('session_id', 'unknown'),
        }
        with LOG_FILE.open('a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        pass


def log_entry(entry: Dict[str, Any]) -> None:
    try:
        ensure_dirs()
        entry['event_type'] = 'chat'
        entry['username']   = st.session_state.get('username', 'unknown')
        entry['session_id'] = st.session_state.get('session_id', 'unknown')
        with LOG_FILE.open('a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception as e:
        st.warning(f'⚠️ Ошибка записи лога: {e}')


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
        st.session_state.context = {'module': None, 'channel': None, 'analysis_type': None}
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
        return '\n'.join((page.extract_text() or '').strip() for page in reader.pages)
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
        raise FileNotFoundError('Документы базы знаний не найдены.')
    return docs


def split_text(text: str, max_len: int = 900) -> List[str]:
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
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(y * y for y in b))
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
    q_emb  = get_embeddings([question.lower()], api_key)[0]
    texts  = [item['text'] for item in corpus]
    c_embs = get_embeddings(texts, api_key)
    for item, emb in zip(corpus, c_embs):
        score = cosine(q_emb, emb)
        tl = item['text'].lower()
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
# OPENAI — универсальный вызов
# =============================================================================

def ask_openai(
    messages: List[Dict[str, str]],
    api_key: str,
    model: str = COMPLETION_MODEL,
    max_tokens: int = MAX_TOKENS,
    temperature: float = 0.6,
) -> str:
    resp = requests.post(
        OPENAI_COMPLETION_URL,
        json={'model': model, 'max_tokens': max_tokens, 'messages': messages, 'temperature': temperature},
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        timeout=90,
    )
    if resp.status_code == 401:
        return '❌ Неверный API ключ.'
    if resp.status_code == 429:
        return '⏱️ Превышен лимит запросов OpenAI. Подождите немного и повторите.'
    if resp.status_code != 200:
        return f'❌ Ошибка API (код {resp.status_code}). Попробуйте снова.'
    choices = resp.json().get('choices', [])
    if not choices:
        return '❌ Пустой ответ от сервера.'
    return choices[0].get('message', {}).get('content', '').strip()

# =============================================================================
# STAGE 1 — LLM НОРМАЛИЗАЦИЯ
# =============================================================================

_STAGE1_SYSTEM = """\
Ты — нормализатор запросов для AI-ассистента PhaDataPro. Верни ТОЛЬКО JSON без markdown.

ДОПУСТИМЫЕ intent:
- definition: "что такое X", "что означает", "объясни"
- navigation: "как войти", "как зайти", "личный кабинет"
- build_report: "как создать/построить отчёт", "как выгрузить"
- compare: "сравнить", "план vs факт", "прирост", "динамика"
- troubleshooting: "не работает", "пустой отчёт", "ошибка", "данные не загружаются"
- analytics_help: "как анализировать", "топ аптек", "доля рынка"
- business_explanation: "зачем нужен", "почему", "в чём разница"
- contact: "как связаться", "технический менеджер", "техподдержка", "контакты"
- history: "что обсуждали", "история чата", "покажи всё", "итог разговора", "полная выгрузка"
- other: всё остальное

МОДУЛИ: pharmacy_data | distributor_data | null
КАНАЛЫ: sell_out | sell_in | sell_out_ecom | placement | stock | ecom | dist_sell_in | sell_in_tender | tender | import_channel | dist_stock | null
АНАЛИЗЫ: sales_breakdown | plan_vs_fact | percent_plan | growth | share | high_potential | categorization | null

JSON формат:
{
  "intent": "...",
  "module": "...",
  "channel": "...",
  "analysis_type": "...",
  "normalized_query": "нормализованный вопрос для RAG",
  "sub_queries": ["запрос1", "запрос2"]
}

ТОЛЬКО JSON, без пояснений!
"""


def normalize_question_llm(
    question: str,
    conversation: List[Dict[str, Any]],
    context: Dict[str, Any],
    api_key: str,
) -> Dict[str, Any]:
    ctx_lines = []
    if context.get('module'):
        ctx_lines.append(f"Модуль: {MODULE_DISPLAY.get(context['module'], context['module'])}")
    if context.get('channel'):
        ctx_lines.append(f"Канал: {CHANNEL_DISPLAY.get(context['channel'], context['channel'])}")
    ctx_block = '\n'.join(ctx_lines)

    recent    = conversation[-4:] if len(conversation) >= 4 else conversation
    conv_lines = '\n'.join(f"{m['role'].upper()}: {m['content'][:120]}" for m in recent)

    user_msg = f"Контекст:\n{ctx_block}\n\nДиалог:\n{conv_lines}\n\nВопрос: {question}"

    raw = ask_openai(
        [{'role': 'system', 'content': _STAGE1_SYSTEM}, {'role': 'user', 'content': user_msg}],
        api_key, model=NORMALIZATION_MODEL, max_tokens=NORM_MAX_TOKENS, temperature=0,
    )
    raw = re.sub(r'^```json\s*', '', raw.strip())
    raw = re.sub(r'\s*```$', '', raw.strip())
    try:
        result = json.loads(raw)
        result['intent']           = result.get('intent') or 'other'
        result['module']           = result.get('module') or None
        result['channel']          = result.get('channel') or None
        result['analysis_type']    = result.get('analysis_type') or None
        result['normalized_query'] = result.get('normalized_query') or question
        result['sub_queries']      = result.get('sub_queries') or [result['normalized_query']]
        return result
    except Exception:
        return {
            'intent': 'other', 'module': None, 'channel': None, 'analysis_type': None,
            'normalized_query': question, 'sub_queries': [question],
        }

# =============================================================================
# STAGE 2 — SYSTEM PROMPT И СООБЩЕНИЯ
# =============================================================================

_INTENT_INSTRUCTIONS: Dict[str, str] = {
    'definition': (
        'Это вопрос-определение. Дай КРАТКИЙ ответ (2-4 предложения) — только суть понятия. '
        'БЕЗ пошаговых инструкций и шагов входа.'
    ),
    'navigation': (
        'Это вопрос о входе. Инструкция: перейти на pdp.viortis.kz → Email → Пароль → SIGN IN.'
    ),
    'build_report': (
        'Запрос на построение отчёта. Полная пошаговая инструкция. '
        'ОБЯЗАТЕЛЬНО: ⚠️ Период (отдельным пунктом), Фильтры (конкретные), Блоки (конкретные). '
        'НЕ ВКЛЮЧАЙ шаг входа в систему. Начинай с кнопки «Создать отчёт».'
    ),
    'compare': (
        'Запрос на сравнение/анализ. Пошаговая инструкция с ⚠️ Периодом, Блоками, Фильтрами. '
        'НЕ ВКЛЮЧАЙ шаг входа в систему.'
    ),
    'analytics_help': (
        'Аналитический запрос. Пошаговая инструкция. '
        'НЕ ВКЛЮЧАЙ шаг входа в систему. Начинай с «Создать отчёт».'
    ),
    'troubleshooting': 'Вопрос о проблеме. Дай конкретные шаги диагностики и решения.',
    'contact':  'Пользователь спрашивает контакты. Укажи контакты техменеджеров.',
    'history':  'Пользователь просит историю диалога. Кратко суммируй ВСЕ обсуждённые темы.',
    'business_explanation': 'Бизнес-вопрос. Краткое объяснение (3-5 предложений), без лишних шагов.',
}


def build_system_prompt(context: Dict[str, Any], intent: str = 'other') -> str:
    ctx_lines = []
    if context.get('module'):
        ctx_lines.append(f"Текущий модуль: **{MODULE_DISPLAY.get(context['module'], context['module'])}**")
    if context.get('channel'):
        ctx_lines.append(f"Текущий канал: **{CHANNEL_DISPLAY.get(context['channel'], context['channel'])}**")
    if context.get('analysis_type'):
        ctx_lines.append(f"Тип анализа: **{context['analysis_type']}**")
    ctx_block    = ('\n'.join(ctx_lines) + '\n\n') if ctx_lines else ''
    intent_instr = _INTENT_INSTRUCTIONS.get(intent, '')
    no_login = (
        '\n⛔ ЗАПРЕЩЕНО включать фразу "Откройте сайт pdp.viortis.kz и войдите" — пользователь уже в системе.\n'
        if intent in ('build_report', 'compare', 'analytics_help') else ''
    )

    return f"""Ты — AI-ассистент системы PhaDataPro (Viortis). Помогай работать с аналитической платформой.

{ctx_block}ТИП ЗАПРОСА: {intent}
{intent_instr}
{no_login}
ПРАВИЛА:
1. Только русский язык.
2. Только вопросы про PhaDataPro.
3. Для отчётов: нумерованные шаги, **жирный** для кнопок/полей.
4. Используй известный контекст сессии — не переспрашивай то, что уже сказано.
5. Если нет информации — честно скажи и направь к техменеджерам.

КАК СВЯЗАТЬСЯ С ТЕХНИЧЕСКИМ МЕНЕДЖЕРОМ:
{TECH_MANAGERS_BLOCK}

МОДУЛИ: Аптечные данные | Данные дистрибьютора
Каналы «Sell In» и «Остатки» есть в обоих модулях — уточняй если модуль не ясен.

ПРИ НЕВОЗМОЖНОСТИ ОТВЕТИТЬ — направь к:
{TECH_MANAGERS_BLOCK}"""


def build_messages(
    system_prompt: str,
    conversation: List[Dict[str, Any]],
    question: str,
    chunks: List[Dict[str, Any]],
    context: Dict[str, Any],
    intent: str = 'other',
    full_history: bool = False,
) -> List[Dict[str, str]]:
    kb_text = '\n\n---\n\n'.join(
        f"[Источник: {c['source']}]\n{c['text']}" for c in chunks
    ) if chunks else 'Информация в базе знаний не найдена.'

    ctx_reminder = []
    if context.get('module'):
        ctx_reminder.append(f"Модуль: {MODULE_DISPLAY.get(context['module'], context['module'])}")
    if context.get('channel'):
        ctx_reminder.append(f"Канал: {CHANNEL_DISPLAY.get(context['channel'], context['channel'])}")

    if intent == 'definition':
        task = 'Дай КРАТКОЕ определение (2-4 предложения). Никаких пошаговых инструкций.'
    elif intent in ('build_report', 'compare', 'analytics_help'):
        task = (
            'Полная пошаговая инструкция. НЕ включай шаг входа. '
            'Обязательно: ⚠️ Период, Фильтры (конкретные), Блоки (конкретные).'
        )
    elif intent == 'history':
        task = 'Пользователь просит сводку диалога. Кратко перечисли ВСЕ темы и вопросы которые обсуждались в этой сессии.'
    elif intent == 'contact':
        task = f'Укажи контакты:\n{TECH_MANAGERS_BLOCK}'
    elif intent == 'navigation':
        task = 'Краткая инструкция входа: pdp.viortis.kz → Email → Пароль → SIGN IN.'
    else:
        task = (
            'Ответь по теме. Для отчётов — НЕ включай шаг входа, начинай с «Создать отчёт». '
            'Если не можешь ответить — направь к техменеджерам.'
        )

    user_msg = (
        ('Контекст: ' + ', '.join(ctx_reminder) + '\n\n' if ctx_reminder else '') +
        (f'МАТЕРИАЛЫ ИЗ БАЗЫ ЗНАНИЙ:\n{kb_text}\n\n' if intent != 'history' else '') +
        f'ВОПРОС: {question}\n\nЗАДАЧА: {task}'
    )

    msgs: List[Dict[str, str]] = [{'role': 'system', 'content': system_prompt}]
    history_slice = conversation if full_history else conversation[-10:]
    for entry in history_slice:
        msgs.append({'role': entry['role'], 'content': entry['content']})
    msgs.append({'role': 'user', 'content': user_msg})
    return msgs

# =============================================================================
# ОБРАБОТКА ВОПРОСА — двухэтапный пайплайн
# =============================================================================

def process_question(question: str, force_module: Optional[str] = None) -> None:
    api_key = OPENAI_API_KEY
    ctx = st.session_state.context

    if force_module:
        ctx['module'] = force_module

    ts = datetime.now().strftime('%H:%M:%S')
    st.session_state.conversation.append({'role': 'user', 'content': question, 'timestamp': ts})

    # Быстрый ответ на контакты (без LLM)
    if _is_contact_question(question):
        _finish(CONTACT_ANSWER, question, 'contact', ctx, [])
        return

    # ── STAGE 1: LLM нормализация ─────────────────────────────────────────────
    normalized  = normalize_question_llm(question, st.session_state.conversation[:-1], ctx, api_key)
    intent      = normalized.get('intent', 'other')

    if intent == 'contact':
        _finish(CONTACT_ANSWER, question, 'contact', ctx, [])
        return

    # Обновление контекста — LLM + keyword fallback
    if normalized.get('module'):
        ctx['module'] = normalized['module']
    if normalized.get('channel'):
        ctx['channel'] = normalized['channel']
        if normalized['channel'] in CHANNEL_MODULE_MAP and not ctx.get('module'):
            ctx['module'] = CHANNEL_MODULE_MAP[normalized['channel']]
    if normalized.get('analysis_type'):
        ctx['analysis_type'] = normalized['analysis_type']

    if not ctx.get('module'):
        mod = extract_module(question)
        if mod:
            ctx['module'] = mod
    if not ctx.get('channel'):
        ch = extract_channel(question, ctx.get('module'))
        if ch:
            ctx['channel'] = ch
            if ch in CHANNEL_MODULE_MAP and not ctx.get('module'):
                ctx['module'] = CHANNEL_MODULE_MAP[ch]
    if not ctx.get('analysis_type'):
        at = extract_analysis(question)
        if at:
            ctx['analysis_type'] = at

    # History intent — передаём весь разговор
    if intent == 'history':
        system_prompt = build_system_prompt(ctx, 'history')
        messages = build_messages(
            system_prompt, st.session_state.conversation[:-1],
            question, [], ctx, 'history', full_history=True,
        )
        answer = ask_openai(messages, api_key)
        _finish(answer, question, intent, ctx, [])
        return

    # ── Уточнение нужно только если контекст ещё не установлен ──────────────
    if intent not in ('definition', 'business_explanation', 'navigation', 'troubleshooting', 'contact', 'history'):
        ch_in_msg  = extract_channel(question, None)
        mod_in_msg = extract_module(question)
        answering_clarification = _last_bot_was_clarifying()

        if _is_generic_question(question) and not ch_in_msg and not mod_in_msg and not answering_clarification:
            # *** ИСПРАВЛЕНИЕ: используем существующий контекст сессии если он есть ***
            if ctx.get('module') or ctx.get('channel'):
                clarify_ctx = ctx   # контекст известен — не переспрашиваем
            else:
                clarify_ctx = {'module': None, 'channel': None}  # нет контекста — уточняем
        else:
            clarify_ctx = ctx

        clarify = needs_clarification(question, clarify_ctx)
        if clarify:
            answer = f'Пожалуйста, уточните:\n\n{clarify}'
            _finish(answer, question, 'clarification', ctx, [])
            return

    # ── STAGE 2: RAG + Answer ─────────────────────────────────────────────────
    sub_queries = normalized.get('sub_queries', [question])
    norm_query  = normalized.get('normalized_query', question)

    try:
        all_chunks: List[Dict[str, Any]] = []
        seen_ids: set = set()

        for c in get_relevant_chunks(norm_query, st.session_state.corpus, api_key,
                                     ctx_module=ctx.get('module'), ctx_channel=ctx.get('channel')):
            if c['id'] not in seen_ids:
                all_chunks.append(c)
                seen_ids.add(c['id'])

        for sq in sub_queries[:2]:
            if sq != norm_query:
                for c in get_relevant_chunks(sq, st.session_state.corpus, api_key, top_k=3,
                                             ctx_module=ctx.get('module'), ctx_channel=ctx.get('channel')):
                    if c['id'] not in seen_ids:
                        all_chunks.append(c)
                        seen_ids.add(c['id'])

        all_chunks.sort(key=lambda x: x.get('score', 0), reverse=True)
        chunks = all_chunks[:6]
    except Exception as e:
        chunks = []
        st.warning(f'Поиск в базе знаний недоступен: {e}')

    system_prompt = build_system_prompt(ctx, intent)
    messages = build_messages(
        system_prompt, st.session_state.conversation[:-1],
        question, chunks, ctx, intent,
    )

    try:
        answer = ask_openai(messages, api_key)
        uncertainty = ['не могу найти', 'нет информации', 'не нашёл', 'нет в базе',
                       'выходит за пределы', 'обратитесь к администратору', 'не могу ответить']
        if any(m in answer.lower() for m in uncertainty):
            answer += FALLBACK_SUFFIX
    except Exception as e:
        answer = f'❌ Ошибка OpenAI: {e}{FALLBACK_SUFFIX}'

    _finish(answer, question, intent, ctx, chunks)


def _finish(
    answer: str,
    question: str,
    intent: str,
    ctx: Dict[str, Any],
    chunks: List[Dict[str, Any]],
) -> None:
    ts2 = datetime.now().strftime('%H:%M:%S')
    st.session_state.conversation.append({'role': 'assistant', 'content': answer, 'timestamp': ts2})
    log_entry({
        'timestamp':  datetime.now().isoformat(),
        'user_input': question,
        'intent':     intent,
        'context':    {k: v for k, v in ctx.items() if v},
        'response':   answer,
        'sources':    [c['source'] for c in chunks],
    })
    save_history(st.session_state.conversation)

# =============================================================================
# UI — СТИЛИ И КОМПОНЕНТЫ
# =============================================================================

def apply_styles() -> None:
    st.markdown('''<style>
        .stChatMessage { border-radius: 12px; }
        .context-badge {
            display: inline-block; background: #1D9E75; color: white;
            padding: 3px 10px; border-radius: 20px; font-size: 13px; margin: 2px 4px;
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
            'Как связаться с техническим менеджером?',
        ]
    else:
        questions = [
            'Как создать отчёт Sell In дистрибьютора?',
            'Что такое Tender (тендер)?',
            'Как работает Sell In + Tender?',
            'Как посмотреть Импорт?',
            'Как посмотреть остатки дистрибьютора?',
            'Как сравнить план и факт?',
            'Как связаться с техническим менеджером?',
        ]
    st.markdown('**Быстрые вопросы:**')
    cols = st.columns(4)
    for i, q in enumerate(questions):
        if cols[i % 4].button(q, key=f'quick_{i}', use_container_width=True):
            return q
    return None

# =============================================================================
# ЧАТБОТ — основной рендер
# =============================================================================

def render_chatbot() -> None:
    if not OPENAI_API_KEY:
        st.error(
            '⚠️ **OPENAI_API_KEY не найден.**\n\n'
            '**Streamlit Cloud:** App settings → Secrets → добавьте:\n'
            '```\nOPENAI_API_KEY = "sk-proj-..."\n```\n\n'
            '**Локально:** создайте `.streamlit/secrets.toml` (см. `.streamlit/secrets.toml.example`).'
        )
        st.stop()

    init_session()

    # ── Шапка ─────────────────────────────────────────────────────────────────
    col_title, col_new, col_status, col_logout = st.columns([4, 1, 1, 1])
    with col_title:
        st.markdown('# 🏥 PhaDataPro AI Ассистент')
    with col_new:
        st.markdown('<br>', unsafe_allow_html=True)
        if st.button('✏️ Новый чат', use_container_width=True, type='primary'):
            _log_system_event('new_chat')
            st.session_state.conversation = []
            st.session_state.context = {'module': None, 'channel': None, 'analysis_type': None}
            st.session_state.session_id = str(uuid.uuid4())[:8]
            st.rerun()
    with col_status:
        st.markdown(
            '<br><span style="background:#1D9E75;color:white;padding:6px 14px;'
            'border-radius:20px;font-size:13px">🟢 ОНЛАЙН</span>',
            unsafe_allow_html=True,
        )
    with col_logout:
        st.markdown('<br>', unsafe_allow_html=True)
        if st.button('Выйти', use_container_width=True):
            _log_system_event('session_end')
            for key in ['logged_in', 'username', 'user_role', 'session_id',
                        'conversation', 'context', 'corpus', 'pending_input', 'sidebar_module']:
                st.session_state.pop(key, None)
            st.rerun()
    st.markdown('---')

    # ── Боковая панель ─────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown(f'👤 **{st.session_state.get("username", "")}**')
        st.markdown('---')
        st.subheader('📦 Модуль')
        sidebar_module = st.radio(
            'Модуль', options=['pharmacy_data', 'distributor_data'],
            format_func=lambda x: MODULE_DISPLAY[x],
            index=0 if st.session_state.sidebar_module != 'distributor_data' else 1,
            key='_sidebar_module_radio', label_visibility='collapsed',
        )
        st.session_state.sidebar_module = sidebar_module

        st.markdown('---')
        if st.button('🗑️ Очистить и сохранить историю', use_container_width=True):
            save_history(st.session_state.conversation)
            st.session_state.conversation = []
            st.session_state.context = {'module': None, 'channel': None, 'analysis_type': None}
            st.success('История сохранена')
            st.rerun()

        if st.button('💾 Загрузить историю', use_container_width=True):
            loaded = load_history()
            if loaded:
                st.session_state.conversation = loaded
                st.success(f'Загружено {len(loaded)} сообщений')
                st.rerun()
            else:
                st.info('История пуста')

        st.markdown('---')
        st.markdown('**Техподдержка:**')
        st.markdown('Ардакулы Арсен  \ntechmanager04@viortis.kz  \n+7 708 218 10 53')
        st.markdown('Хисматулина Тахмина  \ntechmanager07@viortis.kz  \n+7 708 268 80 17')

    # ── Загрузка корпуса ───────────────────────────────────────────────────────
    if st.session_state.corpus is None:
        with st.spinner('📚 Загружаю базу знаний...'):
            try:
                docs = load_kb_documents()
                st.session_state.corpus = build_corpus(docs)
                st.success(f'✅ База знаний: {len(st.session_state.corpus)} фрагментов из {len(docs)} документов')
            except Exception as e:
                st.error(f'❌ {e}')
                return

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
            st.session_state.pending_input  = quick
            st.session_state.pending_module = st.session_state.sidebar_module
            st.rerun()

    # ── Ввод ───────────────────────────────────────────────────────────────────
    user_input = st.chat_input('Введите ваш вопрос о PhaDataPro...')

    question_to_process: Optional[str] = None
    force_mod: Optional[str] = None

    if user_input and user_input.strip():
        question_to_process = user_input.strip()
    elif st.session_state.pending_input:
        question_to_process = st.session_state.pending_input
        force_mod = st.session_state.pop('pending_module', None)
        st.session_state.pending_input = None

    if question_to_process:
        with st.spinner('💭 Анализирую вопрос...'):
            process_question(question_to_process, force_module=force_mod)
        st.rerun()

# =============================================================================
# АДМИН-ПАНЕЛЬ
# =============================================================================

def load_all_logs() -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    if LOG_FILE.exists():
        try:
            with LOG_FILE.open('r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except Exception:
                            pass
        except Exception:
            pass
    return entries


def render_admin_panel() -> None:
    st.header('🔧 Панель администратора')

    logs = load_all_logs()
    chat_logs = [l for l in logs if l.get('event_type') == 'chat']

    if not chat_logs:
        st.info('Логов пока нет.')
        return

    # ── Метрики ────────────────────────────────────────────────────────────────
    today_str    = datetime.now().date().isoformat()
    today_logs   = [l for l in chat_logs if l.get('timestamp', '').startswith(today_str)]
    all_users    = sorted(set(l.get('username', 'unknown') for l in chat_logs))
    all_sessions = set(l.get('session_id', '') for l in chat_logs)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric('Всего сообщений', len(chat_logs))
    c2.metric('Сессий', len(all_sessions))
    c3.metric('Пользователей', len(all_users))
    c4.metric('Сегодня', len(today_logs))

    st.markdown('---')

    # ── Фильтры ────────────────────────────────────────────────────────────────
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        filter_user = st.selectbox('Пользователь', ['Все'] + all_users)
    with col_f2:
        filter_date = st.date_input('Дата (необязательно)', value=None, key='admin_date')
    with col_f3:
        filter_intent = st.selectbox(
            'Intent',
            ['Все', 'build_report', 'analytics_help', 'compare', 'definition',
             'navigation', 'contact', 'troubleshooting', 'history', 'clarification', 'other'],
        )

    filtered = chat_logs[:]
    if filter_user != 'Все':
        filtered = [l for l in filtered if l.get('username') == filter_user]
    if filter_date:
        filtered = [l for l in filtered if l.get('timestamp', '').startswith(filter_date.isoformat())]
    if filter_intent != 'Все':
        filtered = [l for l in filtered if l.get('intent') == filter_intent]

    st.caption(f'Показано записей: {len(filtered)}')

    # ── Кнопка экспорта ────────────────────────────────────────────────────────
    if filtered:
        export_lines = []
        for e in filtered:
            export_lines.append(
                f"[{e.get('timestamp','')[:19]}] {e.get('username','')} | {e.get('intent','')}\n"
                f"Q: {e.get('user_input','')}\n"
                f"A: {e.get('response','')[:500]}\n"
                + ('-' * 60)
            )
        export_text = '\n'.join(export_lines)
        st.download_button(
            '⬇️ Скачать логи (TXT)',
            data=export_text.encode('utf-8'),
            file_name=f'pdp_logs_{datetime.now().strftime("%Y%m%d_%H%M")}.txt',
            mime='text/plain',
        )

    st.markdown('---')

    # ── Группировка по сессиям ────────────────────────────────────────────────
    sessions_map: Dict[str, List[Dict]] = {}
    for entry in reversed(filtered):
        sid = entry.get('session_id', 'unknown')
        if sid not in sessions_map:
            sessions_map[sid] = []
        sessions_map[sid].append(entry)

    shown = 0
    for sid, entries in sessions_map.items():
        if shown >= 100:
            st.info('Показаны последние 100 сессий. Используйте фильтры для уточнения.')
            break
        shown += 1
        first    = entries[0]
        username = first.get('username', 'unknown')
        ts       = first.get('timestamp', '')[:16].replace('T', ' ')
        n_msgs   = len(entries)
        intents  = ', '.join(set(e.get('intent', '') for e in entries if e.get('intent')))

        with st.expander(
            f"👤 **{username}** | 🕐 {ts} | 💬 {n_msgs} сообщ. | 🏷️ {intents}",
            expanded=False,
        ):
            for entry in entries:
                ts_entry = entry.get('timestamp', '')[:19].replace('T', ' ')
                intent   = entry.get('intent', 'unknown')
                ctx      = entry.get('context', {})
                ctx_str  = ' | '.join(f"{k}: {v}" for k, v in ctx.items() if v)

                col_meta1, col_meta2 = st.columns([2, 3])
                with col_meta1:
                    st.markdown(f'`{ts_entry}` &nbsp; **Intent:** `{intent}`')
                with col_meta2:
                    if ctx_str:
                        st.markdown(f'**Контекст:** {ctx_str}')

                with st.chat_message('user'):
                    st.markdown(entry.get('user_input', ''))

                with st.chat_message('assistant'):
                    response = entry.get('response', '')
                    # Показываем первые 800 символов с кнопкой "показать всё"
                    if len(response) > 800:
                        st.markdown(response[:800] + '…')
                        with st.expander('Показать полный ответ'):
                            st.markdown(response)
                    else:
                        st.markdown(response)

                sources = entry.get('sources', [])
                if sources:
                    st.caption(f'Источники: {", ".join(set(sources))}')
                st.divider()

# =============================================================================
# ГЛАВНОЕ ПРИЛОЖЕНИЕ
# =============================================================================

def main() -> None:
    st.set_page_config(
        page_title='PhaDataPro AI',
        page_icon='🏥',
        layout='wide',
        initial_sidebar_state='expanded',
    )
    apply_styles()

    # Проверка авторизации
    if not st.session_state.get('logged_in', False):
        render_login_page()
        return

    user_role = st.session_state.get('user_role', 'user')

    if user_role == 'admin':
        tab_chat, tab_admin = st.tabs(['💬 Чат-ассистент', '🔧 Администрирование'])
        with tab_chat:
            render_chatbot()
        with tab_admin:
            render_admin_panel()
    else:
        render_chatbot()


if __name__ == '__main__':
    main()
