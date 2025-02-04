from __future__ import annotations

import subprocess
from dataclasses import dataclass

from rich.console import Group, NewLine
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.reactive import var
from textual.widgets import OptionList, Static
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
    diff: str


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
        hash_short, date, author_name, subject = [
            info.decode("utf-8") for info in split_info
        ]
        entries.append(LogEntry(hash_short, date, author_name, subject))

    return entries


def git_show(commit_hash: str) -> CommitDetails:
    format_placeholders = ["%H", "%ad", "%an", "%ae", "%s", "%b"]
    format = "--format=format:" + "%x00".join(format_placeholders) + "%x00"

    # TODO: Handle errors when running `git show`
    output = subprocess.check_output(
        ["git", "show", commit_hash, format],
    )

    info_count = len(format_placeholders) + 1  # info plus the diff
    split_info = output.split(b"\x00", maxsplit=info_count)
    hash, date, author_name, author_email, subject, body, diff = [
        info.decode("utf-8") for info in split_info
    ]
    diff = diff.strip()

    return CommitDetails(
        hash,
        date,
        author_name,
        author_email,
        subject,
        body,
        diff,
    )


class LogView(OptionList):
    COMPONENT_CLASSES = {
        "log-view--hash",
    }

    DEFAULT_CSS = """
    LogView {
        height: 1fr;
        border: solid $foreground 50%;
        padding: 0;

        &:focus {
            border: solid $border;
        }

        .log-view--hash {
            color: $text-accent;
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
        hash_style = self.get_component_rich_style(
            "log-view--hash",
            partial=True,
        )
        spacer = " "
        prompt = Text.assemble(
            (entry.hash_short, hash_style),
            spacer,
            entry.subject,
        )

        return Option(prompt, id=entry.hash_short)

    @on(OptionList.OptionHighlighted)
    def _update_border_title(
        self,
        event: OptionList.OptionHighlighted,
    ) -> None:
        commit_number = event.option_index + 1
        total_commits = self.option_count
        self.border_title = f"Commit {commit_number}/{total_commits}"


class CommitInfoView(VerticalScroll):
    COMPONENT_CLASSES = {
        "commit-info-view--hash",
    }

    DEFAULT_CSS = """
    CommitInfoView {
        height: auto;
        max-height: 100%;
        background: $surface;
        border: solid $foreground 50%;

        .commit-info-view--hash {
            color: $text-accent;
        }

        &:focus {
            border: solid $border;
            background-tint: $foreground 5%;
        }
    }
    """

    commit_details: var[CommitDetails | None] = var(None)

    def compose(self) -> ComposeResult:
        yield Static()

    def watch_commit_details(self) -> None:
        commit = self.commit_details
        if commit is None:
            return
        hash_style = self.get_component_rich_style(
            "commit-info-view--hash",
            partial=True,
        )
        hash_text = Text(
            f"commit {commit.hash}",
            style=hash_style,
            no_wrap=True,
        )

        info_grid = Table.grid()
        info_grid.add_row(
            "Author: ",
            f"{commit.author_name} <{commit.author_email}>",
        )
        info_grid.add_row("Date: ", commit.date)

        self.query_one(Static).update(
            Group(
                hash_text,
                info_grid,
            )
        )


class CommitMessageView(VerticalScroll):
    COMPONENT_CLASSES = {
        "commit-message-view--subject",
    }

    DEFAULT_CSS = """
    CommitMessageView {
        height: auto;
        max-height: 100%;
        background: $surface;
        border: solid $foreground 50%;

        .commit-message-view--subject {
            text-style: bold;
        }

        &:focus {
            border: solid $border;
            background-tint: $foreground 5%;
        }
    }
    """

    commit_details: var[CommitDetails | None] = var(None)

    def compose(self) -> ComposeResult:
        yield Static()

    def watch_commit_details(self) -> None:
        commit = self.commit_details
        if commit is None:
            return
        subject_style = self.get_component_rich_style(
            "commit-message-view--subject",
            partial=True,
        )
        subject_text = Text(commit.subject, style=subject_style)
        body_text = Text(commit.body)

        self.query_one(Static).update(
            Group(
                subject_text,
                NewLine(),
                body_text,
            )
        )


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
    }
    """

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
        syntax = Syntax(
            commit.diff,
            lexer="diff",
            word_wrap=True,
            theme=self.theme,
        )
        self.query_one(Static).update(syntax)

    def watch_commit_details(self) -> None:
        self._update_syntax_content()

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


class JagtApp(App):
    def compose(self) -> ComposeResult:
        with Horizontal():
            yield LogView()
            yield CommitDetailsView()

    def on_mount(self) -> None:
        log_view = self.query_one(LogView)
        log_view.entries = git_log()

    @on(LogView.OptionHighlighted)
    def update_commit_details_view(
        self,
        event: LogView.OptionHighlighted,
    ) -> None:
        commit_hash = event.option_id
        assert commit_hash is not None
        commit_details_view = self.query_one(CommitDetailsView)
        commit_details_view.commit_details = git_show(commit_hash)


def run() -> None:
    app = JagtApp()
    app.run()
