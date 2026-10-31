"""Unit tests for PolitenessManager and robots.txt handling."""

import time
import urllib.robotparser
from src.crawler.politeness import PolitenessManager
from tests.http_fakes import FakeResponse, FakeSession


def test_politeness_custom_robot_parser():
    manager = PolitenessManager(user_agent="MechatronicsBot/1.0", default_delay=1.0)

    # Inject a simulated robot parser
    mock_parser = urllib.robotparser.RobotFileParser()
    mock_parser.parse([
        "User-agent: *",
        "Disallow: /admin/",
        "Disallow: /private/",
        "Crawl-delay: 3",
        "Allow: /learn/"
    ])
    manager._parsers["docs.arduino.cc"] = mock_parser

    assert manager.can_fetch("https://docs.arduino.cc/learn/sensors") is True
    assert manager.can_fetch("https://docs.arduino.cc/admin/dashboard") is False
    assert manager.get_crawl_delay("https://docs.arduino.cc/learn/sensors") == 3.0


def test_politeness_enforce_delay():
    manager = PolitenessManager(user_agent="MechatronicsBot/1.0", default_delay=0.1)

    url = "https://docs.arduino.cc/test"
    # Inject an empty parser so this unit test never touches the network.
    manager._parsers["docs.arduino.cc"] = urllib.robotparser.RobotFileParser()
    # First call should not sleep
    slept1 = manager.enforce_delay(url)
    assert slept1 == 0.0

    # Immediate second call should sleep roughly 0.1s
    start = time.time()
    slept2 = manager.enforce_delay(url)
    elapsed = time.time() - start

    assert slept2 > 0.0
    assert elapsed >= 0.08  # Tolerant threshold for test execution


def test_politeness_reads_robots_txt_with_http_and_timeout():
    manager = PolitenessManager(
        user_agent="MechatronicsBot/1.0",
        default_delay=1.0,
        request_timeout=3.0,
    )
    robots_url = "https://docs.arduino.cc/robots.txt"
    session = FakeSession({
        robots_url: FakeResponse(
            url=robots_url,
            content=b"User-agent: *\nDisallow: /private/\n",
            headers={"Content-Type": "text/plain"},
        )
    })
    manager._session = session

    assert manager.can_fetch("https://docs.arduino.cc/learn/sensors") is True
    assert manager.can_fetch("https://docs.arduino.cc/private/notes") is False
    assert session.calls == [robots_url]
    assert session.last_kwargs["timeout"] == 3.0
    assert "MechatronicsBot" in session.last_kwargs["headers"]["User-Agent"]


def test_politeness_disallows_host_when_robots_txt_is_unavailable():
    manager = PolitenessManager(user_agent="MechatronicsBot/1.0")
    robots_url = "https://docs.arduino.cc/robots.txt"
    manager._session = FakeSession({
        robots_url: FakeResponse(url=robots_url, status_code=503, content=b"down")
    })

    assert manager.can_fetch("https://docs.arduino.cc/learn/") is False


def test_politeness_allows_when_robots_txt_is_missing():
    manager = PolitenessManager(user_agent="MechatronicsBot/1.0")
    robots_url = "https://docs.arduino.cc/robots.txt"
    manager._session = FakeSession({
        robots_url: FakeResponse(url=robots_url, status_code=404, content=b"missing")
    })

    assert manager.can_fetch("https://docs.arduino.cc/learn/") is True
