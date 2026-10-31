"""Deterministic topic classification for indexed pages.

The UI offers a topic filter for Robotics, Control Systems, Electronics,
Mechanical Engineering, Sensors and Embedded Systems. Those filters are only
honest if every topic label is derived from the page that carries it, so this
module scores each crawled page against an explicit, auditable rule table and
assigns the topics that actually clear a threshold.

Design rules:

* The score for a topic is: ``2 * (distinct keywords in the title)``
  ``+ 1 * (distinct keywords in the body)`` ``+ 2 * (matching URL hints)``.
  Counting *distinct* keywords rather than raw occurrences stops a single long
  page from dominating a topic just because it repeats one word.
* A topic is assigned only when its score reaches :data:`MIN_TOPIC_SCORE`, and a
  page keeps at most :data:`MAX_TOPICS_PER_PAGE` topics (highest score first,
  ties broken by label) so the labels stay meaningful instead of exhaustive.
* Multi-topic assignment is deliberate: a stepper-motor tutorial is genuinely
  Electronics, Mechanical Engineering and Embedded Systems at once.
* Scoring never touches BM25F. Topic labels are stored in the Whoosh index as a
  separate ``topics`` field that is absent from the query parser's field list, so
  ranking and snippets are unchanged whether or not a topic filter is used.

Nothing here is learned or inferred at runtime; re-running the indexer over the
same pages always produces the same labels.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Tuple

__all__ = [
    "TOPIC_LABELS",
    "MIN_TOPIC_SCORE",
    "MAX_TOPICS_PER_PAGE",
    "classify_topics",
    "topic_label",
    "describe_rules",
]

# Canonical topic slug -> human-readable label shown in the UI. The slug is what
# gets stored in the Whoosh index, so it must stay a single token that Whoosh's
# keyword analyzer will not split (no spaces, no commas).
TOPIC_LABELS: Dict[str, str] = {
    "robotics": "Robotics",
    "control_systems": "Control Systems",
    "electronics": "Electronics",
    "mechanical_engineering": "Mechanical Engineering",
    "sensors": "Sensors",
    "embedded_systems": "Embedded Systems",
}

# A topic needs at least this much evidence. One keyword hit in a title (2
# points) is not enough on its own; a title hit plus a body hit, or two body
# hits, is.
MIN_TOPIC_SCORE = 3

# Keeps the most relevant labels instead of labelling every page with everything.
MAX_TOPICS_PER_PAGE = 3

# Distinct keywords per topic. Single words match their regular plural
# automatically ("sensor" also matches "sensors"); multi-word entries are
# matched as literal phrases. Terms were chosen to be diagnostic of the
# discipline rather than generic engineering vocabulary.
TOPIC_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "robotics": (
        "robot", "robotic", "robotics", "manipulator", "end effector",
        "gripper", "humanoid", "hexapod", "quadruped", "mobile robot",
        "autonomous", "slam", "path planning", "inverse kinematics",
        "forward kinematics", "actuator", "servo", "degrees of freedom",
        "degree of freedom", "mecanum", "rover", "quadcopter", "drone",
        "robot arm", "pick and place",
    ),
    "control_systems": (
        "pid", "proportional integral derivative", "controller", "control system",
        "feedback", "closed loop", "closed-loop", "open loop", "open-loop",
        "setpoint", "transfer function", "state space", "state-space",
        "root locus", "bode", "nyquist", "routh", "compensator", "observer",
        "overshoot", "steady state error", "stability", "gain", "plant",
        "system identification", "discrete-time", "sampled data",
    ),
    "electronics": (
        "circuit", "voltage", "current", "resistor", "resistance", "capacitor",
        "capacitance", "inductor", "inductance", "transistor", "diode",
        "mosfet", "pcb", "printed circuit", "solder", "soldering",
        "power supply", "h-bridge", "h bridge", "motor driver", "ohm",
        "rectifier", "amplifier", "oscilloscope", "breadboard", "relay",
        "integrated circuit", "schematic", "watt", "clamp meter", "multimeter",
    ),
    "mechanical_engineering": (
        "mechanical", "mechanism", "gear", "gearbox", "gear ratio", "torque",
        "bearing", "shaft", "machine design", "statics", "dynamics",
        "thermodynamics", "fluid mechanics", "stress", "strain", "material",
        "3d printing", "3d model", "cnc", "finite element", "friction",
        "vibration", "linkage", "cycloidal", "planetary gear", "tolerance",
        "clutch", "belt drive", "moment of inertia", "solidworks",
        "structural", "mechanics",
    ),
    "sensors": (
        "sensor", "transducer", "encoder", "accelerometer", "gyroscope",
        "magnetometer", "ultrasonic", "hall effect", "thermistor",
        "thermocouple", "photodiode", "limit switch", "load cell",
        "potentiometer", "strain gauge", "pir", "calibration", "analog input",
        "analog-to-digital", "adc", "measurement", "sampling rate",
        "resolution", "proximity", "temperature sensor", "pressure sensor",
        "force sensor", "photoresistor", "ldr",
    ),
    "embedded_systems": (
        "microcontroller", "arduino", "firmware", "embedded", "gpio",
        "digital pin", "digital pins", "interrupt", "i2c", "spi", "uart",
        "serial communication", "rtos", "real-time operating system",
        "register", "eeprom", "bootloader", "plc",
        "programmable logic controller", "microprocessor", "sketch",
        "watchdog timer", "pulse width modulation", "pwm", "bitwise",
        "memory", "bootloader",
    ),
}

# URL evidence. Documentation sites often encode the discipline in the path, and
# that is more reliable than guessing from a short product blurb.
TOPIC_URL_HINTS: Dict[str, Tuple[str, ...]] = {
    "mechanical_engineering": ("mechanical_engineering", "mechanical-engineering"),
    "electronics": (
        "electrical_engineering",
        "electrical-engineering",
        "electronics",
    ),
    "control_systems": ("control_systems", "control-systems", "control-system"),
    "robotics": ("robotics", "robot"),
    "embedded_systems": ("/embedded", "microcontroller", "/hardware/"),
    "sensors": ("sensors", "/sensor"),
}


def _compile_keyword(word: str) -> "re.Pattern[str]":
    """Compiles one keyword into a case-insensitive, boundary-aware pattern."""
    escaped = re.escape(word)
    if " " in word:
        # Literal phrase; allow flexible whitespace between words.
        pattern = escaped.replace(r"\ ", r"\s+")
        return re.compile(pattern, re.IGNORECASE)
    # Single word: also match the regular plural ("sensor" -> "sensors").
    return re.compile(rf"\b{escaped}(?:s|es)?\b", re.IGNORECASE)


_COMPILED_KEYWORDS: Dict[str, Tuple["re.Pattern[str]", ...]] = {
    slug: tuple(_compile_keyword(word) for word in words)
    for slug, words in TOPIC_KEYWORDS.items()
}


def _topic_score(
    slug: str, title: str, body: str, path: str
) -> int:
    """Scores one topic against a page's title, body and URL path."""
    score = 0
    for pattern in _COMPILED_KEYWORDS[slug]:
        if title and pattern.search(title):
            score += 2
        if body and pattern.search(body):
            score += 1
    for hint in TOPIC_URL_HINTS.get(slug, ()):
        if hint in path:
            score += 2
    return score


def classify_topics(
    title: Optional[str],
    content_text: Optional[str],
    url: Optional[str] = None,
) -> Tuple[str, ...]:
    """Returns the topic slugs a page genuinely belongs to, strongest first.

    An empty tuple means the page carried no clear evidence for any of the six
    topics, which is reported honestly rather than papered over with a guess.
    """
    title_text = title or ""
    body_text = content_text or ""
    path = ""
    if url:
        # Only the path is inspected; query strings and the scheme add no signal.
        path = url.split("://", 1)[-1].lower()
        path = path.split("?", 1)[0]
    else:
        path = ""

    scored: List[Tuple[str, int]] = []
    for slug in TOPIC_LABELS:
        score = _topic_score(slug, title_text, body_text, path)
        if score >= MIN_TOPIC_SCORE:
            scored.append((slug, score))

    # Highest score first; ties resolved by label so the result is stable.
    scored.sort(key=lambda item: (-item[1], TOPIC_LABELS[item[0]]))
    return tuple(slug for slug, _score in scored[:MAX_TOPICS_PER_PAGE])


def topic_label(slug: str) -> str:
    """Returns the display label for a topic slug, or the slug itself if unknown."""
    return TOPIC_LABELS.get(slug, slug)


def describe_rules() -> List[str]:
    """Returns a human-readable summary of the rule table, for docs and tests."""
    lines = [
        f"minimum score to assign a topic: {MIN_TOPIC_SCORE}",
        f"maximum topics per page: {MAX_TOPICS_PER_PAGE}",
        "score = 2 * distinct title keywords + 1 * distinct body keywords "
        "+ 2 * matching URL hints",
    ]
    for slug, label in TOPIC_LABELS.items():
        keywords = ", ".join(TOPIC_KEYWORDS[slug])
        lines.append(f"{label} [{slug}] ({len(TOPIC_KEYWORDS[slug])} keywords): {keywords}")
    return lines
