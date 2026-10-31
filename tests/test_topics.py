"""Tests for the deterministic topic classifier and schema definition.

These tests pin the classification rules: the topic filter in the UI is only
honest if the labels are derived from the page itself and always come out the
same way for the same input.
"""

import pytest

from src.indexer import topics
from src.indexer.schema import create_search_schema
from src.indexer.topics import (
    MAX_TOPICS_PER_PAGE,
    MIN_TOPIC_SCORE,
    TOPIC_LABELS,
    classify_topics,
    describe_rules,
    topic_label,
)

REQUIRED_TOPICS = {
    "robotics",
    "control_systems",
    "electronics",
    "mechanical_engineering",
    "sensors",
    "embedded_systems",
}


def test_the_six_documented_topics_exist_with_labels():
    assert set(TOPIC_LABELS) == REQUIRED_TOPICS
    for slug, label in TOPIC_LABELS.items():
        # The slug is written into a Whoosh KEYWORD field, so it must stay a
        # single token: no spaces, no commas.
        assert " " not in slug
        assert "," not in slug
        assert label


def test_topic_label_falls_back_to_the_slug():
    assert topic_label("robotics") == "Robotics"
    assert topic_label("not_a_topic") == "not_a_topic"


@pytest.mark.parametrize(
    "title, content, url, expected_topic",
    [
        (
            "Introduction to Control Systems",
            "Feedback control and PID controller design use transfer functions, "
            "root locus and Bode plots to analyse stability.",
            "https://eng.libretexts.org/Bookshelves/Industrial_and_Systems_Engineering/Introduction_to_Control_Systems_(Iqbal)",
            "control_systems",
        ),
        (
            "Stepper Motor and Driver Basics",
            "A transistor H-bridge circuit switches motor current; add a "
            "capacitor across the supply.",
            "https://docs.arduino.cc/learn/electronics/stepper-motors/",
            "electronics",
        ),
        (
            "Introduction to Autonomous Robots",
            "A manipulator with a gripper uses inverse kinematics and servo "
            "actuators to plan a path for a mobile robot.",
            "https://eng.libretexts.org/Bookshelves/Mechanical_Engineering/Introduction_to_Autonomous_Robots_(Correll)",
            "robotics",
        ),
        (
            "Mechanics of Materials",
            "Bending stress and strain in a beam, plus material selection and "
            "shaft design criteria.",
            "https://eng.libretexts.org/Bookshelves/Mechanical_Engineering/Mechanics_of_Materials_(Roylance)",
            "mechanical_engineering",
        ),
        (
            "Ultrasonic Distance Sensor Interfacing",
            "The ultrasonic transducer times the acoustic echo to measure "
            "distance; calibration improves accuracy.",
            "https://howtomechatronics.com/tutorials/arduino/ultrasonic-sensor-hc-sr04/",
            "sensors",
        ),
        (
            "Microcontroller Programming Guide",
            "Firmware for an embedded target drives GPIO pins, configures an "
            "interrupt and talks over I2C and SPI.",
            "https://en.wikibooks.org/wiki/Embedded_Systems/Microprocessor_Introduction",
            "embedded_systems",
        ),
    ],
)
def test_representative_pages_are_classified_into_the_right_topic(
    title, content, url, expected_topic
):
    assert expected_topic in classify_topics(title, content, url)


def test_classification_is_deterministic():
    title = "PID Controller Tuning"
    content = "Proportional integral derivative control with feedback and a setpoint."
    url = "https://example.edu/control/pid"
    first = classify_topics(title, content, url)
    for _ in range(5):
        assert classify_topics(title, content, url) == first


def test_a_single_body_keyword_is_not_enough_evidence():
    """One incidental mention must not label a whole page."""
    assert classify_topics("Workshop notes", "buy a sensor") == ()


def test_minimum_score_is_respected():
    """Body-only evidence needs three distinct keywords, not one or two."""
    assert MIN_TOPIC_SCORE == 3
    assert classify_topics("", "sensor") == ()
    # Two distinct body keywords score 2, still below the threshold.
    assert classify_topics("", "sensor calibration") == ()
    # A third distinct keyword is enough.
    assert "sensors" in classify_topics("", "sensor calibration encoder")
    # One keyword in the title plus one in the body also reaches it.
    assert "sensors" in classify_topics("Sensor guide", "encoder wiring")


def test_empty_and_missing_input_is_unclassified():
    assert classify_topics(None, None, None) == ()
    assert classify_topics("", "", "") == ()
    assert classify_topics("   ", "   ") == ()


def test_url_evidence_is_used_when_the_text_is_thin():
    thin_text = "Read the overview and chapter list."
    without_hint = classify_topics("Overview", thin_text, "https://example.edu/x")
    with_hint = classify_topics(
        "Overview",
        thin_text,
        "https://eng.libretexts.org/Bookshelves/Electrical_Engineering/Electronics",
    )
    assert without_hint == ()
    assert "electronics" in with_hint


def test_query_strings_do_not_create_false_topic_evidence():
    # Topic evidence must come from the path, not from arbitrary query data.
    result = classify_topics(
        "Overview", "Read the overview.", "https://example.edu/x?q=robotics"
    )
    assert result == ()


def test_a_page_keeps_at_most_the_documented_number_of_topics():
    title = "Mechatronics Robot Arm with PID Control and DC Motor Driver"
    content = (
        "The robot arm combines a microcontroller, a servo gripper, an "
        "H-bridge motor driver, a gearbox, torque calculations, an encoder "
        "sensor, a PID controller with feedback, and a 3D printed bracket."
    )
    url = "https://example.edu/robotics/arm"
    result = classify_topics(title, content, url)

    assert 1 <= len(result) <= MAX_TOPICS_PER_PAGE
    assert len(set(result)) == len(result)


def test_topics_are_ordered_by_evidence_strength():
    title = "PID Controller Tuning for a Robot Joint"
    content = (
        "Feedback control with a setpoint and a transfer function. The robot "
        "uses a servo actuator and a gripper."
    )
    # The URL deliberately carries no topic hint, so ordering is decided by the
    # page text alone.
    result = classify_topics(title, content, "https://example.edu/notes/42")

    assert result[0] == "control_systems"
    assert "robotics" in result


def test_url_evidence_can_outweigh_a_weaker_text_signal():
    """URL evidence is worth 2 points, so it can decide a close call.

    The page text alone is slightly more mechanical than robotic; the path
    places it under a robotics section, which tips the balance.
    """
    title = "Gearbox Guide"
    content = "A bearing is pressed into the housing. A servo drives the gripper."

    without_hint = classify_topics(title, content, "https://example.edu/notes/42")
    with_hint = classify_topics(title, content, "https://example.edu/robotics/gearbox")

    assert without_hint[0] == "mechanical_engineering"
    assert with_hint[0] == "robotics"
    assert "mechanical_engineering" in with_hint


def test_searcher_topic_vocabulary_matches_the_classifier():
    """The searcher imports the same table, so the two cannot drift apart."""
    from src.search import searcher

    assert searcher.TOPIC_LABELS is TOPIC_LABELS


def test_index_schema_has_a_topics_field_that_is_not_scored():
    schema = create_search_schema()
    names = set(schema.names())

    assert "topics" in names
    assert schema["topics"].stored is True
    # The field exists purely for filtering and display.
    assert names >= {"url", "domain", "title", "content", "topics"}


def test_describe_rules_documents_every_topic():
    rules = "\n".join(describe_rules())

    for slug in REQUIRED_TOPICS:
        assert slug in rules
    assert str(MIN_TOPIC_SCORE) in rules
    assert str(MAX_TOPICS_PER_PAGE) in rules


def test_topics_module_exposes_only_the_documented_vocabulary():
    assert topics.TOPIC_LABELS == TOPIC_LABELS
    # Every hint must point at a real topic.
    assert set(topics.TOPIC_URL_HINTS) <= set(TOPIC_LABELS)
    # Every keyword list must be non-empty and lowercase.
    for slug, keywords in topics.TOPIC_KEYWORDS.items():
        assert slug in TOPIC_LABELS
        assert keywords
        for keyword in keywords:
            assert keyword == keyword.lower()
