"""Unit tests for SQLite database operations and models."""

import pytest
import sqlite3
from src.storage.models import PageRecord
from src.storage.db import DatabaseManager


@pytest.fixture
def temp_db(tmp_path):
    """Provides a fresh DatabaseManager backed by a temporary file."""
    db_file = tmp_path / "test_pages.db"
    return DatabaseManager(db_file)


def test_db_initialization(temp_db):
    """Verifies that pages and crawl_log tables are created."""
    with temp_db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        assert "pages" in tables
        assert "crawl_log" in tables


def test_save_page_and_deduplication(temp_db):
    """Ensures pages can be saved and duplicate URLs are cleanly ignored."""
    page1 = PageRecord(
        url="https://docs.arduino.cc/learn/electronics/stepper-motors",
        domain="docs.arduino.cc",
        title="Stepper Motor Guide",
        content_text="Stepper motors convert digital pulses into mechanical shaft rotation.",
        http_status=200,
        content_length=1024,
    )

    # First insert should succeed
    inserted = temp_db.save_page(page1)
    assert inserted is True
    assert temp_db.get_page_count() == 1
    assert temp_db.has_url(page1.url) is True

    # Duplicate insert with identical URL should return False without error
    duplicate_page = PageRecord(
        url="https://docs.arduino.cc/learn/electronics/stepper-motors",
        domain="docs.arduino.cc",
        title="Different Title",
        content_text="Different Content",
        http_status=200,
        content_length=2048,
    )
    inserted_again = temp_db.save_page(duplicate_page)
    assert inserted_again is False
    assert temp_db.get_page_count() == 1


def test_get_all_pages(temp_db):
    """Verifies retrieval of stored pages."""
    p1 = PageRecord(
        url="https://eng.libretexts.org/pid",
        domain="eng.libretexts.org",
        title="PID Controllers",
        content_text="Proportional-Integral-Derivative control fundamentals.",
        http_status=200,
        content_length=512,
    )
    p2 = PageRecord(
        url="https://docs.arduino.cc/ultrasonic",
        domain="docs.arduino.cc",
        title="Ultrasonic Distance Sensor",
        content_text="HC-SR04 ultrasonic sensor tutorial and wiring.",
        http_status=200,
        content_length=768,
    )

    temp_db.save_page(p1)
    temp_db.save_page(p2)

    pages = temp_db.get_all_pages()
    assert len(pages) == 2
    urls = {p.url for p in pages}
    assert p1.url in urls
    assert p2.url in urls


def test_log_crawl_attempt(temp_db):
    """Ensures crawl attempts and errors are properly logged."""
    temp_db.log_crawl_attempt(
        url="https://docs.arduino.cc/broken-link",
        status_code=404,
        error_message="Not Found",
    )
    with temp_db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT url, status_code, error_message FROM crawl_log")
        row = cursor.fetchone()
        assert row["url"] == "https://docs.arduino.cc/broken-link"
        assert row["status_code"] == 404
        assert row["error_message"] == "Not Found"
