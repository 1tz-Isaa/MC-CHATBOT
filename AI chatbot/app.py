from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from catalog import bootstrap_catalog, get_catalog_summary, load_catalog_resources


# Main runtime config for the local chatbot app.
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:120b-clound")
MAX_CONTEXT_ITEMS = 4
SUPPORTED_TOPICS = [
    "admissions",
    "teachers",
    "classes",
    "rooms",
    "office administration",
    "counselors",
    "transportation",
    "new student onboarding",
    "counseling",
    "athletics calendar",
    "sports calendar",
    "events calendar",
    "school events",
    "daily news",
    "school links",
    "staff contacts you add locally",
    "rooms you add locally",
]

GREETING_TOKENS = {"hi", "hello", "hey", "yo", "sup", "hola"}
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "can",
    "do",
    "for",
    "how",
    "i",
    "is",
    "it",
    "malden",
    "catholic",
    "mc",
    "me",
    "of",
    "on",
    "or",
    "school",
    "tell",
    "the",
    "to",
    "what",
    "where",
    "who",
}
LATEST_NEWS_PATTERNS = (
    "latest daily news",
    "today's daily news",
    "todays daily news",
    "daily announcements",
    "today's announcements",
    "todays announcements",
    "latest announcements",
)
NEXT_GAME_PATTERNS = (
    "next sports game",
    "next game",
    "next match",
    "upcoming game",
    "upcoming sports game",
)
NEXT_EVENT_PATTERNS = (
    "next event",
    "upcoming event",
    "upcoming school event",
    "next school event",
    "school calendar",
    "events calendar",
    "what events are coming up",
)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list)


class Source(BaseModel):
    title: str
    url: str | None = None
    source_type: Literal["official", "local"]


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    model: str
    used_resource_ids: list[str]


# Resource loading combines official website facts, local notes, and structured catalog records.
def load_resource_file(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_resources() -> list[dict]:
    resources: list[dict] = []
    for filename in ("official_resources.json", "local_resources.json"):
        resources.extend(load_resource_file(DATA_DIR / filename))
    resources.extend(load_catalog_resources())
    return resources


bootstrap_catalog()


# This is the lightweight retrieval layer used before calling the LLM.
def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def tokenize(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", normalize_text(value)))


def resource_blob(resource: dict) -> str:
    parts: list[str] = [
        resource.get("title", ""),
        resource.get("summary", ""),
        " ".join(resource.get("keywords", [])),
        " ".join(resource.get("details", [])),
    ]
    for contact in resource.get("contacts", []):
        parts.extend(
            [
                contact.get("name", ""),
                contact.get("role", ""),
                contact.get("email", ""),
                contact.get("phone", ""),
            ]
        )
    return " ".join(part for part in parts if part)


def search_resources(message: str, resources: list[dict], limit: int = MAX_CONTEXT_ITEMS) -> list[dict]:
    query = normalize_text(message)
    query_tokens = tokenize(query) - STOPWORDS
    if not query_tokens:
        return []
    scored: list[tuple[int, dict]] = []

    for resource in resources:
        title_tokens = tokenize(resource.get("title", ""))
        keyword_tokens = tokenize(" ".join(resource.get("keywords", [])))
        body_tokens = tokenize(resource_blob(resource))

        score = 0
        score += len(query_tokens & title_tokens) * 6
        score += len(query_tokens & keyword_tokens) * 5
        score += len(query_tokens & body_tokens) * 2

        for keyword in resource.get("keywords", []):
            keyword_normalized = normalize_text(keyword)
            if keyword_normalized and keyword_normalized in query:
                score += 8

        if resource.get("is_placeholder"):
            score -= 4

        if score > 0:
            scored.append((score, resource))

    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        return []

    best_score = scored[0][0]
    threshold = max(8, best_score // 3)
    filtered_pairs = [(score, resource) for score, resource in scored if score >= threshold]
    has_real_match = any(not resource.get("is_placeholder", False) for _, resource in filtered_pairs)
    filtered = [
        resource
        for score, resource in filtered_pairs
        if not (has_real_match and resource.get("is_placeholder", False))
    ]
    return filtered[:limit]


def is_greeting(message: str) -> bool:
    words = tokenize(message)
    return bool(words) and words <= GREETING_TOKENS


# These shortcuts bypass fuzzy retrieval for obvious "latest" or "next" questions.
def special_catalog_answer(message: str) -> ChatResponse | None:
    normalized = normalize_text(message)
    summary = get_catalog_summary()

    if any(pattern in normalized for pattern in LATEST_NEWS_PATTERNS):
        latest_news = summary.get("latest_news", [])
        if not latest_news:
            return ChatResponse(
                answer="I do not have any approved daily news items in the local catalog yet.",
                sources=[],
                model=OLLAMA_MODEL,
                used_resource_ids=[],
            )
        news = latest_news[0]
        answer = f"Latest daily news: {news['title']}. {news['summary']}"
        return ChatResponse(
            answer=answer,
            sources=[
                Source(
                    title=f"Daily News: {news['title']}",
                    url=news.get("source_url"),
                    source_type="local",
                )
            ],
            model=OLLAMA_MODEL,
            used_resource_ids=[f"news-{news['id']}"],
        )

    if any(pattern in normalized for pattern in NEXT_GAME_PATTERNS):
        upcoming_games = summary.get("upcoming_games", [])
        if not upcoming_games:
            return ChatResponse(
                answer="I do not have an approved upcoming sports game in the local catalog yet.",
                sources=[],
                model=OLLAMA_MODEL,
                used_resource_ids=[],
            )
        game = upcoming_games[0]
        answer = (
            f"Next sports game: {game['sport_name']} {game.get('team_level') or ''} vs "
            f"{game.get('opponent') or 'TBD'} on {game.get('game_date') or 'TBD'} at "
            f"{game.get('game_time') or 'TBD'} in {game.get('location') or game.get('home_game_location') or 'TBD'}."
        )
        return ChatResponse(
            answer=" ".join(answer.split()),
            sources=[],
            model=OLLAMA_MODEL,
            used_resource_ids=[f"sports-game-{game['id']}"],
        )

    if any(pattern in normalized for pattern in NEXT_EVENT_PATTERNS):
        upcoming_events = summary.get("upcoming_events", [])
        if not upcoming_events:
            return ChatResponse(
                answer="I do not have an approved upcoming school event in the local calendar yet.",
                sources=[],
                model=OLLAMA_MODEL,
                used_resource_ids=[],
            )
        event = upcoming_events[0]
        answer = (
            f"Next school event: {event['title']} on {event.get('event_date') or 'TBD'}"
            f"{f' at {event['start_time']}' if event.get('start_time') else ''}."
            f" {event['summary']}"
        )
        return ChatResponse(
            answer=" ".join(answer.split()),
            sources=[
                Source(
                    title=f"Event: {event['title']}",
                    url=event.get("source_url"),
                    source_type="local",
                )
            ],
            model=OLLAMA_MODEL,
            used_resource_ids=[f"event-{event['id']}"],
        )

    return None


def build_context(resources: list[dict]) -> str:
    context_blocks: list[str] = []
    for resource in resources:
        contacts = resource.get("contacts", [])
        contact_lines = []
        for contact in contacts:
            bits = [contact.get("name", ""), contact.get("role", "")]
            line = " - ".join(bit for bit in bits if bit)
            extras = []
            if contact.get("email"):
                extras.append(f"email: {contact['email']}")
            if contact.get("phone"):
                extras.append(f"phone: {contact['phone']}")
            if extras:
                line = f"{line} ({', '.join(extras)})" if line else ", ".join(extras)
            if line:
                contact_lines.append(f"- {line}")

        detail_lines = [f"- {detail}" for detail in resource.get("details", [])]
        block = "\n".join(
            part
            for part in [
                f"Resource ID: {resource['id']}",
                f"Title: {resource['title']}",
                f"Category: {resource['category']}",
                f"Source type: {resource['source_type']}",
                f"Summary: {resource['summary']}",
                "Verification: starter data only, not fully approved yet." if resource.get("is_placeholder") else "Verification: approved data.",
                "Details:\n" + "\n".join(detail_lines) if detail_lines else "",
                "Contacts:\n" + "\n".join(contact_lines) if contact_lines else "",
                f"Source URL: {resource['source_url']}" if resource.get("source_url") else "",
                f"Source note: {resource['source_note']}" if resource.get("source_note") else "",
            ]
            if part
        )
        context_blocks.append(block)
    return "\n\n".join(context_blocks)


def make_fallback_answer() -> ChatResponse:
    return ChatResponse(
        answer=(
            "I do not have approved MC information for that yet. Try asking about admissions, "
            "teachers, classes, rooms, counseling, daily news, sports calendar, events calendar, or add the missing "
            "room/staff/schedule info to the local catalog."
        ),
        sources=[],
        model=OLLAMA_MODEL,
        used_resource_ids=[],
    )


async def call_ollama(
    message: str,
    history: list[ChatTurn],
    context: str,
    *,
    has_placeholder_context: bool,
    only_placeholder_context: bool,
) -> str:
    system_prompt = (
        "You are Ask MC, a cautious Malden Catholic information assistant.\n"
        "Answer only from the approved context provided below.\n"
        "If the context does not answer the question, say you do not have that information yet.\n"
        "Do not invent dates, people, room numbers, schedules, policies, or application details.\n"
        "If the context mentions an official contact or link, direct the user there when useful.\n"
        "Keep the answer concise and practical.\n"
        "Do not include a Sources section because the app will render sources separately.\n\n"
        f"Approved context:\n{context}"
    )

    if has_placeholder_context:
        system_prompt += (
            "\n\nSome context may be marked as starter data only."
            " Never present starter data as fully verified."
            " If you use starter data, explicitly say it still needs school approval or confirmation."
        )

    if only_placeholder_context:
        system_prompt += (
            "\nAll available context for this question is starter data only."
            " Make that limitation explicit in the answer."
        )

    messages = [{"role": "system", "content": system_prompt}]
    for turn in history[-6:]:
        messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": message})

    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": messages,
        "options": {"temperature": 0.2},
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
            response.raise_for_status()
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=503,
            detail="Could not reach Ollama. Start it with `ollama serve` and make sure the model exists.",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Ollama request failed: {exc}") from exc

    data = response.json()
    return data.get("message", {}).get("content", "").strip()


# FastAPI routes: web page, health, catalog summary, and chat endpoint.
app = FastAPI(title="Ask MC", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict:
    catalog_summary = get_catalog_summary()
    resources = load_resources()
    model_available = False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            response.raise_for_status()
            tags = response.json().get("models", [])
            model_available = any(tag.get("model") == OLLAMA_MODEL or tag.get("name") == OLLAMA_MODEL for tag in tags)
    except httpx.HTTPError:
        model_available = False

    return {
        "app": "ask-mc",
        "model": OLLAMA_MODEL,
        "model_available": model_available,
        "resource_count": len(resources),
        "supported_topics": SUPPORTED_TOPICS,
        "catalog_counts": catalog_summary["counts"],
    }


@app.get("/api/catalog/summary")
async def catalog_summary() -> dict:
    return get_catalog_summary()


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    message = request.message.strip()
    if is_greeting(message):
        return ChatResponse(
            answer=(
                "Hi. I can help with approved MC info like admissions, teachers, classes, rooms, "
                "counseling, daily news, sports calendar, school events, and any local staff or schedule data you add."
            ),
            sources=[],
            model=OLLAMA_MODEL,
            used_resource_ids=[],
        )

    shortcut_answer = special_catalog_answer(message)
    if shortcut_answer is not None:
        return shortcut_answer

    resources = load_resources()
    matched_resources = search_resources(message, resources)
    if not matched_resources:
        return make_fallback_answer()

    context = build_context(matched_resources)
    answer = await call_ollama(
        message,
        request.history,
        context,
        has_placeholder_context=any(resource.get("is_placeholder") for resource in matched_resources),
        only_placeholder_context=all(resource.get("is_placeholder") for resource in matched_resources),
    )

    sources = [
        Source(
            title=resource["title"],
            url=resource.get("source_url"),
            source_type=resource["source_type"],
        )
        for resource in matched_resources
    ]

    return ChatResponse(
        answer=answer,
        sources=sources,
        model=OLLAMA_MODEL,
        used_resource_ids=[resource["id"] for resource in matched_resources],
    )
