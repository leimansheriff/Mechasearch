"""Unit tests for the full-text search engine and BM25F ranking."""

import pytest
from src.indexer.indexer import SearchIndexer
from src.search.searcher import SearchEngine, search
from src.storage.models import PageRecord, SearchResult


TOPIC_FIXTURE_URLS = {
    "control": "https://eng.libretexts.org/pid-controller-design",
    "electronics": "https://docs.arduino.cc/h-bridge-motor-driver",
    "robotics": "https://docs.arduino.cc/stepper-actuators",
    "sensors": "https://docs.arduino.cc/rotary-encoder-sensor",
}


@pytest.fixture
def arduino_only_index(tmp_path):
    """A four-page Arduino collection with no PID material anywhere in it."""
    index_dir = tmp_path / "arduino_only_index"
    indexer = SearchIndexer(index_dir=index_dir)

    pages = [
        PageRecord(
            url="https://docs.arduino.cc/learn/",
            domain="docs.arduino.cc",
            title="Learn",
            content_text=(
                "Arduino tutorials cover servo motors, sensors, and real-time control "
                "for beginner electronics projects."
            ),
            http_status=200,
            content_length=1200,
        ),
        PageRecord(
            url="https://docs.arduino.cc/hardware/",
            domain="docs.arduino.cc",
            title="Hardware",
            content_text=(
                "Arduino boards provide digital pins and control for sensors and motors. "
                "Browse the hardware family and accessories."
            ),
            http_status=200,
            content_length=1100,
        ),
        PageRecord(
            url="https://eng.libretexts.org/mechanical-engineering",
            domain="eng.libretexts.org",
            title="Mechanical Engineering",
            content_text="Mechanical engineering covers dynamics, materials, and machine design.",
            http_status=200,
            content_length=900,
        ),
        PageRecord(
            url="https://eng.libretexts.org/electrical-engineering",
            domain="eng.libretexts.org",
            title="Electrical Engineering",
            content_text="Electrical engineering covers circuits, signals, and power systems.",
            http_status=200,
            content_length=950,
        ),
    ]

    indexer.build_from_pages(pages, clean=True)
    return index_dir


@pytest.fixture
def mechatronics_index(tmp_path):
    """Creates a temporary indexed collection of mechatronics documents."""
    index_dir = tmp_path / "search_index"
    indexer = SearchIndexer(index_dir=index_dir)

    pages = [
        # Document 1: Has "PID Controller" in title and control discussion in body
        PageRecord(
            url="https://eng.libretexts.org/pid-controller-design",
            domain="eng.libretexts.org",
            title="PID Controller Tuning and Closed Loop Feedback",
            content_text="Proportional Integral Derivative control stabilizes plant transfer functions.",
            http_status=200,
            content_length=1500,
        ),
        # Document 2: Has "PID" mentioned only once in the body, title is unrelated
        PageRecord(
            url="https://docs.arduino.cc/h-bridge-motor-driver",
            domain="docs.arduino.cc",
            title="H-Bridge DC Motor Driver Circuit",
            content_text="An H-bridge circuit controls DC motor direction and PWM speed. A PID controller may be used for speed regulation.",
            http_status=200,
            content_length=1200,
        ),
        # Document 3: Stepper motor and robotics
        PageRecord(
            url="https://docs.arduino.cc/stepper-actuators",
            domain="docs.arduino.cc",
            title="Stepper Motor Microstepping Actuators",
            content_text="Microstepping reduces resonance and improves positional accuracy in robotics and 3D printing.",
            http_status=200,
            content_length=1400,
        ),
        # Document 4: Sensors (ultrasonic & encoder)
        PageRecord(
            url="https://docs.arduino.cc/rotary-encoder-sensor",
            domain="docs.arduino.cc",
            title="Rotary Encoder Angular Position Sensor",
            content_text="Quadrature optical encoders output square wave pulses to detect rotation and velocity in mechatronic joints.",
            http_status=200,
            content_length=1600,
        ),
        # Document 5: PLCs and industrial automation
        PageRecord(
            url="https://eng.libretexts.org/plc-automation",
            domain="eng.libretexts.org",
            title="Industrial PLC Automation Systems",
            content_text="Programmable Logic Controllers execute ladder diagrams to orchestrate pneumatic actuators and factory lines.",
            http_status=200,
            content_length=1700,
        ),
    ]

    indexer.build_from_pages(pages, clean=True)
    return index_dir


def test_search_title_match(mechatronics_index):
    """Verifies queries matching document titles."""
    results = search("Rotary Encoder", index_dir=mechatronics_index)
    assert len(results) > 0
    top_hit = results[0]
    assert "Rotary Encoder" in top_hit.title
    assert top_hit.url == "https://docs.arduino.cc/rotary-encoder-sensor"


def test_search_content_match(mechatronics_index):
    """Verifies queries matching words located in body content."""
    results = search("resonance microstepping", index_dir=mechatronics_index)
    assert len(results) > 0
    assert "Stepper Motor" in results[0].title


def test_title_match_ranks_above_body_match(mechatronics_index):
    """
    Core Ranking Requirement:
    Document 1 has 'PID Controller' in its title (boosted 2.5x).
    Document 2 mentions 'PID' only in its body.
    For query 'PID Controller', Document 1 must rank first with a higher BM25F score.
    """
    results = search("PID Controller", limit=5, index_dir=mechatronics_index)
    assert len(results) >= 2

    first_result = results[0]
    second_result = results[1]

    assert first_result.url == "https://eng.libretexts.org/pid-controller-design"
    assert second_result.url == "https://docs.arduino.cc/h-bridge-motor-driver"
    assert first_result.score > second_result.score


def test_search_unmatched_query_returns_empty(mechatronics_index):
    """Verifies that queries with no matching documents return an empty list."""
    results = search("quantum astrophysics supercollider", index_dir=mechatronics_index)
    assert results == []


def test_search_blank_or_whitespace_query(mechatronics_index):
    """Ensures empty, whitespace, or invalid queries return an empty list."""
    assert search("", index_dir=mechatronics_index) == []
    assert search("     ", index_dir=mechatronics_index) == []
    assert search(None, index_dir=mechatronics_index) == []


def test_search_on_empty_or_missing_index(tmp_path):
    """Ensures search handles non-existent or uninitialized indexes gracefully."""
    non_existent = tmp_path / "does_not_exist"
    engine = SearchEngine(index_dir=non_existent)
    assert engine.is_index_ready() is False
    assert engine.search("robotics") == []


def test_search_returns_expected_fields(mechatronics_index):
    """Verifies that all SearchResult fields are present and valid."""
    results = search("actuators", limit=1, index_dir=mechatronics_index)
    assert len(results) == 1
    hit = results[0]

    assert isinstance(hit, SearchResult)
    assert hit.url.startswith("http")
    assert hit.domain in ("docs.arduino.cc", "eng.libretexts.org")
    assert len(hit.title) > 0
    assert isinstance(hit.score, float)
    assert hit.score > 0.0
    assert len(hit.snippet) > 0


def test_search_malformed_syntax_query(mechatronics_index):
    """Verifies graceful handling of malformed search syntax without crashing."""
    malformed_queries = [
        "PID AND (",
        "))))",
        "AND OR NOT",
        "sensor:::",
        "stepper ~~~ ^^^",
    ]
    for q in malformed_queries:
        # Should not raise QueryParserError
        results = search(q, index_dir=mechatronics_index)
        assert isinstance(results, list)


def test_search_preserves_technical_acronyms(mechatronics_index):
    """Ensures technical engineering abbreviations (PID, PLC) match accurately."""
    pid_res = search("PID", index_dir=mechatronics_index)
    assert len(pid_res) >= 1
    assert any("PID" in r.title for r in pid_res)

    plc_res = search("PLC", index_dir=mechatronics_index)
    assert len(plc_res) >= 1
    assert any("PLC" in r.title for r in plc_res)


def test_matching_technical_query_returns_relevant_documents(mechatronics_index):
    """A technical query returns the documents that actually discuss it."""
    results = search("stepper motor", index_dir=mechatronics_index)
    assert results
    assert results[0].url == "https://docs.arduino.cc/stepper-actuators"
    assert all(r.score > 0.0 for r in results)


def test_absent_technical_term_returns_no_unrelated_results(arduino_only_index):
    """
    Regression for the reported bug: '"PID controller" returned Arduino pages
    with 0.000 scores even though the collection contains no PID material.
    """
    assert search("PID controller", index_dir=arduino_only_index) == []
    assert search("PID", index_dir=arduino_only_index) == []


def test_partial_match_policy_one_matching_one_absent_term(mechatronics_index):
    """
    Documented policy:
    - If any query term is absent from the whole collection, there is no
      meaningful answer, so the result list is empty.
    - If every query term exists in the collection, documents may still match
      only a subset of those terms and are returned as partial matches.
    """
    # 'quantum' is absent from every document, so the query is not meaningful.
    assert search("stepper quantum", index_dir=mechatronics_index) == []

    # Both terms exist somewhere in the collection; each result matches one.
    results = search("stepper pneumatic", index_dir=mechatronics_index)
    urls = {r.url for r in results}
    assert urls == {
        "https://docs.arduino.cc/stepper-actuators",
        "https://eng.libretexts.org/plc-automation",
    }
    assert all(r.score > 0.0 for r in results)


def test_scores_are_positive_and_ranked(mechatronics_index):
    """BM25F produces positive, descending scores for matching documents."""
    results = search("control", index_dir=mechatronics_index)
    assert len(results) >= 2
    assert all(r.score > 0.0 for r in results)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_title_match_receives_higher_score(tmp_path):
    """A term in the title outranks the same term in body content."""
    index_dir = tmp_path / "title_boost_index"
    indexer = SearchIndexer(index_dir=index_dir)
    indexer.build_from_pages(
        [
            PageRecord(
                url="https://docs.arduino.cc/calibration-title",
                domain="docs.arduino.cc",
                title="Calibration Reference",
                content_text="General notes for workshop equipment.",
                http_status=200,
                content_length=500,
            ),
            PageRecord(
                url="https://docs.arduino.cc/calibration-body",
                domain="docs.arduino.cc",
                title="General Reference",
                content_text="Calibration notes for workshop equipment.",
                http_status=200,
                content_length=500,
            ),
        ],
        clean=True,
    )

    results = search("calibration", index_dir=index_dir)
    assert len(results) == 2
    assert results[0].url == "https://docs.arduino.cc/calibration-title"
    assert results[0].score > results[1].score


def test_snippets_strip_html_markup(mechatronics_index):
    """Highlighted snippets must be plain text, with no raw HTML tags."""
    results = search("stepper motor", index_dir=mechatronics_index)
    assert results
    for result in results:
        assert "<" not in result.snippet
        assert ">" not in result.snippet
        assert result.snippet.strip()


def test_blank_and_punctuation_only_queries_are_safe(mechatronics_index):
    """Blank, whitespace, and syntax-only inputs never raise or return junk."""
    assert search("", index_dir=mechatronics_index) == []
    assert search("   ", index_dir=mechatronics_index) == []
    assert search("((((", index_dir=mechatronics_index) == []
    assert search("AND OR NOT", index_dir=mechatronics_index) == []


def test_search_resource_cleanup_context_manager(mechatronics_index):
    """Verifies that SearchEngine context manager opens and closes cleanly."""
    with SearchEngine(index_dir=mechatronics_index) as engine:
        res = engine.search("pneumatic")
        assert len(res) == 1

    # After exiting block, engine is closed and can be reopened
    with SearchEngine(index_dir=mechatronics_index) as engine2:
        res2 = engine2.search("pneumatic")
        assert len(res2) == 1


def test_results_carry_the_topic_labels_written_by_the_indexer(mechatronics_index):
    """Topic labels travel from the index into each SearchResult."""
    results = search("Rotary Encoder", index_dir=mechatronics_index)
    assert results
    assert "sensors" in results[0].topics

    control = search("PID Controller", limit=1, index_dir=mechatronics_index)
    assert control
    assert "control_systems" in control[0].topics


def test_topic_filter_restricts_results(mechatronics_index):
    """Filtering by topic returns only documents carrying that label."""
    engine = SearchEngine(index_dir=mechatronics_index)
    try:
        unfiltered = engine.search("control", limit=10)
        filtered = engine.search("control", limit=10, topic="electronics")
    finally:
        engine.close()

    assert len(filtered) < len(unfiltered)
    assert filtered, "the electronics document still matches the query"
    assert all("electronics" in result.topics for result in filtered)
    assert TOPIC_FIXTURE_URLS["electronics"] in {r.url for r in filtered}


def test_topic_filter_does_not_change_bm25f_scores(mechatronics_index):
    """A filter excludes documents; it never re-scores the ones it keeps."""
    engine = SearchEngine(index_dir=mechatronics_index)
    try:
        unfiltered = {r.url: r.score for r in engine.search("control", limit=10)}
        filtered = engine.search("control", limit=10, topic="electronics")
    finally:
        engine.close()

    assert filtered
    for result in filtered:
        assert result.score == pytest.approx(unfiltered[result.url])


def test_topic_filter_returns_nothing_for_an_unknown_topic(mechatronics_index):
    """An unrecognised filter must not be silently ignored."""
    assert search("control", index_dir=mechatronics_index, topic="astrophysics") == []
    assert search("control", index_dir=mechatronics_index, topic="") != []
    assert search("control", index_dir=mechatronics_index, topic=None) != []


def test_topic_filter_narrows_the_robotics_query(mechatronics_index):
    results = search("actuators", index_dir=mechatronics_index, topic="robotics")
    assert results
    assert results[0].url == TOPIC_FIXTURE_URLS["robotics"]
    assert search("actuators", index_dir=mechatronics_index, topic="sensors") == []


def test_topic_and_domain_counts_describe_the_index(mechatronics_index):
    """The statistics the UI shows are read from the index, not hard-coded."""
    engine = SearchEngine(index_dir=mechatronics_index)
    try:
        topics = engine.topic_counts()
        domains = engine.domain_counts()
        assert engine.document_count() == 5
    finally:
        engine.close()

    assert domains == {"docs.arduino.cc": 3, "eng.libretexts.org": 2}
    assert sum(domains.values()) == 5
    # Every fixture document carries exactly one label, and the counts are read
    # from the index rather than computed by the test.
    assert topics == {
        "control_systems": 1,
        "electronics": 1,
        "robotics": 1,
        "sensors": 1,
        "embedded_systems": 1,
    }
    # Topics without indexed documents are omitted rather than reported as 0.
    assert "mechanical_engineering" not in topics
    assert all(count > 0 for count in topics.values())


def test_counts_are_empty_when_the_index_is_missing(tmp_path):
    engine = SearchEngine(index_dir=tmp_path / "absent")
    assert engine.topic_counts() == {}
    assert engine.domain_counts() == {}
