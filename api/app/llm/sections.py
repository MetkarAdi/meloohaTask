from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class AnswerSection:
    title: str
    text: str


class SectionParser:
    """Incrementally parses the model's explicit semantic section markers."""

    _start = re.compile(r"\[\[SECTION:\s*([^\]]+)\]\]", re.I)
    _end = "[[/SECTION]]"

    def __init__(self) -> None:
        self.buffer = ""
        self.title: str | None = None
        self.body: list[str] = []
        self.untitled: list[str] = []
        self.index = 0

    def feed(self, text: str, *, final: bool = False) -> list[AnswerSection]:
        self.buffer += text
        found: list[AnswerSection] = []
        while self.buffer:
            if self.title is None:
                match = self._start.search(self.buffer)
                if not match:
                    keep = 32 if not final else 0
                    if len(self.buffer) > keep:
                        self.untitled.append(self.buffer[:-keep] if keep else self.buffer)
                        self.buffer = self.buffer[-keep:] if keep else ""
                    break
                self.untitled.append(self.buffer[:match.start()])
                self.buffer = self.buffer[match.end():]
                self.title = match.group(1).strip()[:80] or "Reading"
                self.body = []
            end = self.buffer.find(self._end)
            if end < 0:
                keep = len(self._end) - 1
                if len(self.buffer) > keep:
                    self.body.append(self.buffer[:-keep])
                    self.buffer = self.buffer[-keep:]
                break
            self.body.append(self.buffer[:end])
            self.buffer = self.buffer[end + len(self._end):]
            content = "".join(self.body).strip()
            if content:
                found.append(AnswerSection(self.title, content))
            self.title = None
            self.body = []
        if final:
            if self.title is not None:
                content = "".join(self.body + [self.buffer]).strip()
                if content:
                    found.append(AnswerSection(self.title, content))
            else:
                self.untitled.append(self.buffer)
                content = "".join(self.untitled).strip()
                if content:
                    found.append(AnswerSection("Reading", content))
            self.buffer = ""
            self.body = []
            self.untitled = []
            self.title = None
        return found


def section_answer(sections: list[AnswerSection]) -> str:
    if len(sections) == 1 and sections[0].title.strip().lower() == "reading":
        return sections[0].text
    return "\n\n".join(f"### {item.title}\n\n{item.text}" for item in sections)
