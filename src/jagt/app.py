from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass

from rich.syntax import Syntax
from rich.table import Table
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits, Provider, SimpleCommand
from textual.containers import VerticalScroll
from textual.content import Content
from textual.reactive import var
from textual.screen import Screen
from textual.widgets import Footer, OptionList, Static
from textual.widgets.option_list import Option


@dataclass(frozen=True)
class LogEntry:
    hash_short: str
    date: str
    author_name: str
    subject: str


@dataclass(frozen=True)
class CommitDetails:
    hash: str
    date: str
    author_name: str
    author_email: str
    subject: str
    body: str
    short_stat: str
    diff: str


class GitCommandError(Exception):
    def __init__(self, command: str, return_code: int, stderr: str) -> None:
        self.command = command
        self.return_code = return_code
        self.stderr = stderr

    def __str__(self) -> str:
        return f"git command `{self.command}` failed: {self.stderr}"


def git_log() -> list[LogEntry]:
    entries: list[LogEntry] = []

    format_placeholders = ["%h", "%as", "%an", "%s"]
    format = "--format=format:" + "%x00".join(format_placeholders)

    try:
        output = subprocess.check_output(
            ["git", "log", format],
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as error:
        raise GitCommandError("log", error.returncode, error.output.decode())

    info_count = len(format_placeholders)
    for line in output.splitlines():
        split_info = line.split(b"\x00", maxsplit=info_count - 1)
        assert len(split_info) == info_count
        hash_short, date, author_name, subject = [
            info.decode("utf-8") for info in split_info
        ]
        entries.append(LogEntry(hash_short, date, author_name, subject))

    return entries


def git_show(commit_hash: str) -> CommitDetails:
    format_placeholders = ["%H", "%ad", "%an", "%ae", "%s", "%b"]
    format = "--format=format:" + "%x00".join(format_placeholders) + "%x00"

    try:
        output = subprocess.check_output(
            ["git", "show", commit_hash, "--shortstat", "--patch", format],
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as error:
        raise GitCommandError("show", error.returncode, error.output.decode())

    info_count = len(format_placeholders) + 1  # info plus the diff
    split_info = output.split(b"\x00", maxsplit=info_count - 1)
    assert len(split_info) == info_count
    hash, date, author_name, author_email, subject, body, diff_info = [
        info.decode("utf-8") for info in split_info
    ]
    diff_info = diff_info.lstrip()
    short_stat, diff = diff_info.split("\n", maxsplit=1)
    diff = diff.strip()

    return CommitDetails(
        hash,
        date,
        author_name,
        author_email,
        subject,
        body,
        short_stat,
        diff,
    )


class LogView(OptionList):
    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("space", "page_down", "Page Down", show=False),
        Binding("g", "first", "First", show=False),
        Binding("G", "last", "Last", show=False),
    ]

    DEFAULT_CSS = """
    LogView {
        height: 1fr;
        border: solid $foreground 50%;
        padding: 0;

        &:focus {
            border: solid $border;
        }
    }
    """

    entries: var[list[LogEntry]] = var([])

    def watch_entries(self) -> None:
        if not self.entries:
            return
        self.add_options(
            [self._make_entry_content(entry) for entry in self.entries],
        )
        self.highlighted = 0

    def _make_entry_content(self, entry: LogEntry) -> Option:
        # TODO: I'm not decided yet whether the log view should display other
        # info such as the date and author.
        content = Content.from_markup(
            "[$text-accent]$hash_short[/] $subject",
            hash_short=entry.hash_short,
            subject=entry.subject,
        )

        return Option(content, id=entry.hash_short)

    @on(OptionList.OptionHighlighted)
    def _update_border_title(
        self,
        event: OptionList.OptionHighlighted,
    ) -> None:
        total_commits = self.option_count
        commit_number = total_commits - event.option_index
        self.border_title = f"Commit {commit_number}/{total_commits}"


class CommitInfoView(VerticalScroll):
    DEFAULT_CSS = """
    CommitInfoView {
        height: auto;
        max-height: 100%;
        background: $surface;
        border: solid $foreground 50%;

        #--hash {
            color: $text-accent;
            text-wrap: nowrap;
            text-overflow: clip;
        }

        &:focus {
            border: solid $border;
            background-tint: $foreground 5%;
        }
    }
    """

    commit_details: var[CommitDetails | None] = var(None)

    def compose(self) -> ComposeResult:
        yield Static(id="--hash")
        yield Static(id="--info")

    def watch_commit_details(self) -> None:
        commit = self.commit_details
        if commit is None:
            return

        self.query_one("#--hash", Static).update(f"commit {commit.hash}")

        info_grid = Table.grid()
        info_grid.add_row(
            "Author: ",
            f"{commit.author_name} <{commit.author_email}>",
        )
        info_grid.add_row("Date: ", commit.date)

        self.query_one("#--info", Static).update(info_grid)


class CommitMessageView(VerticalScroll):
    DEFAULT_CSS = """
    CommitMessageView {
        height: auto;
        max-height: 100%;
        background: $surface;
        border: solid $foreground 50%;

        #--subject {
            text-style: bold;
            margin-bottom: 1;
        }

        &:focus {
            border: solid $border;
            background-tint: $foreground 5%;
        }
    }
    """

    commit_details: var[CommitDetails | None] = var(None)

    def compose(self) -> ComposeResult:
        yield Static(id="--subject", markup=False)
        yield Static(id="--body", markup=False)

    def watch_commit_details(self) -> None:
        commit = self.commit_details
        if commit is None:
            return
        self.query_one("#--subject", Static).update(commit.subject)
        self.query_one("#--body", Static).update(commit.body)


class CommitDiffView(VerticalScroll):
    DEFAULT_CSS = """
    CommitDiffView {
        height: auto;
        max-height: 100%;
        background: $surface;
        border: solid $foreground 50%;

        &:focus {
            border: solid $border;
            background-tint: $foreground 5%;
        }

        &.-warning-max-diff {
            Static {
                border-top: panel $warning;
                border-title-style: italic;
            }
        }
    }
    """

    MAX_DIFF_CHARS = 100_000

    DARK_SYNTAX_THEME = "monokai"
    LIGHT_SYNTAX_THEME = "default"

    commit_details: var[CommitDetails | None] = var(None)
    theme: var[str] = var(DARK_SYNTAX_THEME)

    def compose(self) -> ComposeResult:
        yield Static()

    def _update_syntax_content(self) -> None:
        commit = self.commit_details
        if commit is None:
            return
        truncated_diff = commit.diff[: self.MAX_DIFF_CHARS]
        syntax = Syntax(
            truncated_diff,
            lexer="diff",
            word_wrap=True,
            theme=self.theme,
        )
        diff_widget = self.query_one(Static)
        diff_widget.update(syntax)

        # TODO: Allow loading the full diff via a link or button
        diff_exceeds_max = len(commit.diff) > self.MAX_DIFF_CHARS
        self.set_class(diff_exceeds_max, "-warning-max-diff")
        diff_widget.border_title = (
            "Large commit: diff truncated" if diff_exceeds_max else None
        )

    def watch_commit_details(self) -> None:
        commit = self.commit_details
        if commit is None:
            return
        self._update_syntax_content()
        self.border_title = f"Diff: {commit.short_stat}"

    def watch_theme(self) -> None:
        self._update_syntax_content()

    def on_mount(self) -> None:
        self.watch(self.app, "theme", self._retheme)

    def _retheme(self) -> None:
        self.theme = (
            self.DARK_SYNTAX_THEME
            if self.app.current_theme.dark
            else self.LIGHT_SYNTAX_THEME
        )


class CommitDetailsView(VerticalScroll, can_focus=False):
    DEFAULT_CSS = """
    CommitDetailsView {
        background: $surface;
    }
    """

    commit_details: var[CommitDetails | None] = var(None)

    def compose(self) -> ComposeResult:
        commit_info = CommitInfoView()
        commit_info.border_title = "Info"
        commit_info.data_bind(CommitDetailsView.commit_details)

        commit_message = CommitMessageView()
        commit_message.border_title = "Message"
        commit_message.data_bind(CommitDetailsView.commit_details)

        commit_diff = CommitDiffView()
        commit_diff.border_title = "Diff"
        commit_diff.data_bind(CommitDetailsView.commit_details)

        yield commit_info
        yield commit_message
        yield commit_diff


class LogScreenCommands(Provider):
    @property
    def commands(self) -> list[SimpleCommand]:
        screen = self.screen
        assert isinstance(screen, LogScreen)
        commands = [
            SimpleCommand(
                "Flip layout",
                screen.flip_layout,
                "Toggle vertical/horizontal layout",
            ),
        ]
        return commands

    async def discover(self) -> Hits:
        for name, callback, help_text in self.commands:
            yield DiscoveryHit(name, callback, help=help_text)

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for name, callback, help_text in self.commands:
            score = matcher.match(name)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(name),
                    callback,
                    help=help_text,
                )


class LogScreen(Screen):
    BINDINGS = [
        ("y", "copy_commit_hash", "Copy Hash"),
    ]

    COMMANDS = {LogScreenCommands}

    CSS = """
    LogScreen {
        layout: horizontal;

        &.vertical-split {
            layout: vertical;
        }
    }
    """

    def compose(self) -> ComposeResult:
        yield LogView()
        yield CommitDetailsView()
        yield Footer()

    def on_mount(self) -> None:
        log_view = self.query_one(LogView)
        try:
            log_view.entries = git_log()
        except GitCommandError as error:
            self.app.exit(
                message=f"{self.app.title}: {error}",
                return_code=error.return_code,
            )

    @on(LogView.OptionHighlighted)
    def update_commit_details_view(
        self,
        event: LogView.OptionHighlighted,
    ) -> None:
        commit_hash = event.option_id
        assert commit_hash is not None
        commit_details_view = self.query_one(CommitDetailsView)
        try:
            commit_details_view.commit_details = git_show(commit_hash)
        except GitCommandError as error:
            self.app.exit(
                message=f"{self.app.title}: {error}",
                return_code=error.return_code,
            )

    def action_copy_commit_hash(self) -> None:
        # Textual warns that its copy_to_clipboard method does not work in all
        # terminals. Maybe use an external library like pyperclip instead?
        commit_details = self.query_one(CommitDetailsView).commit_details
        if commit_details is None:
            return
        self.app.copy_to_clipboard(commit_details.hash)
        self.notify(title="Copied to clipboard", message=commit_details.hash)

    def flip_layout(self) -> None:
        self.toggle_class("vertical-split")


class JagtApp(App):
    TITLE = "jagt"

    MODES = {
        "log": LogScreen,
    }

    DEFAULT_MODE = "log"

    CSS = """
    * {
        scrollbar-size-vertical: 1;
    }
    """


def run() -> None:
    app = JagtApp()
    app.run()
    # https://textual.textualize.io/guide/app/#return-code
    sys.exit(app.return_code or 0)
