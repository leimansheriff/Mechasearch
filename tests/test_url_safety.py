"""Unit tests for URL normalization, filtering, and safety checks."""

import pytest
from src.crawler.url_safety import URLSafety


def test_is_allowed_domain():
    allowed = ["docs.arduino.cc", "eng.libretexts.org"]

    assert URLSafety.is_allowed_domain("https://docs.arduino.cc/learn/electronics", allowed) is True
    assert URLSafety.is_allowed_domain("https://sub.docs.arduino.cc/hardware", allowed) is True
    assert URLSafety.is_allowed_domain("https://eng.libretexts.org/Bookshelves", allowed) is True
    assert URLSafety.is_allowed_domain("https://malicious-site.com/hack", allowed) is False
    assert URLSafety.is_allowed_domain("https://arduino.cc.fake.com", allowed) is False
    assert URLSafety.is_allowed_domain("", allowed) is False


def test_has_ignored_extension():
    assert URLSafety.has_ignored_extension("https://docs.arduino.cc/datasheet.pdf") is True
    assert URLSafety.has_ignored_extension("https://docs.arduino.cc/schematic.png") is True
    assert URLSafety.has_ignored_extension("https://docs.arduino.cc/firmware.zip") is True
    assert URLSafety.has_ignored_extension("https://docs.arduino.cc/tutorial.html") is False
    assert URLSafety.has_ignored_extension("https://docs.arduino.cc/learn/electronics/") is False


def test_normalize_url_basic():
    # Fragment stripping and lowercasing
    raw = "HTTPS://Docs.Arduino.CC/learn/electronics#section-overview"
    normalized = URLSafety.normalize_url(raw)
    assert normalized == "https://docs.arduino.cc/learn/electronics"


def test_normalize_url_relative_resolution():
    base = "https://eng.libretexts.org/Bookshelves/Control_Systems/"
    relative = "PID_Control/01_Introduction"
    normalized = URLSafety.normalize_url(relative, base_url=base)
    assert normalized == "https://eng.libretexts.org/Bookshelves/Control_Systems/PID_Control/01_Introduction"


def test_normalize_url_tracking_param_removal():
    raw = "https://docs.arduino.cc/product?utm_source=twitter&id=10&utm_medium=social"
    normalized = URLSafety.normalize_url(raw)
    assert normalized == "https://docs.arduino.cc/product?id=10"


def test_spider_trap_length_rejection():
    excessive_url = "https://docs.arduino.cc/" + ("deep/path/" * 40)
    assert len(excessive_url) > 250
    assert URLSafety.normalize_url(excessive_url) is None
