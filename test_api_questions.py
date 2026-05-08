import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

import requests

OPENAI_COMPLETION_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_EMBEDDING_URL = "https://api.openai.com/v1/embeddings"
COMPLETION_MODEL = "gpt-4o"
EMBEDDING_MODEL = "text-embedding-3-small"
MAX_TOKENS = 1000
PROMPT_FILE = Path("prompt.md")
KB_FILES = [
    Path("ТЗ PDP ИИ.docx"),
    Path("Вопросы для ИИ маршрутизатор.docx"),
    Path("Инструкция для пользователей PhadataPro (1).pdf"),
]


def get_api_key() -> str:
    key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY") or ""
    if not key:
        raise RuntimeError("OPENAI_API_KEY не задан. Установите переменную окружения или создайте .streamlit/secrets.toml.")
    return key


def load_prompt(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Файл prompt.md не найден по пути: {path}")
    return path.read_text(encoding="utf-8")


def extract_system_prompt(prompt_text: str) -> str:
    marker = "Ты — AI-ассистент системы PhaDataPro"
    idx = prompt_text.find(marker)
    if idx != -1:
        return prompt_text[idx:].strip()
    return prompt_text.strip()


try:
    from docx import Document
except ImportError:
    Document = None


PdfReader = None
try:
    from pypdf import PdfReader
    PdfReader = PdfReader
except ImportError:
    try:
        from PyPDF2 import PdfReader
        PdfReader = PdfReader
    except ImportError:
        PdfReader = None


def load_docx_text(path: Path) -> str:
    if Document is None:
        raise RuntimeError('Установите пакет python-docx: pip install python-docx')
    doc = Document(path)
    return "\n".join(paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip())


def load_pdf_text(path: Path) -> str:
    if PdfReader is None:
        raise RuntimeError('Установите пакет pypdf: pip install pypdf')
    reader = PdfReader(path)
    texts: List[str] = []
    for page in reader.pages:
        page_text = page.extract_text() or ""
        if page_text.strip():
            texts.append(page_text)
    return "\n".join(texts)


def load_kb_documents(paths: List[Path]) -> List[Dict[str, str]]:
    documents: List[Dict[str, str]] = []
    for path in paths:
        if not path.exists():
            continue
        if path.suffix.lower() == ".docx":
            documents.append({"source": path.name, "text": load_docx_text(path)})
        elif path.suffix.lower() == ".pdf":
            documents.append({"source": path.name, "text": load_pdf_text(path)})
    return documents


def split_text(text: str, max_chars: int = 1000) -> List[str]:
    text = text.replace("\r", "")
    pieces: List[str] = []
    current: List[str] = []
    current_len = 0

    for paragraph in re.split(r"\n{2,}", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) > max_chars:
            if current:
                pieces.append("\n\n".join(current))
                current = []
                current_len = 0
            for i in range(0, len(paragraph), max_chars):
                pieces.append(paragraph[i : i + max_chars].strip())
            continue

        if current_len + len(paragraph) + 2 <= max_chars:
            current.append(paragraph)
            current_len += len(paragraph) + 2
        else:
            pieces.append("\n\n".join(current))
            current = [paragraph]
            current_len = len(paragraph)

    if current:
        pieces.append("\n\n".join(current))
    return pieces


def build_corpus(documents: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    corpus: List[Dict[str, Any]] = []
    for doc in documents:
        chunks = split_text(doc["text"], max_chars=900)
        for idx, chunk in enumerate(chunks, start=1):
            corpus.append({"source": doc["source"], "text": chunk, "id": f"{doc['source']}#{idx}"})
    return corpus


def get_embeddings(texts: List[str], api_key: str) -> List[List[float]]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": EMBEDDING_MODEL, "input": texts}
    response = requests.post(OPENAI_EMBEDDING_URL, headers=headers, json=payload, timeout=60)
    if response.status_code != 200:
        raise RuntimeError(f"OpenAI embeddings error {response.status_code}: {response.text}")
    data = response.json()
    embeddings = [item["embedding"] for item in data.get("data", [])]
    return embeddings


def cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def get_relevant_chunks(question: str, corpus: List[Dict[str, Any]], api_key: str, top_k: int = 4) -> List[Dict[str, Any]]:
    if not corpus:
        return []
    question_emb = get_embeddings([question], api_key)[0]
    chunk_texts = [item["text"] for item in corpus]
    chunk_embs = get_embeddings(chunk_texts, api_key)
    for item, emb in zip(corpus, chunk_embs):
        item["score"] = cosine_similarity(question_emb, emb)
    sorted_corpus = sorted(corpus, key=lambda item: item["score"], reverse=True)
    return sorted_corpus[:top_k]


def build_messages(system_prompt: str, question: str, relevant_chunks: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    context = "\n\n".join(
        f"Источник: {chunk['source']}\n{chunk['text']}" for chunk in relevant_chunks
    )
    if not context:
        context = "Информация по запросу в базе знаний не найдена."
    user_content = (
        "Используй только информацию из указанного контекста. Ответь красиво, коротко и по делу.\n\n"
        f"Контекст:\n{context}\n\n"
        f"Вопрос: {question}\n"
        "Ответ:"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


def ask_openai(messages: List[Dict[str, str]], api_key: str) -> str:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": COMPLETION_MODEL, "max_tokens": MAX_TOKENS, "messages": messages}
    response = requests.post(OPENAI_COMPLETION_URL, headers=headers, json=payload, timeout=60)
    if response.status_code == 401:
        raise RuntimeError("Неверный API ключ. Проверьте и введите снова.")
    if response.status_code == 429:
        raise RuntimeError("Превышен лимит запросов. Подождите и попробуйте снова.")
    if response.status_code != 200:
        raise RuntimeError(f"Ошибка соединения. Попробуйте снова. (status {response.status_code})")
    data = response.json()
    choice = data.get("choices", [])[0]
    return choice.get("message", {}).get("content", "").strip()


def main() -> None:
    api_key = get_api_key()
    question = input("Введите вопрос: ").strip()
    if not question:
        print("Ошибка: Вопрос не задан.")
        sys.exit(1)

    prompt_text = load_prompt(PROMPT_FILE)
    system_prompt = extract_system_prompt(prompt_text)
    documents = load_kb_documents(KB_FILES)
    if not documents:
        raise RuntimeError("Базы знаний не найдены. Убедитесь, что файлы ТЗ PDP ИИ, Вопросы для ИИ маршрутизатора и Инструкция для пользователей PhadataPro находятся в рабочем каталоге.")

    corpus = build_corpus(documents)
    relevant_chunks = get_relevant_chunks(question, corpus, api_key)
    messages = build_messages(system_prompt, question, relevant_chunks)
    answer = ask_openai(messages, api_key)
    print(answer)


if __name__ == "__main__":
    main()
