"""`kb gap` — the learning-gaps inbox."""

import json
from pathlib import Path

from conftest import ArticleWriter
from typer.testing import CliRunner

from kb import schema
from kb.cli import app
from kb.commands.gap import LEARNED, OPEN, PROMOTED, gaps_path, read

runner = CliRunner()


def _add(text: str, area: str = "Networking", note: str = "") -> None:
    args = ["gap", "add", text, "--area", area, "--no-dry-run"]
    if note:
        args += ["--note", note]
    assert runner.invoke(app, args).exit_code == 0


def test_the_first_gap_creates_the_inbox(vault: Path) -> None:
    _add("IPv6 prefix delegation")
    (gap,) = read(vault)
    assert gap.id == "g-0001"
    assert gap.state == OPEN
    assert gaps_path(vault).is_file()


def test_the_inbox_is_an_active_learning_article(vault: Path) -> None:
    # It mutates every session, so lint must never call it stale and it is never fact.
    _add("Something")
    article = schema.parse_article(gaps_path(vault), vault)
    assert article.type == "learning"
    assert article.is_active


def test_ids_increment_and_stay_unique(vault: Path) -> None:
    for n in range(3):
        _add(f"Gap {n}")
    assert [gap.id for gap in read(vault)] == ["g-0001", "g-0002", "g-0003"]


def test_a_pipe_in_the_text_survives_the_round_trip(vault: Path) -> None:
    # A raw pipe would split the row; escaping it twice would corrupt it differently.
    _add("ClusterIP | NodePort | LoadBalancer are different things")
    (gap,) = read(vault)
    assert gap.text == "ClusterIP | NodePort | LoadBalancer are different things"


def test_rewriting_does_not_re_escape(vault: Path) -> None:
    # The bug that bit in real use: read leaves `\|` in the text, write escapes it again.
    _add("A | B")
    _add("C")
    (first,) = [gap for gap in read(vault) if gap.id == "g-0001"]
    assert first.text == "A | B"
    assert "\\\\|" not in gaps_path(vault).read_text()


def test_backticked_code_in_a_gap_survives(vault: Path) -> None:
    _add("`SpecificDatumReader` throws `SecurityException: Forbidden <class>!`")
    (gap,) = read(vault)
    assert gap.text.startswith("`SpecificDatumReader`")


def test_add_is_a_preview_by_default(vault: Path) -> None:
    result = runner.invoke(app, ["gap", "add", "Something", "--area", "SQL"])
    assert result.exit_code == 0
    assert read(vault) == []


def test_list_filters_by_area_and_state(vault: Path) -> None:
    _add("One", area="SQL")
    _add("Two", area="Networking")
    payload = json.loads(runner.invoke(app, ["gap", "list", "--area", "sql", "--json"]).output)
    assert payload["count"] == 1
    assert payload["gaps"][0]["area"] == "SQL"


def test_list_counts_by_area(vault: Path) -> None:
    _add("One", area="SQL")
    _add("Two", area="SQL")
    _add("Three", area="Networking")
    payload = json.loads(runner.invoke(app, ["gap", "list", "--json"]).output)
    assert payload["by_area"] == {"SQL": 2, "Networking": 1}


def test_list_is_newest_first(vault: Path) -> None:
    for n in range(3):
        _add(f"Gap {n}")
    payload = json.loads(runner.invoke(app, ["gap", "list", "--json"]).output)
    assert [gap["id"] for gap in payload["gaps"]] == ["g-0003", "g-0002", "g-0001"]


def test_promote_marks_the_gap_as_owned_by_a_topic(article: ArticleWriter, vault: Path) -> None:
    article("learning/networking", title="Networking — Topic", status="active")
    _add("IPv6 prefix delegation")
    result = runner.invoke(app, ["gap", "promote", "g-0001", "--to", "learning/networking", "--no-dry-run"])
    assert result.exit_code == 0
    (gap,) = read(vault)
    assert gap.state == PROMOTED
    assert gap.note == "[[learning/networking|Networking — Topic]]"


def test_promote_takes_several_gaps(article: ArticleWriter, vault: Path) -> None:
    article("learning/networking", title="Networking", status="active")
    for n in range(3):
        _add(f"Gap {n}")
    runner.invoke(app, ["gap", "promote", "g-0001", "g-0003", "--to", "learning/networking", "--no-dry-run"])
    states = {gap.id: gap.state for gap in read(vault)}
    assert states == {"g-0001": PROMOTED, "g-0002": OPEN, "g-0003": PROMOTED}


def test_promote_refuses_a_topic_that_does_not_exist(vault: Path) -> None:
    _add("Something")
    result = runner.invoke(app, ["gap", "promote", "g-0001", "--to", "learning/nope", "--no-dry-run"])
    assert result.exit_code == 1
    assert read(vault)[0].state == OPEN


def test_promote_refuses_an_unknown_id(article: ArticleWriter, vault: Path) -> None:
    article("learning/networking", title="Networking", status="active")
    _add("Something")
    result = runner.invoke(app, ["gap", "promote", "g-9999", "--to", "learning/networking", "--no-dry-run"])
    assert result.exit_code == 1


def test_close_records_what_answered_it(vault: Path) -> None:
    _add("Something")
    runner.invoke(app, ["gap", "close", "g-0001", "--note", "guides/s3-streaming §6.1", "--no-dry-run"])
    (gap,) = read(vault)
    assert gap.state == LEARNED
    assert gap.note == "guides/s3-streaming §6.1"


def test_a_closed_gap_keeps_its_id_so_it_is_not_logged_twice(vault: Path) -> None:
    _add("Something")
    runner.invoke(app, ["gap", "close", "g-0001", "--no-dry-run"])
    _add("Another thing")
    assert [gap.id for gap in read(vault)] == ["g-0001", "g-0002"]


def test_the_summary_reports_the_counts(vault: Path) -> None:
    _add("One")
    _add("Two")
    runner.invoke(app, ["gap", "close", "g-0001", "--no-dry-run"])
    assert "1 open" in schema.parse_article(gaps_path(vault), vault).summary


def test_the_inbox_lints_clean(vault: Path) -> None:
    from kb.commands.lint import check

    _add("A gap with a | pipe and `code` in it")
    assert [f for f in check(vault) if f.severity == "error"] == []


def test_an_explicit_date_is_accepted_and_a_bad_one_is_not(vault: Path) -> None:
    assert runner.invoke(app, ["gap", "add", "X", "--area", "SQL", "--on", "2026-01-02", "--no-dry-run"]).exit_code == 0
    assert read(vault)[0].date == "2026-01-02"
    assert runner.invoke(app, ["gap", "add", "Y", "--area", "SQL", "--on", "whenever", "--no-dry-run"]).exit_code == 1


def test_an_empty_inbox_reads_as_empty(vault: Path) -> None:
    assert read(vault) == []
    assert runner.invoke(app, ["gap", "list"]).exit_code == 0


def test_escaping_does_not_compound_over_repeated_writes(vault: Path) -> None:
    # The real failure: a migration seeded already-escaped text, and every later write
    # escaped it again, reaching five backslashes before the pipe.
    _add("Kibana's ES|QL bar maps to POST /_query")
    for _ in range(4):
        gaps = read(vault)
        from kb.commands.gap import write

        write(vault, gaps)
    (gap,) = read(vault)
    assert gap.text == "Kibana's ES|QL bar maps to POST /_query"
    assert "\\\\|" not in gaps_path(vault).read_text()


def test_a_note_containing_a_pipe_also_survives(vault: Path) -> None:
    _add("Something", note="see a|b")
    (gap,) = read(vault)
    assert gap.note == "see a|b"
