"""Unit tests for the Whoosh full-text indexer."""

import pytest
from src.indexer.indexer import SearchIndexer
from src.indexer.schema import create_search_schema
from src.indexer.topics import TOPIC_LABELS
from src.storage.db import DatabaseManager
from src.storage.models import PageRecord


@pytest.fixture
def sample_mechatronics_pages():
    """Provides realistic mechatronics test page fixtures."""
    return [
        PageRecord(
            url="https://docs.arduino.cc/learn/electronics/stepper-motor-guide",
            domain="docs.arduino.cc",
            title="Stepper Motor and Driver Basics",
            content_text="Stepper motors convert digital electrical pulses into mechanical shaft rotation for robotics.",
            http_status=200,
            content_length=1024,
            crawled_at="2026-10-19 12:00:00",
        ),
        PageRecord(
            url="https://eng.libretexts.org/Control_Systems/PID_Controller_Design",
            domain="eng.libretexts.org",
            title="PID Controller Tuning and Closed-Loop Stability",
            content_text="Proportional Integral Derivative control calculates error values between desired setpoints and process variables.",
            http_status=200,
            content_length=2048,
            crawled_at="2026-10-19 12:05:00",
        ),
        PageRecord(
            url="https://docs.arduino.cc/hardware/sensors/ultrasonic-distance",
            domain="docs.arduino.cc",
            title="Ultrasonic Distance Sensor Interfacing",
            content_text="Ultrasonic transducers measure distance by timing acoustic time-of-flight pulses for obstacle avoidance in autonomous robotics.",
            http_status=200,
            content_length=1500,
            crawled_at="2026-10-19 12:10:00",
        ),
        PageRecord(
            url="https://eng.libretexts.org/Industrial_Automation/PLC_Ladder_Logic",
            domain="eng.libretexts.org",
            title="Programmable Logic Controllers and Ladder Logic",
            content_text="PLCs execute cyclic scan loops to control industrial actuators, relays, and manufacturing assembly lines.",
            http_status=200,
            content_length=1800,
            crawled_at="2026-10-19 12:15:00",
        ),
    ]


def test_build_index_from_multiple_pages(tmp_path, sample_mechatronics_pages):
    """Verifies that multiple eligible pages are indexed successfully."""
    index_dir = tmp_path / "index"
    indexer = SearchIndexer(index_dir=index_dir)

    report = indexer.build_from_pages(sample_mechatronics_pages, clean=True)

    assert report.total_pages == 4
    assert report.indexed == 4
    assert report.skipped == 0
    assert report.failed == 0

    # Verify documents can be read from the index
    ix = indexer.open_or_create_index(clean=False)
    try:
        assert ix.doc_count() == 4
    finally:
        ix.close()


def test_indexer_deduplication(tmp_path):
    """Verifies that duplicate URLs in the input collection are not duplicated in the index."""
    index_dir = tmp_path / "index_dedup"
    indexer = SearchIndexer(index_dir=index_dir)

    duplicate_pages = [
        PageRecord(
            url="https://docs.arduino.cc/sensors/encoder",
            domain="docs.arduino.cc",
            title="Rotary Encoder Basics",
            content_text="Rotary encoders measure angular displacement.",
            http_status=200,
            content_length=500,
        ),
        PageRecord(
            url="https://docs.arduino.cc/sensors/encoder",
            domain="docs.arduino.cc",
            title="Rotary Encoder Basics (Duplicate)",
            content_text="Duplicate text for rotary encoders.",
            http_status=200,
            content_length=500,
        ),
    ]

    report = indexer.build_from_pages(duplicate_pages, clean=True)
    assert report.total_pages == 2
    assert report.indexed == 1
    assert report.skipped == 1

    ix = indexer.open_or_create_index(clean=False)
    try:
        assert ix.doc_count() == 1
    finally:
        ix.close()


def test_indexer_handles_empty_db(tmp_path):
    """Verifies safe handling when indexing an empty SQLite database."""
    db_file = tmp_path / "empty.db"
    db_mgr = DatabaseManager(db_file)

    index_dir = tmp_path / "empty_index"
    indexer = SearchIndexer(index_dir=index_dir)

    report = indexer.build_from_database(db_mgr, clean=True)
    assert report.total_pages == 0
    assert report.indexed == 0
    assert report.skipped == 0
    assert report.failed == 0


def test_indexer_skips_ineligible_pages(tmp_path):
    """Ensures non-200 pages and empty-content pages are skipped."""
    index_dir = tmp_path / "ineligible_index"
    indexer = SearchIndexer(index_dir=index_dir)

    pages = [
        PageRecord(
            url="https://docs.arduino.cc/error-404",
            domain="docs.arduino.cc",
            title="Not Found",
            content_text="Error 404 page.",
            http_status=404,
            content_length=20,
        ),
        PageRecord(
            url="https://docs.arduino.cc/empty",
            domain="docs.arduino.cc",
            title="Empty Content",
            content_text="    ",
            http_status=200,
            content_length=0,
        ),
        PageRecord(
            url="https://docs.arduino.cc/valid",
            domain="docs.arduino.cc",
            title="Valid Document",
            content_text="Legitimate mechatronics content on sensors.",
            http_status=200,
            content_length=100,
        ),
    ]

    report = indexer.build_from_pages(pages, clean=True)
    assert report.total_pages == 3
    assert report.indexed == 1
    assert report.skipped == 2


def test_reopen_existing_index(tmp_path, sample_mechatronics_pages):
    """Verifies that an existing index can be reopened without data loss."""
    index_dir = tmp_path / "reopen_index"
    indexer = SearchIndexer(index_dir=index_dir)
    indexer.build_from_pages(sample_mechatronics_pages[:2], clean=True)

    # Reopen with clean=False
    reopened_ix = indexer.open_or_create_index(clean=False)
    try:
        assert reopened_ix.doc_count() == 2
    finally:
        reopened_ix.close()


def test_indexer_stores_topic_labels(tmp_path):
    """Topic labels are computed at index time and stored with the document."""
    index_dir = tmp_path / "topics_index"
    indexer = SearchIndexer(index_dir=index_dir)
    url = "https://docs.arduino.cc/learn/electronics/stepper-motors/"

    report = indexer.build_from_pages(
        [
            PageRecord(
                url=url,
                domain="docs.arduino.cc",
                title="Stepper Motor and Driver Basics",
                content_text=(
                    "A transistor H-bridge circuit switches motor current; the "
                    "microcontroller firmware drives it."
                ),
                http_status=200,
                content_length=120,
            )
        ],
        clean=True,
    )
    assert report.indexed == 1
    assert report.unclassified == 0

    ix = indexer.open_or_create_index(clean=False)
    try:
        with ix.searcher() as searcher:
            stored = searcher.document(url=url)["topics"]
    finally:
        ix.close()

    assert stored
    slugs = stored.split(",")
    assert slugs == sorted(set(slugs), key=slugs.index)  # no duplicates, order kept
    assert all(slug in TOPIC_LABELS for slug in slugs)


def test_indexer_counts_pages_it_cannot_classify(tmp_path):
    """An unlabelled page is counted rather than silently given a wrong topic."""
    index_dir = tmp_path / "unclassified_index"
    indexer = SearchIndexer(index_dir=index_dir)

    report = indexer.build_from_pages(
        [
            PageRecord(
                url="https://example.edu/notes",
                domain="example.edu",
                title="Weekly notes",
                content_text="Reminder to order more coffee for the lab.",
                http_status=200,
                content_length=44,
            )
        ],
        clean=True,
    )

    assert report.indexed == 1
    assert report.unclassified == 1


def test_rebuild_index_reflects_updated_or_deleted_source(tmp_path):
    """
    Verifies that rebuilding the index cleanly removes deleted pages
    and updates modified content from the database.
    """
    db_file = tmp_path / "source.db"
    db_mgr = DatabaseManager(db_file)

    p1 = PageRecord(
        url="https://docs.arduino.cc/actuator",
        domain="docs.arduino.cc",
        title="Original Actuator Title",
        content_text="Servo motor fundamentals for robotic arms.",
        http_status=200,
        content_length=200,
    )
    p2 = PageRecord(
        url="https://docs.arduino.cc/deprecated",
        domain="docs.arduino.cc",
        title="Obsolete Article",
        content_text="This article should be removed later.",
        http_status=200,
        content_length=150,
    )
    db_mgr.save_page(p1)
    db_mgr.save_page(p2)

    index_dir = tmp_path / "rebuild_test_index"
    indexer = SearchIndexer(index_dir=index_dir)
    r1 = indexer.build_from_database(db_mgr, clean=True)
    assert r1.indexed == 2

    # Now remove p2 and update p1 in SQLite
    with db_mgr._get_connection() as conn:
        conn.execute("DELETE FROM pages WHERE url = ?", (p2.url,))
        conn.execute(
            "UPDATE pages SET title = ? WHERE url = ?",
            ("Updated Actuator Title", p1.url),
        )
        conn.commit()

    # Rebuild index from modified DB
    r2 = indexer.build_from_database(db_mgr, clean=True)
    assert r2.indexed == 1

    ix = indexer.open_or_create_index(clean=False)
    try:
        assert ix.doc_count() == 1
        with ix.searcher() as s:
            doc = s.document(url=p1.url)
            assert doc["title"] == "Updated Actuator Title"
            assert s.document(url=p2.url) is None
    finally:
        ix.close()
