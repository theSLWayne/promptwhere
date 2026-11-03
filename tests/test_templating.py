from pathlib import Path

import pytest

from promptwhere import MissingVariables, Prompt, PromptNotFound, PromptWhere, VersionNotFound
from promptwhere.templating import find_variables


@pytest.fixture
def store(tmp_path: Path) -> PromptWhere:
    return PromptWhere(tmp_path / "prompts")


# --- variable detection --------------------------------------------------------


def test_variables_listed_in_order_without_duplicates(store: PromptWhere) -> None:
    prompt = store.save("p", "Hi {name}, welcome to {company}. Bye {name}.")
    assert prompt.variables == ["name", "company"]


def test_no_variables(store: PromptWhere) -> None:
    assert store.save("p", "plain text").variables == []


def test_escaped_braces_are_not_variables() -> None:
    assert find_variables("literal {{braces}} and {x}") == ["x"]


def test_attribute_and_index_use_root_name() -> None:
    assert find_variables("{user.name} {items[0]} {user.age}") == ["user", "items"]


def test_format_spec_and_conversion_are_handled() -> None:
    template = "{price:.2f} {name!r} {value:{width}}"
    assert find_variables(template) == ["price", "name", "value", "width"]


@pytest.mark.parametrize("template", ["{}", "{0}", '{"a": 1}', "{ x }", "oops {", "oops }"])
def test_unsupported_templates_raise_helpful_error(template: str) -> None:
    with pytest.raises(ValueError, match=r"\{\{|Invalid template"):
        find_variables(template)


# --- render ----------------------------------------------------------------------


def test_render_fills_variables(store: PromptWhere) -> None:
    store.save("p", "Hello {name} from {company}")
    assert store.render("p", name="Ada", company="Acme") == "Hello Ada from Acme"


def test_prompt_render(store: PromptWhere) -> None:
    prompt = store.save("p", "Hello {name}")
    assert isinstance(prompt, Prompt)
    assert prompt.render(name="Ada") == "Hello Ada"


def test_render_unescapes_literal_braces(store: PromptWhere) -> None:
    store.save("p", 'Reply as JSON: {{"answer": "{x}"}}')
    assert store.render("p", x="42") == 'Reply as JSON: {"answer": "42"}'


def test_render_supports_format_specs_and_attributes(store: PromptWhere) -> None:
    class User:
        name = "Ada"

    store.save("p", "{user.name} paid {price:.2f}")
    assert store.render("p", user=User(), price=3.14159) == "Ada paid 3.14"


def test_extra_variables_are_ignored(store: PromptWhere) -> None:
    store.save("p", "Hi {name}")
    assert store.render("p", name="Ada", unused=1) == "Hi Ada"


def test_template_without_variables_renders_as_is(store: PromptWhere) -> None:
    store.save("p", "no variables here")
    assert store.render("p") == "no variables here"


def test_render_uses_latest_by_default_and_specific_version(store: PromptWhere) -> None:
    store.save("p", "v1 {x}")
    store.save("p", "v2 {x}")
    assert store.render("p", x="a") == "v2 a"
    assert store.render("p", version=1, x="a") == "v1 a"


def test_render_does_not_change_stored_template(store: PromptWhere) -> None:
    store.save("p", "Hi {name}")
    store.render("p", name="Ada")
    assert store.get("p").template == "Hi {name}"
    assert len(store.history("p")) == 1


# --- MissingVariables ----------------------------------------------------------------


def test_missing_variables_are_named(store: PromptWhere) -> None:
    store.save("p", "{a} {b} {c}")
    with pytest.raises(MissingVariables) as info:
        store.render("p", b="x")
    assert info.value.missing == ["a", "c"]
    assert info.value.name == "p"
    message = str(info.value)
    assert "a, c" in message and "'p'" in message


def test_missing_variables_on_prompt_render(store: PromptWhere) -> None:
    prompt = store.save("p", "Hi {name}")
    with pytest.raises(MissingVariables, match="name"):
        prompt.render()


def test_missing_variable_inside_format_spec(store: PromptWhere) -> None:
    store.save("p", "{value:{width}}")
    with pytest.raises(MissingVariables, match="width"):
        store.render("p", value=1)


def test_render_errors_for_unknown_prompt_and_version(store: PromptWhere) -> None:
    store.save("chatbot", "x")
    with pytest.raises(PromptNotFound):
        store.render("chatbt")
    with pytest.raises(VersionNotFound):
        store.render("chatbot", version=9)


def test_variable_named_name_works(store: PromptWhere) -> None:
    store.save("p", "Hi {name}")
    assert store.render("p", name="Ada") == "Hi Ada"


def test_variable_named_version_via_prompt_render(store: PromptWhere) -> None:
    store.save("p", "Release {version}")
    assert store.get("p").render(version="2.0") == "Release 2.0"
