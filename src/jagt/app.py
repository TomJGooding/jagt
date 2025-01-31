import dataclasses
import subprocess

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import OptionList


@dataclasses.dataclass
class LogEntry:
    hash: str
    date: str
    author: str
    subject: str


def git_log() -> list[LogEntry]:
    entries: list[LogEntry] = []

    format_placeholders = ["%h", "%as", "%an", "%s"]
    format = "--format=format:" + "%x00".join(format_placeholders)

    # TODO: Handle errors when running `git log`
    # e.g. when not a git repository
    output = subprocess.check_output(["git", "log", format])

    info_count = len(format_placeholders)
    for line in output.splitlines():
        split_info = line.split(b"\x00", maxsplit=info_count)
        assert len(split_info) == info_count
        hash, date, author, subject = [info.decode("utf-8") for info in split_info]
        entries.append(LogEntry(hash, date, author, subject))

    return entries


class LogView(OptionList):
    COMPONENT_CLASSES = {
        "log-view--hash",
        "log-view--subject",
    }

    DEFAULT_CSS = """
    LogView {
        height: 1fr;

        .log-view--hash {
            color: $text-accent;
        }

        .log-view--subject {
            color: $foreground;
        }

    }
    """

    def add_entries(self, entries: list[LogEntry]) -> None:
        if not entries:
            return
        content = [self.render_entry(entry) for entry in entries]
        self.add_options(content)
        self.highlighted = 0

    def render_entry(self, entry: LogEntry) -> Text:
        # TODO: I'm not decided yet whether the log view should display other
        # info such as the date and author.
        hash_style = self.get_component_rich_style(
            "log-view--hash",
            partial=True,
        )
        subject_style = self.get_component_rich_style(
            "log-view--subject",
            partial=True,
        )
        spacer = " "

        return Text.assemble(
            (entry.hash, hash_style),
            spacer,
            (entry.subject, subject_style),
        )


class JagtApp(App):
    def compose(self) -> ComposeResult:
        yield LogView()

    def on_mount(self) -> None:
        log = self.query_one(LogView)
        entries = git_log()
        log.add_entries(entries)


def run() -> None:
    app = JagtApp()
    app.run()
