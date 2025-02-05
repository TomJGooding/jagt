from __future__ import annotations

import subprocess
import sys
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
    COMPONENT_CLASSES = {
        "log-view--hash",
        "log-view--subject",
    }

    DEFAULT_CSS = """
    LogView {
        height: 1fr;
        border: solid $surface-lighten-3;
        padding: 0;

        &:focus {
            border: solid $border;
        }

        .log-view--hash {
            color: $text-accent;
        }

        .log-view--subject {
            color: $foreground;
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
        subject_style = self.get_component_rich_style(
            "log-view--subject",
            partial=True,
        )

        spacer = " "
        prompt = Text.assemble(
            (entry.hash_short, hash_style),
            spacer,
            (entry.subject, subject_style),
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
        border: solid $surface-lighten-3;

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
        border: solid $surface-lighten-3;

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
        border: solid $surface-lighten-3;

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
        syntax = Syntax(
            commit.diff,
            lexer="diff",
            word_wrap=True,
        )
        self.query_one(Static).update(syntax)

        self.border_title = f"Diff: {commit.short_stat}"


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
    TITLE = "jagt"

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield LogView()
            yield CommitDetailsView()

    def on_mount(self) -> None:
        log_view = self.query_one(LogView)
        try:
            log_view.entries = git_log()
        except GitCommandError as error:
            self.exit(
                message=f"{self.title}: {error}",
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
            self.exit(
                message=f"{self.title}: {error}",
                return_code=error.return_code,
            )


def run() -> None:
    app = JagtApp()
    app.run()
    # https://textual.textualize.io/guide/app/#return-code
    sys.exit(app.return_code or 0)
