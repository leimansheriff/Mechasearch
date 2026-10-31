"""Tests for the Stage 3 Streamlit interface and its integration with search."""

import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import app
from config import settings
from src.indexer.indexer import SearchIndexer
from src.indexer.topics import TOPIC_LABELS, topic_label
from src.search.searcher import SearchEngine, search
from src.storage.db import DatabaseManager
from src.storage.models import PageRecord, SearchResult

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def _ui_pages():
    """Returns an isolated Arduino collection for UI tests."""
    return [
        PageRecord(
            url="https://docs.arduino.cc/hardware/",
            domain="docs.arduino.cc",
            title="Arduino Hardware",
            content_text=(
                "Arduino hardware boards provide digital pins, sensors, and "
                "real-time control for electronics projects."
            ),
            http_status=200,
            content_length=1200,
        ),
        PageRecord(
            url="https://docs.arduino.cc/learn/",
            domain="docs.arduino.cc",
            title="Arduino Learn",
            content_text=(
                "Arduino tutorials cover sensors, servo motors, and control "
                "fundamentals for beginners."
            ),
            http_status=200,
            content_length=1100,
        ),
        PageRecord(
            url="https://eng.libretexts.org/mechanical-engineering",
            domain="eng.libretexts.org",
            title="Mechanical Engineering",
            content_text="Mechanical engineering covers dynamics and machine design.",
            http_status=200,
            content_length=900,
        ),
        PageRecord(
            url="https://eng.libretexts.org/electrical-engineering",
            domain="eng.libretexts.org",
            title="Electrical Engineering",
            content_text="Electrical engineering covers circuits, signals, and power.",
            http_status=200,
            content_length=950,
        ),
    ]


def _build_ui_index(index_dir: Path) -> Path:
    """Builds a small, isolated Arduino collection for UI tests."""
    SearchIndexer(index_dir=index_dir).build_from_pages(_ui_pages(), clean=True)
    return index_dir


@pytest.fixture
def ui_index(tmp_path):
    return _build_ui_index(tmp_path / "ui_index")


@pytest.fixture
def empty_index(tmp_path):
    index_dir = tmp_path / "empty_index"
    ix = SearchIndexer(index_dir=index_dir).open_or_create_index(clean=True)
    ix.close()
    return index_dir


def _run_app(monkeypatch, index_dir: Path, db_path: Path | None = None) -> AppTest:
    """Runs app.py against an isolated settings configuration."""
    database = db_path or index_dir.parent / "test_pages.db"
    database.write_text("")
    monkeypatch.setattr(app.settings, "INDEX_DIR", Path(index_dir))
    monkeypatch.setattr(app.settings, "DB_PATH", Path(database))

    at = AppTest.from_file(str(APP_PATH), default_timeout=30)
    at.run()
    return at


def test_app_imports_and_has_entry_point():
    assert app.APP_TITLE == "MechaSearch"
    assert app.APP_NAME == "MechaSearch"
    assert app.APP_HEADING == "Mechatronics Knowledge Hub"
    assert callable(app.main)
    assert app.SearchEngine is SearchEngine


def test_app_offers_the_six_documented_topic_filters():
    """The UI filter order must match the documented topic vocabulary."""
    assert app.TOPIC_ORDER == (
        "robotics",
        "control_systems",
        "electronics",
        "mechanical_engineering",
        "sensors",
        "embedded_systems",
    )
    assert set(app.TOPIC_ORDER) == set(TOPIC_LABELS)
    assert all(slug in app.TOPIC_COLORS for slug in app.TOPIC_ORDER)


def test_normalize_and_prepare_query():
    assert app.normalize_query("  Arduino hardware  ") == "Arduino hardware"
    assert app.normalize_query(None) == ""
    assert app.normalize_query(123) == ""
    assert app.prepare_query("   ") is None
    assert app.prepare_query("") is None
    assert app.prepare_query(None) is None
    assert app.prepare_query("  sensor ") == "sensor"


def test_limit_is_clamped_to_supported_range():
    assert app.clamp_limit(5) == 5
    assert app.clamp_limit(0) == 1
    assert app.clamp_limit(100) == app.MAX_LIMIT
    assert app.clamp_limit("nonsense") == app.DEFAULT_LIMIT


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://docs.arduino.cc/learn/", "https://docs.arduino.cc/learn/"),
        ("http://example.com/page", "http://example.com/page"),
        ("javascript:alert(1)", None),
        ("ftp://example.com/file", None),
        ("/relative/path", None),
        ("", None),
        (None, None),
    ],
)
def test_safe_http_url(url, expected):
    assert app.safe_http_url(url) == expected


def test_display_text_is_markdown_escaped():
    escaped = app.escape_markdown("<b>**stepper**</b>")
    assert "\\<b\\>" in escaped
    assert "\\*\\*stepper\\*\\*" in escaped


def test_inspect_index_reports_ready_missing_and_empty(ui_index, empty_index, tmp_path):
    ready = app.inspect_index(SearchEngine(index_dir=ui_index))
    assert ready.state == app.INDEX_READY
    assert ready.document_count == 4

    missing = app.inspect_index(SearchEngine(index_dir=tmp_path / "missing"))
    assert missing.state == app.INDEX_MISSING
    assert missing.document_count == 0

    empty = app.inspect_index(SearchEngine(index_dir=empty_index))
    assert empty.state == app.INDEX_EMPTY
    assert empty.document_count == 0


def test_inspect_index_reports_unreadable_index():
    class BrokenEngine:
        def is_index_ready(self):
            return True

        def document_count(self):
            raise RuntimeError("index is unreadable")

    status = app.inspect_index(BrokenEngine())
    assert status.state == app.INDEX_ERROR
    assert "index is unreadable" in status.detail


def test_build_indexer_command_uses_configured_paths(tmp_path):
    command = app.build_indexer_command(
        db_path=tmp_path / "pages.db", index_dir=tmp_path / "whoosh_index"
    )
    assert "-m src.indexer" in command
    assert str(tmp_path / "pages.db") in command
    assert str(tmp_path / "whoosh_index") in command


def test_inspect_database_reports_ready_missing_and_unusable(tmp_path):
    usable = tmp_path / "corpus.db"
    DatabaseManager(usable).save_page(
        PageRecord(
            url="https://docs.arduino.cc/learn/",
            domain="docs.arduino.cc",
            title="Learn",
            content_text="Arduino tutorials.",
            http_status=200,
            content_length=18,
        )
    )
    ready = app.inspect_database(usable)
    assert ready.state == app.DB_READY
    assert ready.page_count == 1

    missing = app.inspect_database(tmp_path / "absent.db")
    assert missing.state == app.DB_MISSING

    # The exact shape of the leftover data/pages.db in this project: a file that
    # exists but cannot rebuild an index.
    leftover = tmp_path / "pages.db"
    leftover.write_text("")
    unusable = app.inspect_database(leftover)
    assert unusable.state == app.DB_UNUSABLE
    assert "pages" in unusable.detail


# The committed index is a build artifact, so these figures change only when the
# corpus is re-crawled and the index rebuilt. If this test fails after a crawl,
# re-run the commands in the README's "Rebuilding the corpus" section and update
# the numbers from the actual output rather than guessing.
SHIPPED_DOCUMENT_COUNT = 65
SHIPPED_DOMAIN_COUNTS = {
    "docs.arduino.cc": 10,
    "eng.libretexts.org": 12,
    "ocw.mit.edu": 12,
    "howtomechatronics.com": 15,
    "en.wikibooks.org": 16,
}
# Every representative query from the Stage E verification list must return at
# least one result from the shipped corpus.
REPRESENTATIVE_QUERIES = (
    "Arduino hardware",
    "PID controller",
    "DC motor control",
    "stepper motor",
    "robotic arm",
    "sensors and actuators",
    "control systems",
    "mechanical design",
)


@pytest.mark.skipif(
    not settings.INDEX_DIR.is_dir(),
    reason="the committed Whoosh index is not present in this checkout",
)
def test_repository_ships_a_searchable_index_and_database():
    """A fresh clone has no crawler run, so the committed index must answer queries."""
    engine = SearchEngine(index_dir=settings.INDEX_DIR)
    try:
        assert engine.document_count() == SHIPPED_DOCUMENT_COUNT
        assert engine.domain_counts() == SHIPPED_DOMAIN_COUNTS
        assert sum(SHIPPED_DOMAIN_COUNTS.values()) == SHIPPED_DOCUMENT_COUNT

        # All six UI topic filters must be backed by real indexed documents.
        topic_counts = engine.topic_counts()
        assert set(topic_counts) == set(app.TOPIC_ORDER)
        assert all(count > 0 for count in topic_counts.values())

        for query in REPRESENTATIVE_QUERIES:
            results = engine.search(query_text=query, limit=5)
            assert results, query
            assert all(result.score > 0.0 for result in results), query

        assert engine.search(query_text="   ", limit=5) == []
        assert engine.search(query_text="zzzznonsense", limit=5) == []
    finally:
        engine.close()

    assert app.inspect_database(settings.DB_PATH).state == app.DB_READY


@pytest.mark.skipif(
    not settings.INDEX_DIR.is_dir(),
    reason="the committed Whoosh index is not present in this checkout",
)
def test_shipped_index_answers_a_topic_filtered_query():
    """The deployed corpus supports real topic filtering, not decorative pills."""
    engine = SearchEngine(index_dir=settings.INDEX_DIR)
    try:
        unfiltered = engine.search("stepper motor", limit=10)
        filtered = engine.search("stepper motor", limit=10, topic="robotics")
        assert filtered
        assert all("robotics" in result.topics for result in filtered)

        # A filter the corpus cannot satisfy returns nothing rather than
        # silently falling back to the unfiltered set.
        assert engine.search("stepper motor", limit=10, topic="not_a_topic") == []
        assert len(filtered) <= len(unfiltered)
    finally:
        engine.close()


def test_build_indexer_command_uses_the_running_interpreter():
    command = app.build_indexer_command()
    assert sys.executable in command
    assert str(settings.DB_PATH) in command
    assert str(settings.INDEX_DIR) in command
    assert "-m src.indexer" in command


def test_streamlit_sidebar_explains_an_unusable_database(monkeypatch, ui_index):
    # _run_app points DB_PATH at a 0-byte file, the situation the app must report.
    at = _run_app(monkeypatch, ui_index)

    assert not at.exception
    assert any(
        "cannot rebuild the index" in info.value for info in at.sidebar.info
    )


def test_execute_search_matches_existing_engine_ranking(ui_index):
    expected = search("Arduino hardware", index_dir=ui_index)
    engine = app.create_search_engine(ui_index)
    try:
        snapshot = app.execute_search(engine, "Arduino hardware", 5)
        assert engine.document_count() == 4
    finally:
        engine.close()

    assert [r.url for r in snapshot.results] == [r.url for r in expected]
    assert [r.score for r in snapshot.results] == pytest.approx(
        [r.score for r in expected]
    )
    assert snapshot.results[0].title == "Arduino Hardware"
    assert snapshot.elapsed_ms >= 0.0


def test_execute_search_handles_zero_results(ui_index):
    engine = app.create_search_engine(ui_index)
    try:
        snapshot = app.execute_search(engine, "PID controller", 5)
    finally:
        engine.close()
    assert snapshot.results == ()


def test_streamlit_app_starts_and_connects_to_existing_index(monkeypatch, ui_index):
    at = _run_app(monkeypatch, ui_index)

    assert not at.exception
    assert any(title.value == app.APP_HEADING for title in at.title)
    assert any(
        metric.label == "Indexed documents" and metric.value == "4"
        for metric in at.metric
    )
    assert at.text_input(key="query_input").value == ""


def test_topic_options_only_offer_topics_the_index_can_answer():
    options = app.topic_options({"embedded_systems": 2, "mechanical_engineering": 1})

    assert options[0] == (app.ALL_TOPICS_LABEL, None)
    assert ("Embedded Systems (2)", "embedded_systems") in options
    assert ("Mechanical Engineering (1)", "mechanical_engineering") in options
    # No indexed document carries this label, so no pill is offered for it.
    assert all(slug != "sensors" for _label, slug in options)
    assert all(slug != "robotics" for _label, slug in options)


def test_topic_options_follow_the_documented_order():
    counts = {slug: 1 for slug in app.TOPIC_ORDER}
    labels = [label for label, _slug in app.topic_options(counts)]

    assert labels == [app.ALL_TOPICS_LABEL] + [
        f"{topic_label(slug)} (1)" for slug in app.TOPIC_ORDER
    ]


def test_collection_summary_is_compact_and_counts_real_entries():
    summary = app.collection_summary(
        63,
        {"docs.arduino.cc": 10, "eng.libretexts.org": 12},
        {"robotics": 9, "sensors": 11},
    )

    assert "63 indexed document(s)" in summary
    assert "2 source site(s)" in summary
    assert "2 topic(s)" in summary


def test_streamlit_search_matches_existing_ranking(monkeypatch, ui_index):
    at = _run_app(monkeypatch, ui_index)
    at.text_input(key="query_input").set_value("Arduino hardware").run()

    assert not at.exception
    assert at.text_input(key="query_input").value == "Arduino hardware"
    metrics = {metric.label: metric.value for metric in at.metric}
    assert metrics["Matching results"] == "2"
    assert metrics["Indexed documents"] == "4"

    expected = search("Arduino hardware", index_dir=ui_index)
    headings = [
        markdown.value
        for markdown in at.markdown
        if markdown.value.startswith("#### ")
    ]
    assert headings == [
        f"#### {rank}. {result.title}"
        for rank, result in enumerate(expected, start=1)
    ]


def test_streamlit_refresh_reopens_rebuilt_index(monkeypatch, ui_index):
    at = _run_app(monkeypatch, ui_index)
    assert any(
        metric.label == "Indexed documents" and metric.value == "4"
        for metric in at.metric
    )

    extra_page = PageRecord(
        url="https://docs.arduino.cc/robotics/",
        domain="docs.arduino.cc",
        title="Arduino Robotics",
        content_text="Arduino robotics projects combine motors, sensors, and control.",
        http_status=200,
        content_length=1000,
    )
    SearchIndexer(index_dir=ui_index).build_from_pages(
        _ui_pages() + [extra_page], clean=True
    )

    at.button(key="refresh_index_button").click().run()

    assert not at.exception
    assert any(
        metric.label == "Indexed documents" and metric.value == "5"
        for metric in at.metric
    )


def test_streamlit_zero_result_query_is_clean(monkeypatch, ui_index):
    at = _run_app(monkeypatch, ui_index)
    at.text_input(key="query_input").set_value("PID controller").run()

    assert not at.exception
    assert any(
        metric.label == "Matching results" and metric.value == "0"
        for metric in at.metric
    )
    assert any("No documents matched" in warning.value for warning in at.warning)


def test_streamlit_blank_query_does_not_search(monkeypatch, ui_index):
    at = _run_app(monkeypatch, ui_index)
    at.text_input(key="query_input").set_value("   ").run()

    assert not at.exception
    assert any(
        "Please enter a search query" in warning.value for warning in at.warning
    )
    assert not any(metric.label == "Matching results" for metric in at.metric)


def test_streamlit_missing_index_has_actionable_message(monkeypatch, tmp_path):
    at = _run_app(monkeypatch, tmp_path / "missing_index")

    assert not at.exception
    assert any("missing" in error.value.lower() for error in at.error)
    assert any("src.indexer" in code.value for code in at.code)


def test_streamlit_empty_index_has_actionable_message(monkeypatch, empty_index):
    at = _run_app(monkeypatch, empty_index)

    assert not at.exception
    assert any("contains no documents" in warning.value for warning in at.warning)
    assert any("src.indexer" in code.value for code in at.code)


def test_streamlit_malformed_query_does_not_crash(monkeypatch, ui_index):
    at = _run_app(monkeypatch, ui_index)
    at.text_input(key="query_input").set_value("PID AND (").run()

    assert not at.exception
    assert any(
        "No documents matched" in warning.value for warning in at.warning
    )


def test_streamlit_search_exception_is_handled(monkeypatch, ui_index):
    def failing_search(self, *args, **kwargs):
        raise RuntimeError("simulated search failure")

    monkeypatch.setattr(SearchEngine, "search", failing_search)
    at = _run_app(monkeypatch, ui_index)
    at.text_input(key="query_input").set_value("control").run()

    assert not at.exception
    assert any("could not be completed" in error.value for error in at.error)


def test_format_result_meta_shows_domain_and_relevance_score():
    result = SearchResult(
        url="https://docs.arduino.cc/learn/",
        title="Arduino Learn",
        snippet="Snippet text.",
        score=1.23456,
        domain="docs.arduino.cc",
    )
    assert app.format_result_meta(result) == (
        "docs.arduino.cc · Relevance score (BM25F): 1.235"
    )


def test_format_result_meta_escapes_untrusted_domain():
    result = SearchResult(
        url="https://example.com/",
        title="Title",
        snippet="",
        score=2.0,
        domain="*<b>evil</b>",
    )
    meta = app.format_result_meta(result)
    assert r"\*\<b\>evil\</b\>" in meta
    assert "2.000" in meta


def test_streamlit_example_query_buttons_are_present_and_run_a_search(
    monkeypatch, ui_index
):
    at = _run_app(monkeypatch, ui_index)
    example_keys = [
        button.key for button in at.button if button.key.startswith("example_query_")
    ]
    assert example_keys == [
        f"example_query_{index}" for index in range(len(app.EXAMPLE_QUERIES))
    ]

    at.button(key="example_query_0").click().run()

    assert not at.exception
    assert app.EXAMPLE_QUERIES[0] == "Arduino hardware"
    assert at.text_input(key="query_input").value == "Arduino hardware"
    metrics = {metric.label: metric.value for metric in at.metric}
    assert metrics["Matching results"] == "2"


def test_streamlit_results_render_tappable_http_links(monkeypatch, ui_index):
    at = _run_app(monkeypatch, ui_index)
    at.text_input(key="query_input").set_value("Arduino hardware").run()

    assert not at.exception
    expected = search("Arduino hardware", index_dir=ui_index)
    link_buttons = list(at.link_button)
    assert [button.value for button in link_buttons] == [
        "Open original page" for _ in expected
    ]
    assert [button.url for button in link_buttons] == [
        result.url for result in expected
    ]
    assert all(button.url.startswith("https://") for button in link_buttons)


def test_streamlit_sidebar_keeps_statistics_and_controls(monkeypatch, ui_index):
    at = _run_app(monkeypatch, ui_index)
    sidebar = at.sidebar

    assert not at.exception
    assert any(metric.label == "Indexed documents" for metric in sidebar.metric)
    assert sidebar.button(key="clear_search_button") is not None
    assert sidebar.button(key="refresh_index_button") is not None
    # Compact per-source and per-topic statistics come from the index itself.
    sidebar_text = "\n".join(markdown.value for markdown in sidebar.markdown)
    assert "docs.arduino.cc" in sidebar_text
    assert "eng.libretexts.org" in sidebar_text
    assert "Embedded Systems" in sidebar_text


def test_streamlit_topic_filter_offers_only_indexed_topics_with_counts(
    monkeypatch, ui_index
):
    at = _run_app(monkeypatch, ui_index)

    assert not at.exception
    pills = at.pills(key="topic_filter")
    assert pills.value == app.ALL_TOPICS_LABEL
    # The four fixture pages classify as Embedded Systems (2), Electronics (1)
    # and Mechanical Engineering (1); the count is shown in the pill label.
    assert "Embedded Systems (2)" in pills.options
    assert "Electronics (1)" in pills.options
    assert "Mechanical Engineering (1)" in pills.options
    assert "Robotics (1)" not in pills.options


def test_streamlit_topic_filter_restricts_the_search(monkeypatch, ui_index):
    at = _run_app(monkeypatch, ui_index)
    at.text_input(key="query_input").set_value("Arduino hardware").run()
    assert {m.label: m.value for m in at.metric}["Matching results"] == "2"

    at.pills(key="topic_filter").set_value("Mechanical Engineering (1)").run()

    assert not at.exception
    # The filter genuinely filters: the same query now matches nothing, because
    # no Mechanical Engineering document discusses Arduino hardware.
    assert {m.label: m.value for m in at.metric}["Matching results"] == "0"
    assert any("No documents matched" in warning.value for warning in at.warning)
    assert any("Mechanical Engineering" in warning.value for warning in at.warning)


def test_streamlit_topic_filter_keeps_documents_that_carry_the_label(
    monkeypatch, ui_index
):
    at = _run_app(monkeypatch, ui_index)
    at.text_input(key="query_input").set_value("Arduino hardware").run()

    at.pills(key="topic_filter").set_value("Embedded Systems (2)").run()

    assert not at.exception
    assert {m.label: m.value for m in at.metric}["Matching results"] == "2"
    expected = search("Arduino hardware", index_dir=ui_index, topic="embedded_systems")
    headings = [
        markdown.value
        for markdown in at.markdown
        if markdown.value.startswith("#### ")
    ]
    assert headings == [
        f"#### {rank}. {result.title}"
        for rank, result in enumerate(expected, start=1)
    ]


def test_streamlit_result_cards_show_topic_badges(monkeypatch, ui_index):
    at = _run_app(monkeypatch, ui_index)
    at.text_input(key="query_input").set_value("Arduino hardware").run()

    assert not at.exception
    # st.badge renders the color-badge Markdown directive; the label is the same
    # vocabulary the indexer wrote, so the card and the filter agree.
    rendered = "\n".join(markdown.value for markdown in at.markdown)
    assert f"badge[{topic_label('embedded_systems')}]" in rendered


def test_streamlit_header_reports_the_collection_size(monkeypatch, ui_index):
    at = _run_app(monkeypatch, ui_index)

    assert not at.exception
    captions = "\n".join(caption.value for caption in at.caption)
    assert "4 indexed document(s)" in captions
    assert "2 source site(s)" in captions


def test_execute_search_applies_a_topic_filter(ui_index):
    engine = app.create_search_engine(ui_index)
    try:
        unfiltered = app.execute_search(engine, "Arduino hardware", 5)
        filtered = app.execute_search(engine, "Arduino hardware", 5, "sensors")
    finally:
        engine.close()

    assert filtered.topic == "sensors"
    assert len(unfiltered.results) == 2
    assert filtered.results == ()


def test_execute_search_records_the_active_filter(ui_index):
    engine = app.create_search_engine(ui_index)
    try:
        snapshot = app.execute_search(engine, "Arduino hardware", 5, "sensors")
    finally:
        engine.close()
    assert snapshot.topic == "sensors"
    assert app._active_topic_label(snapshot.topic) == "Sensors"
