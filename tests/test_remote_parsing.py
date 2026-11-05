import pytest

from pr_review_agent.adapters.azure_devops import (
    azure_from_args,
    parse_azure_pr_url,
    parse_azure_remote,
)
from pr_review_agent.adapters.github import (
    github_from_args,
    parse_github_pr_url,
    parse_github_remote,
)
from pr_review_agent.errors import ConfigError

GH_ENV = {"GITHUB_TOKEN": "t"}
AZ_ENV = {"AZURE_DEVOPS_PAT": "p"}


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/acme/widgets",
        "https://github.com/acme/widgets.git",
        "https://github.com/acme/widgets/",
        "https://user@github.com/acme/widgets.git",
        "git@github.com:acme/widgets.git",
        "git@github.com:acme/widgets",
        "ssh://git@github.com/acme/widgets.git",
    ],
)
def test_github_remote_forms(url):
    assert parse_github_remote(url) == ("acme", "widgets")


def test_github_remote_rejects_other_hosts():
    assert parse_github_remote("https://gitlab.com/acme/widgets.git") is None
    assert parse_github_remote("https://dev.azure.com/o/p/_git/r") is None


def test_github_pr_url():
    assert parse_github_pr_url("https://github.com/acme/widgets/pull/42/files") == (
        "acme",
        "widgets",
        42,
    )
    assert parse_github_pr_url("https://github.com/acme/widgets/issues/42") is None


@pytest.mark.parametrize(
    "url,base",
    [
        ("https://dev.azure.com/org/proj/_git/repo", "https://dev.azure.com/org"),
        ("https://user@dev.azure.com/org/proj/_git/repo", "https://dev.azure.com/org"),
        ("git@ssh.dev.azure.com:v3/org/proj/repo", "https://dev.azure.com/org"),
        ("https://org.visualstudio.com/proj/_git/repo", "https://org.visualstudio.com"),
        (
            "https://org.visualstudio.com/DefaultCollection/proj/_git/repo",
            "https://org.visualstudio.com",
        ),
    ],
)
def test_azure_remote_forms(url, base):
    c = parse_azure_remote(url)
    assert (c.base_url, c.organization, c.project, c.repository) == (base, "org", "proj", "repo")


def test_azure_remote_decodes_spaces():
    c = parse_azure_remote("https://dev.azure.com/org/My%20Project/_git/my%20repo")
    assert (c.project, c.repository) == ("My Project", "my repo")


def test_azure_remote_rejects_other_hosts_and_pr_urls():
    assert parse_azure_remote("https://github.com/acme/widgets") is None
    assert parse_azure_remote("https://dev.azure.com/org/proj/_git/repo/pullrequest/3") is None


def test_azure_pr_url():
    c, n = parse_azure_pr_url("https://dev.azure.com/org/proj/_git/repo/pullrequest/17")
    assert (c.repository, n) == ("repo", 17)


def test_github_pr_url_mismatch():
    with pytest.raises(ConfigError, match="PR URL is for other/thing but remote points to acme/widgets"):
        github_from_args(
            "https://github.com/acme/widgets.git", "https://github.com/other/thing/pull/1", GH_ENV
        )


def test_github_mismatch_is_case_insensitive():
    github_from_args(
        "https://github.com/Acme/Widgets.git", "https://github.com/acme/widgets/pull/1", GH_ENV
    )


def test_azure_pr_url_mismatch():
    with pytest.raises(ConfigError, match="PR URL is for"):
        azure_from_args(
            "https://dev.azure.com/org/proj/_git/repo",
            "https://dev.azure.com/org/proj/_git/other/pullrequest/1",
            AZ_ENV,
        )


def test_wrong_adapter_for_remote():
    with pytest.raises(ConfigError, match="not a github.com repository"):
        github_from_args("https://dev.azure.com/org/proj/_git/repo", "1", GH_ENV)
    with pytest.raises(ConfigError, match="not an Azure DevOps repository"):
        azure_from_args("https://github.com/acme/widgets.git", "1", AZ_ENV)


def test_missing_tokens():
    with pytest.raises(ConfigError, match="GITHUB_TOKEN"):
        github_from_args("https://github.com/acme/widgets.git", "1", {})
    with pytest.raises(ConfigError, match="AZURE_DEVOPS_PAT"):
        azure_from_args("https://dev.azure.com/org/proj/_git/repo", "1", {})


def test_bad_pr_arg():
    with pytest.raises(ConfigError, match="--pr must be"):
        github_from_args("https://github.com/acme/widgets.git", "abc", GH_ENV)
