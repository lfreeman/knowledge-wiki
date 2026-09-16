"""`kb search` — which articles already cover a subject.

The command exists for one decision, update-vs-create, so the tests are about whether it
surfaces the article you were about to duplicate.
"""

import json
from pathlib import Path

from conftest import ArticleWriter
from typer.testing import CliRunner

from kb.cli import app
from kb.commands.search import find

runner = CliRunner()


def test_it_finds_an_article_by_its_title(article: ArticleWriter, vault: Path) -> None:
    article("guides/streaming", title="S3 Streaming Reference")
    article("runbooks/unrelated", title="Restarting Something")
    assert [match.slug for match in find(vault, ["streaming"])] == ["guides/streaming"]


def test_an_article_about_the_subject_outranks_one_that_merely_mentions_it(
    article: ArticleWriter, vault: Path
) -> None:
    # The whole point: separate "about this" from "mentions this once".
    article("guides/about-it", title="S3 Streaming", summary="How S3 streaming works.", systems=["S3"])
    article("runbooks/mentions-it", title="Restarting Something", body="Afterwards, check S3 for leftovers.\n")
    matches = find(vault, ["s3"])
    assert [match.slug for match in matches] == ["guides/about-it", "runbooks/mentions-it"]
    assert matches[0].score > matches[1].score


def test_a_body_only_match_is_still_returned(article: ArticleWriter, vault: Path) -> None:
    article("runbooks/mentions-it", title="Restarting", body="Check the widget afterwards.\n")
    (match,) = find(vault, ["widget"])
    assert match.matched == ["body"]


def test_an_article_matching_every_term_outranks_a_partial_one(article: ArticleWriter, vault: Path) -> None:
    # Deliberately not a strict AND: a four-word query that nothing satisfies used to
    # return nothing, while an article matching three of four sat there unmentioned.
    article("guides/one", title="S3 Streaming", body="About streaming.\n")
    article("guides/two", title="Kafka Streaming", body="About kafka.\n")
    matches = find(vault, ["s3", "streaming"])
    assert [match.slug for match in matches] == ["guides/one", "guides/two"]
    assert matches[0].terms_found == ["s3", "streaming"]
    assert matches[1].terms_missing == ["s3"]


def test_an_article_matching_no_term_is_not_returned(article: ArticleWriter, vault: Path) -> None:
    article("guides/one", title="S3 Streaming")
    assert find(vault, ["kafka", "rabbitmq"]) == []


def test_the_output_says_how_many_matched_every_term(article: ArticleWriter, vault: Path) -> None:
    article("guides/one", title="S3 Streaming")
    article("guides/two", title="Kafka Streaming")
    output = runner.invoke(app, ["search", "s3", "streaming"]).output
    assert "1 with all 2 of 2" in output
    assert "1 with 1 of 2" in output


def test_it_warns_when_nothing_matched_every_term(article: ArticleWriter, vault: Path) -> None:
    # Otherwise you cannot tell "nothing covers this" from "one of my words was wrong".
    article("guides/one", title="S3 Streaming")
    output = runner.invoke(app, ["search", "s3", "kafka"]).output
    assert "Nothing matched all 2 terms" in output


def test_terms_may_match_in_different_fields(article: ArticleWriter, vault: Path) -> None:
    article("guides/split", title="Streaming Reference", systems=["S3"], body="Nothing else.\n")
    assert [match.slug for match in find(vault, ["s3", "streaming"])] == ["guides/split"]


def test_matching_is_case_insensitive(article: ArticleWriter, vault: Path) -> None:
    article("guides/one", title="S3 Streaming")
    assert find(vault, ["S3"]) and find(vault, ["s3"])


def test_a_repeated_body_mention_cannot_outrank_a_title(article: ArticleWriter, vault: Path) -> None:
    # A document saying "S3" fifty times is not thereby more about S3 than one titled S3.
    article("guides/titled", title="S3 Streaming")
    article("runbooks/repeats", title="Something Else", body="S3 " * 50)
    matches = find(vault, ["s3"])
    assert matches[0].slug == "guides/titled"


def test_it_reports_where_each_term_was_found(article: ArticleWriter, vault: Path) -> None:
    article("guides/one", title="S3 Streaming", summary="About S3.", systems=["S3"], body="More on S3.\n")
    (match,) = find(vault, ["s3"])
    assert set(match.matched) == {"title", "summary", "systems", "body"}


def test_the_slug_counts_as_a_place_a_term_can_match(article: ArticleWriter, vault: Path) -> None:
    article("guides/s3-streaming", title="Streaming Reference")
    (match,) = find(vault, ["s3"])
    assert "slug" in match.matched


def test_it_points_at_the_first_body_line_that_matched(article: ArticleWriter, vault: Path) -> None:
    article("guides/one", title="A Guide", body="First line.\n\nThe widget is here.\n")
    (match,) = find(vault, ["widget"])
    assert match.line is not None
    on_disk = (vault / "guides" / "one.md").read_text().splitlines()
    assert "widget" in on_disk[match.line - 1]


def test_results_are_stable_between_runs(article: ArticleWriter, vault: Path) -> None:
    for name in ("alpha", "bravo", "charlie"):
        article(f"guides/{name}", title=f"S3 {name.title()}")
    assert [m.slug for m in find(vault, ["s3"])] == [m.slug for m in find(vault, ["s3"])]


def test_nothing_matching_returns_nothing(article: ArticleWriter, vault: Path) -> None:
    article("guides/one", title="S3 Streaming")
    assert find(vault, ["kafka"]) == []


def test_the_command_says_so_when_nothing_covers_the_subject(article: ArticleWriter, vault: Path) -> None:
    article("guides/one", title="S3 Streaming")
    result = runner.invoke(app, ["search", "kafka"])
    assert result.exit_code == 0
    assert "new article" in result.output


def test_the_command_prints_an_absolute_path(article: ArticleWriter, vault: Path) -> None:
    # A relative path:line is not resolvable from wherever the shell is, so the terminal
    # guesses it is a URL and hands it to a browser instead of opening the file.
    article("guides/one", title="A Guide", body="The widget is here.\n")
    output = runner.invoke(app, ["search", "widget"]).output
    assert str(vault / "guides" / "one") in output.replace("\n", "")


def test_the_command_shows_how_many_terms_each_result_matched(article: ArticleWriter, vault: Path) -> None:
    article("guides/one", title="S3 Streaming")
    assert "1/1 terms" in runner.invoke(app, ["search", "s3"]).output


def test_limit_caps_the_results(article: ArticleWriter, vault: Path) -> None:
    for name in ("alpha", "bravo", "charlie"):
        article(f"guides/{name}", title=f"S3 {name.title()}")
    payload = json.loads(runner.invoke(app, ["search", "s3", "--limit", "2", "--json"]).output)
    assert payload["count"] == 2


def test_json_carries_what_an_agent_needs_to_decide(article: ArticleWriter, vault: Path) -> None:
    article("guides/one", title="S3 Streaming", summary="How it works.", status="active")
    payload = json.loads(runner.invoke(app, ["search", "s3", "--json"]).output)
    (match,) = payload["matches"]
    assert match["title"] == "S3 Streaming"
    assert match["summary"] == "How it works."
    assert match["status"] == "active"
    assert match["score"] > 0


def test_a_missing_vault_is_a_one_line_error(tmp_path: Path) -> None:
    assert runner.invoke(app, ["search", "s3"], env={"KB_VAULT": str(tmp_path / "nope")}).exit_code == 1


def test_a_question_finds_an_article_that_uses_a_different_word_form(
    article: ArticleWriter, vault: Path
) -> None:
    # The real miss: the article says "population" and "generator", the question says
    # "populate" and "generate". Substring matching cannot bridge that, and it is exactly
    # the pair a question and an article naturally disagree on.
    article("research/gen", title="Location Data Generator", summary="Shapes population density.")
    assert [match.slug for match in find(vault, ["populate"])] == ["research/gen"]
    assert [match.slug for match in find(vault, ["generate"])] == ["research/gen"]


def test_stemming_converges_for_verb_and_noun_forms() -> None:
    from kb.commands.search import _stem

    assert _stem("populate") == _stem("population")
    assert _stem("generate") == _stem("generator") == _stem("generation")
    assert _stem("timeouts") == _stem("timeout")


def test_short_words_are_not_stemmed_into_each_other() -> None:
    from kb.commands.search import _stem

    assert _stem("data") == "data"
    assert _stem("s3") == "s3"
    assert _stem("es") == "es"


def test_an_exact_match_still_outranks_a_stemmed_one(article: ArticleWriter, vault: Path) -> None:
    article("research/exact", title="Generate Data", summary="About generate.")
    article("research/stemmed", body="Something about a generator.\n")
    matches = find(vault, ["generate"])
    assert matches[0].slug == "research/exact"


def test_stemming_does_not_make_everything_match(article: ArticleWriter, vault: Path) -> None:
    article("research/gen", title="Generator", summary="Shapes population density.")
    article("runbooks/unrelated", title="Restarting Something", body="Nothing in common.\n")
    assert [match.slug for match in find(vault, ["populate"])] == ["research/gen"]


def test_a_superseded_article_ranks_below_a_current_one(article: ArticleWriter, vault: Path) -> None:
    # A plan whose work shipped must never outrank the article describing what exists now.
    article("research/old-plan", title="Widget Plan", summary="How widgets will work.", status="superseded")
    article("systems/widgets", title="Widget System", summary="How widgets work.")
    assert [match.slug for match in find(vault, ["widget"])] == ["systems/widgets", "research/old-plan"]


def test_a_superseded_article_is_still_found(article: ArticleWriter, vault: Path) -> None:
    article("research/old-plan", title="Widget Plan", status="superseded")
    assert [match.slug for match in find(vault, ["widget"])] == ["research/old-plan"]
