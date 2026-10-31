import logging
import os
import sqlite3
import sys
import time
import traceback
import webbrowser

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import flet as ft

from config import settings
from src.indexer.topics import TOPIC_LABELS, topic_label
from src.search.searcher import SearchEngine
from src.storage.models import SearchResult

logger = logging.getLogger(__name__)

# Application identity
APP_NAME = "MechaSearch"
APP_HEADING = "Mechatronics Knowledge Hub"
APP_TAGLINE = (
    "A focused search engine for mechatronics, robotics, control systems, "
    "electronics and mechanical engineering."
)

DEFAULT_LIMIT = 5
LIMIT_OPTIONS = [5, 10, 20]
EXAMPLE_QUERIES = ["Arduino hardware", "PID controller", "stepper motor", "sensor"]

TOPIC_ORDER = (
    "robotics",
    "control_systems",
    "electronics",
    "mechanical_engineering",
    "sensors",
    "embedded_systems",
)
TOPIC_COLORS: Dict[str, str] = {
    "robotics": ft.Colors.PURPLE,
    "control_systems": ft.Colors.BLUE,
    "electronics": ft.Colors.ORANGE,
    "mechanical_engineering": ft.Colors.GREY,
    "sensors": ft.Colors.GREEN,
    "embedded_systems": ft.Colors.YELLOW,
}
ALL_TOPICS_LABEL = "All topics"

INDEX_READY, INDEX_MISSING, INDEX_EMPTY, INDEX_ERROR = "ready", "missing", "empty", "error"


@dataclass(frozen=True)
class IndexStatus:
    state: str
    document_count: int = 0
    detail: str = ""


@dataclass(frozen=True)
class SearchSnapshot:
    query: str
    results: Tuple[SearchResult, ...]
    elapsed_ms: float
    limit: int
    topic: Optional[str] = None


# --- Backend Helpers ---
def normalize_query(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def safe_http_url(value: object) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    parsed = urlparse(candidate)
    return candidate if parsed.scheme.lower() in {"http", "https"} and parsed.netloc else None


def create_search_engine(index_dir: str | Path) -> SearchEngine:
    return SearchEngine(index_dir=index_dir)


def inspect_index(engine: SearchEngine) -> IndexStatus:
    try:
        if not engine.is_index_ready():
            return IndexStatus(INDEX_MISSING)
        count = engine.document_count()
        return IndexStatus(INDEX_EMPTY) if count <= 0 else IndexStatus(INDEX_READY, document_count=count)
    except Exception as exc:
        return IndexStatus(INDEX_ERROR, detail=str(exc))


def execute_search(
    engine: SearchEngine, query: str, limit: int, topic: Optional[str] = None
) -> SearchSnapshot:
    started = time.perf_counter()
    results = engine.search(query_text=query, limit=limit, topic=topic)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return SearchSnapshot(
        query=query, results=tuple(results), elapsed_ms=elapsed_ms, limit=limit, topic=topic
    )


def topic_options(topic_counts: Dict[str, int]) -> List[Tuple[str, Optional[str]]]:
    options: List[Tuple[str, Optional[str]]] = [(ALL_TOPICS_LABEL, None)]
    for slug in TOPIC_ORDER:
        if topic_counts.get(slug, 0) > 0:
            options.append((f"{topic_label(slug)} ({topic_counts[slug]})", slug))
    return options


# --- Flet UI Layout & Logic ---
def main(page: ft.Page):
    page.title = APP_NAME
    page.theme_mode = ft.ThemeMode.SYSTEM
    page.padding = 20
    page.scroll = ft.ScrollMode.AUTO

    engine: Optional[SearchEngine] = None
    status = IndexStatus(INDEX_ERROR, detail="Uninitialized")
    topic_counts: Dict[str, int] = {}
    domain_counts: Dict[str, int] = {}

    # 1. Initialize Engine safely
    try:
        engine = create_search_engine(settings.INDEX_DIR)
        status = inspect_index(engine)
        if status.state == INDEX_READY:
            topic_counts = engine.topic_counts()
            domain_counts = engine.domain_counts()
    except Exception as e:
        logger.exception("Init error")
        status = IndexStatus(INDEX_ERROR, detail=str(e))

    selected_topic_slug: Optional[str] = None

    # 2. UI Components
    search_input = ft.TextField(
        label="Search topics, components, techniques...",
        width=300,
        on_submit=lambda _: perform_search(),
    )

    limit_dropdown = ft.Dropdown(
        label="Results",
        options=[ft.dropdown.Option(str(x)) for x in LIMIT_OPTIONS],
        value=str(DEFAULT_LIMIT),
        width=100,
    )
    limit_dropdown.on_change = lambda _: perform_search()

    results_container = ft.Column(spacing=15)
    metrics_row = ft.Row()

    def set_topic(slug: Optional[str]):
        nonlocal selected_topic_slug
        selected_topic_slug = slug
        perform_search()

    # Topic Filter Row
    topic_chips = [
        ft.Chip(
            label=ft.Text(label),
            on_click=lambda _, s=slug: set_topic(s),
        )
        for label, slug in topic_options(topic_counts)
    ]

    # Example Queries
    def use_example(query_text: str):
        search_input.value = query_text
        perform_search()

    example_buttons = [
        ft.OutlinedButton(
            content=ft.Text(ex),
            on_click=lambda _, q=ex: use_example(q),
        )
        for ex in EXAMPLE_QUERIES
    ]

    # Result Card Generator (nested inside main so it can access 'page')
    def create_result_card(result: SearchResult, rank: int) -> ft.Card:
        badges = [
            ft.Container(
                content=ft.Text(topic_label(t), size=12, color=ft.Colors.WHITE),
                bgcolor=TOPIC_COLORS.get(t, ft.Colors.BLUE),
                padding=8,
                border_radius=10,
            )
            for t in (result.topics or [])
        ]

        url = safe_http_url(result.url)
        action_button = (
            ft.OutlinedButton(
                content=ft.Text("Open original page"),
                url=url,
            )
            if url
            else ft.Text("Invalid URL", color=ft.Colors.RED)
        )

        return ft.Card(
            content=ft.Container(
                padding=15,
                content=ft.Column(
                    [
                        ft.Text(
                            f"{rank}. {result.title or 'Untitled'}",
                            size=18,
                            weight=ft.FontWeight.BOLD,
                        ),
                        ft.Text(
                            f"{result.domain or 'unknown'} · Score: {result.score:.3f}",
                            color=ft.Colors.GREY,
                            size=12,
                        ),
                        ft.Row(badges, wrap=True),
                        ft.Text(result.snippet or "No snippet available."),
                        action_button,
                    ]
                ),
            )
        )

    # 3. Core Search Execution
    def perform_search():
        if engine is None:
            results_container.controls.clear()
            results_container.controls.append(
                ft.Text("Search engine is not initialized.", color=ft.Colors.RED)
            )
            page.update()
            return

        query = normalize_query(search_input.value)
        results_container.controls.clear()
        metrics_row.controls.clear()

        if not query:
            results_container.controls.append(
                ft.Text("Please enter a search query.", color=ft.Colors.RED)
            )
            page.update()
            return

        try:
            limit_val = limit_dropdown.value or str(DEFAULT_LIMIT)
            limit = int(limit_val)
            snapshot = execute_search(engine, query, limit, selected_topic_slug)

            # Metrics
            metrics_row.controls = [
                ft.Text(
                    f"Results: {len(snapshot.results)} | Time: {snapshot.elapsed_ms:.1f}ms | Indexed: {status.document_count}",
                    weight=ft.FontWeight.BOLD,
                )
            ]

            if not snapshot.results:
                results_container.controls.append(
                    ft.Text("No documents matched your query.", color=ft.Colors.ORANGE)
                )
            else:
                for rank, result in enumerate(snapshot.results, start=1):
                    results_container.controls.append(create_result_card(result, rank))

        except Exception as e:
            results_container.controls.append(
                ft.Text(f"Search failed: {e}", color=ft.Colors.RED)
            )

        page.update()

    # 4. Assemble the Page
    page.add(
        ft.Text(APP_HEADING, size=28, weight=ft.FontWeight.BOLD),
        ft.Text(f"{APP_NAME} · {APP_TAGLINE}", size=14, color=ft.Colors.GREY),
        ft.Divider(),
        ft.Row(
            [
                search_input,
                limit_dropdown,
                ft.FilledButton(
                    content=ft.Text("Search"),
                    on_click=lambda _,: perform_search(),
                ),
            ]
        ),
        ft.Text("Topics:", weight=ft.FontWeight.BOLD),
        ft.Row(topic_chips, wrap=True),
        ft.Text("Examples:", weight=ft.FontWeight.BOLD),
        ft.Row(example_buttons, wrap=True),
        ft.Divider(),
        metrics_row,
        results_container,
    )


if __name__ == "__main__":
    ft.run(main)
