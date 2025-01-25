import dataclasses
import subprocess

from textual.app import App, ComposeResult
from textual.widgets import DataTable


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


class LogView(DataTable):
    DEFAULT_CSS = """
    LogTable {
        height: 1fr;
    }
    """

    COLUMNS = ["Hash", "Date", "Author", "Subject"]

    def __init__(self) -> None:
        super().__init__(
            show_header=False,
            cursor_type="row",
        )

    def on_mount(self) -> None:
        for column in self.COLUMNS:
            self.add_column(column, key=column.lower())

    def add_entries(self, entries: list[LogEntry]) -> None:
        # TODO: Add some color to the log columns
        rows = [list(dataclasses.asdict(entry).values()) for entry in entries]
        self.add_rows(rows)


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
