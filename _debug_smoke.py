import tempfile
import os
import folium
from html.parser import HTMLParser

class TestParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.has_doctype = False
        self.has_html = False
        self.has_head = False
        self.has_body = False
        self.start_tags = []
        self.decls = []

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        if tag_lower == "!doctype":
            self.has_doctype = True
        if tag_lower == "html":
            self.has_html = True
        if tag_lower == "head":
            self.has_head = True
        if tag_lower == "body":
            self.has_body = True
        self