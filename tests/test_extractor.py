"""Unit tests for HTML title, text, link and canonical extraction."""

from src.crawler.extractor import extract_page

URL = "https://docs.arduino.cc/learn/electronics/"


def test_extract_page_success():
    html = """
    <html>
      <head>
        <title>  Sensors &amp; Actuators  </title>
        <link rel="canonical" href="/learn/electronics/actuators">
      </head>
      <body>
        <script>var hidden = "not page text";</script>
        <style>.hidden { display: none; }</style>
        <h1>Motors</h1>
        <p>Stepper motors   convert pulses\n into rotation.</p>
        <a href="stepper.html">Stepper guide</a>
        <a href="https://docs.arduino.cc/hardware/">Hardware</a>
        <a href="mailto:student@university.edu">Email</a>
        <a href="stepper.html">Stepper guide duplicate</a>
      </body>
    </html>
    """

    page = extract_page(html, URL)

    assert page.title == "Sensors & Actuators"
    assert "Stepper motors convert pulses into rotation." in page.text
    assert "hidden" not in page.text
    assert page.canonical_url == "https://docs.arduino.cc/learn/electronics/actuators"
    assert page.links == [
        "https://docs.arduino.cc/learn/electronics/stepper.html",
        "https://docs.arduino.cc/hardware/",
    ]


def test_extract_page_missing_title_falls_back_to_h1():
    page = extract_page("<html><body><h1>Fallback heading</h1><p>Body</p></body></html>", URL)

    assert page.title == "Fallback heading"
    assert page.text == "Fallback heading Body"


def test_extract_page_without_title_or_h1_returns_empty_title():
    page = extract_page("<html><body><p>Only a paragraph.</p></body></html>", URL)

    assert page.title == ""
    assert page.text == "Only a paragraph."


def test_extract_page_empty_document():
    for html in ("", "<html><head></head><body></body></html>"):
        page = extract_page(html, URL)
        assert page.title == ""
        assert page.text == ""
        assert page.links == []
        assert page.canonical_url is None


def test_extract_page_ignores_non_http_links():
    page = extract_page(
        '<html><body><a href="#section">Fragment</a><a href="tel:+123">Phone</a></body></html>',
        URL,
    )

    # Fragments are removed later during URL normalization; tel: is rejected.
    assert page.links == [URL + "#section"]
