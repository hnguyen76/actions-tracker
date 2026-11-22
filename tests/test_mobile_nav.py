from html.parser import HTMLParser
from pathlib import Path


TEMPLATE = Path(__file__).parents[1] / "src/actions_tracker/templates/index.html"


class _NavParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_bottom = False
        self.in_tabs = False
        self.in_bottom_button = False
        self.bottom = []
        self.tabs = []
        self.bottom_text = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        classes = set(values.get("class", "").split())
        if tag == "nav" and values.get("id") == "bottombar":
            self.in_bottom = True
        elif tag == "nav" and "tabs" in classes:
            self.in_tabs = True
        elif tag == "button" and self.in_bottom:
            self.in_bottom_button = True
            self.bottom.append(values)
        elif tag == "button" and self.in_tabs:
            self.tabs.append(values)

    def handle_endtag(self, tag):
        if tag == "button":
            self.in_bottom_button = False
        elif tag == "nav" and self.in_bottom:
            self.in_bottom = False
        elif tag == "nav" and self.in_tabs:
            self.in_tabs = False

    def handle_data(self, data):
        if self.in_bottom_button and data.strip():
            self.bottom_text.append(data.strip())


def test_mobile_nav_exposes_every_tab_as_an_icon():
    parser = _NavParser()
    parser.feed(TEMPLATE.read_text(encoding="utf-8"))

    targets = [button["data-go"] for button in parser.bottom]
    assert targets[:5] == ["upcoming", "second-half", "inplay", "past", "rules"]
    assert "more" not in targets
    assert set(targets) - {"inplay"} == {tab["data-tab"] for tab in parser.tabs}
    assert all(button.get("aria-label") == button.get("title") for button in parser.bottom)
    assert all(button.get("aria-label") for button in parser.bottom)
    assert parser.bottom_text == []
