"""Pure embed-builder functions and review/triage helpers for the GitHub cog.

All functions here are stateless and have no Discord.py cog dependencies.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import discord

from bot.github_client import GITHUB_COLOR, GITHUB_API, MAX_TRIAGE_ITEMS

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_RE = re.compile(r"^[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+$")

# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def _ts(iso: str | None) -> str:
    """Return a short human-readable date from an ISO-8601 string."""
    if not iso:
        return "unknown"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return iso[:10]


def _trunc(text: str | None, n: int = 200) -> str:
    if not text:
        return ""
    return text if len(text) <= n else text[:n - 1] + "…"


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Review queue helpers
# ---------------------------------------------------------------------------


def _requested_reviewer_names(pr_data: dict) -> list[str]:
    names: list[str] = []
    for reviewer in pr_data.get("requested_reviewers") or []:
        login = reviewer.get("login")
        if login:
            names.append(login)
    for team in pr_data.get("requested_teams") or []:
        slug = team.get("slug")
        if slug:
            names.append(f"team:{slug}")
    return names


def _summarize_reviews(reviews: list[dict]) -> tuple[int, bool]:
    latest_by_user: dict[str, tuple[datetime, str]] = {}
    for review in reviews:
        user = review.get("user") or {}
        login = user.get("login")
        submitted_at = _parse_iso_dt(review.get("submitted_at")) or datetime.min.replace(tzinfo=timezone.utc)
        state = str(review.get("state") or "").upper()
        if not login or not state:
            continue
        previous = latest_by_user.get(login)
        if previous is None or submitted_at >= previous[0]:
            latest_by_user[login] = (submitted_at, state)

    latest_states = [state for _, state in latest_by_user.values()]
    approvals = sum(1 for state in latest_states if state == "APPROVED")
    changes_requested = any(state == "CHANGES_REQUESTED" for state in latest_states)
    return approvals, changes_requested


def _review_bucket(pr_data: dict, reviews: list[dict], stale_cutoff: datetime) -> str:
    if pr_data.get("draft"):
        return "draft"
    approvals, changes_requested = _summarize_reviews(reviews)
    if changes_requested:
        return "changes_requested"
    if _requested_reviewer_names(pr_data):
        return "review_requested"
    if approvals > 0:
        return "approved"
    updated_at = _parse_iso_dt(pr_data.get("updated_at"))
    if updated_at and updated_at <= stale_cutoff:
        return "stale"
    return "waiting"


def _review_value(pr_data: dict, reviews: list[dict]) -> str:
    author = (pr_data.get("user") or {}).get("login", "?")
    updated_at = _ts(pr_data.get("updated_at"))
    requested = _requested_reviewer_names(pr_data)
    approvals, changes_requested = _summarize_reviews(reviews)
    parts = [f"[View]({pr_data.get('html_url', '')})  •  by `{author}`  •  updated {updated_at}"]
    if requested:
        parts.append(f"Requested: {', '.join(f'`{name}`' for name in requested[:4])}")
    if changes_requested:
        parts.append("Status: `changes requested`")
    elif approvals:
        parts.append(f"Approvals: `{approvals}`")
    return "\n".join(parts)


def _review_load_lines(
    queue: list[tuple[dict, list[dict]]],
    stale_cutoff: datetime,
    *,
    teams: bool = False,
) -> list[str]:
    review_load: dict[str, dict[str, Any]] = {}
    for pr_data, reviews in queue:
        if _review_bucket(pr_data, reviews, stale_cutoff) != "review_requested":
            continue
        updated_at = _parse_iso_dt(pr_data.get("updated_at")) or datetime.now(timezone.utc)
        number = pr_data.get("number")
        title = _trunc(pr_data.get("title", ""), 40)
        for reviewer in _requested_reviewer_names(pr_data):
            is_team = reviewer.startswith("team:")
            if is_team != teams:
                continue
            display_name = reviewer.removeprefix("team:") if is_team else reviewer
            info = review_load.setdefault(
                display_name,
                {"count": 0, "oldest": updated_at, "number": number, "title": title},
            )
            info["count"] += 1
            if updated_at <= info["oldest"]:
                info["oldest"] = updated_at
                info["number"] = number
                info["title"] = title

    lines = []
    for reviewer, info in sorted(review_load.items(), key=lambda item: (-item[1]["count"], item[1]["oldest"]))[:5]:
        lines.append(
            f"`{reviewer}`  •  {info['count']} pending  •  oldest #{info['number']} {_ts(info['oldest'].isoformat())}"
        )
    return lines


def _reviewer_load_lines(queue: list[tuple[dict, list[dict]]], stale_cutoff: datetime) -> list[str]:
    return _review_load_lines(queue, stale_cutoff, teams=False)


def _team_load_lines(queue: list[tuple[dict, list[dict]]], stale_cutoff: datetime) -> list[str]:
    return _review_load_lines(queue, stale_cutoff, teams=True)


# ---------------------------------------------------------------------------
# Discord embed builders — review / triage / issue
# ---------------------------------------------------------------------------


def _build_review_queue_embed(
    repo: str,
    buckets: dict[str, list[tuple[dict, list[dict]]]],
    stale_hours: int,
    reviewer_load_lines: list[str] | None = None,
    team_load_lines: list[str] | None = None,
) -> discord.Embed:
    em = discord.Embed(
        title=f"🔎 PR Review Queue — {repo}",
        url=f"https://github.com/{repo}/pulls",
        description=f"Open PRs grouped by review status. Stale threshold: {stale_hours} hour(s).",
        color=0x2DA44E,
    )
    sections = [
        ("review_requested", "Needs Review"),
        ("changes_requested", "Changes Requested"),
        ("approved", "Approved"),
        ("stale", "Stale"),
        ("waiting", "Waiting"),
    ]
    for key, label in sections:
        items = buckets.get(key) or []
        if not items:
            continue
        value = "\n\n".join(_review_value(pr_data, reviews) for pr_data, reviews in items[:MAX_TRIAGE_ITEMS])
        em.add_field(name=f"{label} ({len(items)})", value=value, inline=False)
    if reviewer_load_lines:
        em.add_field(name="Reviewer Load", value="\n".join(reviewer_load_lines), inline=False)
    if team_load_lines:
        em.add_field(name="Team Load", value="\n".join(team_load_lines), inline=False)
    draft_count = len(buckets.get("draft") or [])
    if draft_count:
        em.set_footer(text=f"{draft_count} draft PR(s) hidden from the active queue")
    return em


def _issue_body(summary: str, reproduction: str | None = None, source_message: discord.Message | None = None) -> str:
    parts = ["## Summary", summary.strip() or "No summary provided."]
    if reproduction and reproduction.strip():
        parts.extend(["", "## Reproduction / Notes", reproduction.strip()])
    if source_message is not None:
        guild_id = source_message.guild.id if source_message.guild else "@me"
        source_link = f"https://discord.com/channels/{guild_id}/{source_message.channel.id}/{source_message.id}"
        excerpt = _trunc(source_message.content or "(no message content)", 500)
        parts.extend(
            [
                "",
                "## Discord Context",
                f"- Source message: {source_link}",
                f"- Author: @{getattr(source_message.author, 'display_name', getattr(source_message.author, 'name', 'unknown'))}",
                "",
                "> " + excerpt.replace("\n", "\n> "),
            ]
        )
    return "\n".join(parts).strip()


def _build_issue_triage_embed(repo: str, issues: list[dict], stale_days: int) -> discord.Embed:
    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=stale_days)
    unassigned = [issue for issue in issues if not issue.get("assignees")]
    unlabeled = [issue for issue in issues if not issue.get("labels")]
    stale = [
        issue
        for issue in issues
        if (_parse_iso_dt(issue.get("updated_at")) or datetime.now(timezone.utc)) <= stale_cutoff
    ]
    em = discord.Embed(
        title=f"🧰 Issue Triage — {repo}",
        url=f"https://github.com/{repo}/issues",
        description=(
            f"Open issues: `{len(issues)}`  •  Unassigned: `{len(unassigned)}`  •  "
            f"Unlabeled: `{len(unlabeled)}`  •  Stale: `{len(stale)}`"
        ),
        color=0xFBCA04,
    )
    sections = [
        ("Unassigned", unassigned),
        ("Unlabeled", unlabeled),
        (f"Stale ({stale_days}d)", stale),
    ]
    for label, section_issues in sections:
        if not section_issues:
            continue
        lines = []
        for issue in section_issues[:MAX_TRIAGE_ITEMS]:
            author = (issue.get("user") or {}).get("login", "?")
            lines.append(
                f"[#{issue.get('number')} {_trunc(issue.get('title', ''), 55)}]({issue.get('html_url', '')})"
                f"  •  by `{author}`  •  updated {_ts(issue.get('updated_at'))}"
            )
        em.add_field(name=label, value="\n".join(lines), inline=False)
    return em


def _should_send_review_digest(now: datetime, hour_utc: int, last_sent_on: str | None) -> bool:
    if now.hour < hour_utc:
        return False
    return last_sent_on != now.date().isoformat()


def _default_issue_template(template_key: str) -> str:
    templates = {
        "bug": "Problem summary\n\nExpected behavior\n\nActual behavior\n\nImpact",
        "feature": "Requested change\n\nWhy it matters\n\nAcceptance criteria",
        "docs": "What is unclear\n\nSuggested documentation update\n\nWho is affected",
    }
    return templates.get(template_key, "")


# ---------------------------------------------------------------------------
# Discord embed builders — API response embeds
# ---------------------------------------------------------------------------


def _make_repo_embed(data: dict) -> discord.Embed:
    em = discord.Embed(
        title=data.get("full_name", ""),
        url=data.get("html_url", ""),
        description=_trunc(data.get("description") or "", 300),
        color=GITHUB_COLOR,
    )
    lang = data.get("language") or "—"
    stars = data.get("stargazers_count", 0)
    forks = data.get("forks_count", 0)
    issues = data.get("open_issues_count", 0)
    watchers = data.get("watchers_count", 0)
    em.add_field(name="Language", value=lang, inline=True)
    em.add_field(name="⭐ Stars", value=f"{stars:,}", inline=True)
    em.add_field(name="🍴 Forks", value=f"{forks:,}", inline=True)
    em.add_field(name="👁️ Watchers", value=f"{watchers:,}", inline=True)
    em.add_field(name="🐛 Open Issues", value=f"{issues:,}", inline=True)
    visibility = "Private 🔒" if data.get("private") else "Public 🌐"
    em.add_field(name="Visibility", value=visibility, inline=True)
    default_branch = data.get("default_branch")
    if default_branch:
        em.add_field(name="Default Branch", value=f"`{default_branch}`", inline=True)
    topics = data.get("topics") or []
    if topics:
        em.add_field(name="Topics", value=" · ".join(f"`{t}`" for t in topics[:10]), inline=False)
    license_data = data.get("license") or {}
    license_name = license_data.get("spdx_id") or license_data.get("name") or "—"
    em.set_footer(text=f"License: {license_name}  |  Created {_ts(data.get('created_at'))}  |  Updated {_ts(data.get('updated_at'))}")
    owner = data.get("owner") or {}
    if owner.get("avatar_url"):
        em.set_thumbnail(url=owner["avatar_url"])
    return em


def _make_user_embed(data: dict) -> discord.Embed:
    em = discord.Embed(
        title=data.get("name") or data.get("login", ""),
        url=data.get("html_url", ""),
        description=_trunc(data.get("bio") or "", 300),
        color=GITHUB_COLOR,
    )
    em.set_thumbnail(url=data.get("avatar_url", ""))
    em.add_field(name="Login", value=f"`{data.get('login', '')}`", inline=True)
    em.add_field(name="Public Repos", value=str(data.get("public_repos", 0)), inline=True)
    em.add_field(name="Followers", value=str(data.get("followers", 0)), inline=True)
    em.add_field(name="Following", value=str(data.get("following", 0)), inline=True)
    if data.get("company"):
        em.add_field(name="Company", value=data["company"], inline=True)
    if data.get("location"):
        em.add_field(name="Location", value=data["location"], inline=True)
    if data.get("blog"):
        em.add_field(name="Website", value=data["blog"], inline=False)
    em.set_footer(text=f"Member since {_ts(data.get('created_at'))}")
    return em


# ---------------------------------------------------------------------------
# Discord embed builders — event notification embeds (polling)
# ---------------------------------------------------------------------------

ZERO_GIT_SHA = "0" * 40


def normalize_rest_commit_for_push(api_commit: dict) -> dict:
    """Map a REST ``commit`` object (compare or /commits) to webhook-style fields.

    GitHub's repository Events feed omits ``payload.commits`` on PushEvent; the
    compare/commits APIs return a different shape. :func:`_push_embed` and
    :func:`_fmt_commit_line` expect webhook-style dicts.
    """
    sha = api_commit.get("sha") or ""
    inner = api_commit.get("commit") or {}
    message = inner.get("message") or ""
    author = inner.get("author") or {}
    committer = inner.get("committer") or {}
    user = api_commit.get("author")
    author_out = {
        "name": author.get("name"),
        "email": author.get("email"),
        "date": author.get("date"),
    }
    if isinstance(user, dict) and user.get("login"):
        author_out["login"] = user["login"]
    html_url = api_commit.get("html_url") or ""
    api_url = api_commit.get("url") or ""
    url = html_url if html_url.startswith("https://github.com") else api_url
    return {
        "id": sha,
        "sha": sha,
        "message": message,
        "url": url,
        "author": author_out,
        "committer": {
            "name": committer.get("name"),
            "email": committer.get("email"),
            "date": committer.get("date"),
        },
        "added": [],
        "removed": [],
        "modified": [],
    }


def _fmt_commit_line(c: dict, repo_url: str) -> str:
    """Format a single commit as a hyperlinked line with author and optional file stats."""
    full_sha = c.get("sha") or c.get("id", "")
    sha = full_sha[:7]
    msg = _trunc((c.get("message") or "").splitlines()[0], 60)
    url = c.get("url", "")
    if not url.startswith("https://github.com"):
        url = f"{repo_url}/commit/{full_sha}"
    author = (c.get("author") or c.get("committer") or {})
    author_name = author.get("login") or author.get("name") or ""
    added = len(c.get("added") or [])
    removed = len(c.get("removed") or [])
    modified = len(c.get("modified") or [])
    stats_parts = []
    if added:
        stats_parts.append(f"+{added}")
    if removed:
        stats_parts.append(f"-{removed}")
    if modified:
        stats_parts.append(f"~{modified}")
    stats = f" `[{', '.join(stats_parts)}]`" if stats_parts else ""
    author_str = f" — `{author_name}`" if author_name else ""
    return f"[`{sha}`]({url}) {msg}{stats}{author_str}"


def _push_embed(repo: str, payload: dict, actor: dict | None = None) -> discord.Embed:
    ref = payload.get("ref", "")
    branch = ref.split("/")[-1] if "/" in ref else ref
    commits = payload.get("commits") or []
    pusher_name = payload.get("pusher", {}).get("name") or (actor or {}).get("login", "someone")
    avatar_url = (actor or {}).get("avatar_url")
    head = payload.get("head_commit") or {}
    repo_url = f"https://github.com/{repo}"
    em = discord.Embed(
        title=f"📦 Push to `{repo}` on `{branch}`",
        url=f"{repo_url}/tree/{branch}",
        color=0x2DA44E,
        timestamp=datetime.now(timezone.utc),
    )
    em.set_author(name=pusher_name, url=f"https://github.com/{pusher_name}", icon_url=avatar_url)

    lines = []
    for c in commits[:6]:
        lines.append(_fmt_commit_line(c, repo_url))
    if len(commits) > 6:
        lines.append(f"…and {len(commits) - 6} more")
    em.description = "\n".join(lines) or _trunc(head.get("message", ""), 200)

    # Head commit detail field
    if head:
        head_sha = (head.get("id") or "")[:7]
        head_url = head.get("url") or f"{repo_url}/commit/{head.get('id', '')}"
        head_author = head.get("author") or {}
        head_committer = head.get("committer") or {}
        head_msg = _trunc((head.get("message") or ""), 200)
        detail_parts = [f"[`{head_sha}`]({head_url})"]
        if head_author.get("name"):
            detail_parts.append(f"**Author:** {head_author['name']}")
            if head_author.get("email"):
                detail_parts[-1] += f" <{head_author['email']}>"
        committer_name = head_committer.get("name") or ""
        if committer_name and committer_name != head_author.get("name"):
            detail_parts.append(f"**Committer:** {committer_name}")
        if head_author.get("date"):
            detail_parts.append(f"**Date:** {_ts(head_author['date'])}")
        added_files = head.get("added") or []
        removed_files = head.get("removed") or []
        modified_files = head.get("modified") or []
        file_parts = []
        if added_files:
            file_parts.append(f"`+{len(added_files)}` added")
        if removed_files:
            file_parts.append(f"`-{len(removed_files)}` removed")
        if modified_files:
            file_parts.append(f"`~{len(modified_files)}` modified")
        if file_parts:
            detail_parts.append("**Files:** " + "  ".join(file_parts))
        if head_msg:
            detail_parts.append(f"```\n{head_msg[:300]}\n```")
        em.add_field(name="Head Commit", value="\n".join(detail_parts), inline=False)

    # Before/after SHAs
    before = (payload.get("before") or "")[:7]
    after = (payload.get("after") or "")[:7]
    if before and after and before != "0000000":
        compare_url = payload.get("compare") or f"{repo_url}/compare/{before}...{after}"
        em.add_field(name="Compare", value=f"[`{before}...{after}`]({compare_url})", inline=True)

    em.set_footer(text=f"{repo}  •  {len(commits)} commit(s)")
    return em


def _pr_embed(repo: str, payload: dict) -> discord.Embed | None:
    action = payload.get("action", "")
    if action not in ("opened", "closed", "reopened", "merged"):
        return None
    pr = payload.get("pull_request") or {}
    if action == "closed" and pr.get("merged"):
        action = "merged"
    color_map = {"opened": 0x2DA44E, "closed": 0xCF222E, "reopened": 0x2DA44E, "merged": 0x8250DF}
    color = color_map.get(action, GITHUB_COLOR)
    icon_map = {"opened": "🟢", "closed": "🔴", "reopened": "🟢", "merged": "🟣"}
    icon = icon_map.get(action, "⚪")
    sender = payload.get("sender", {}).get("login", "")
    sender_avatar = payload.get("sender", {}).get("avatar_url")
    em = discord.Embed(
        title=f"{icon} PR #{pr.get('number')} {action}: {_trunc(pr.get('title', ''), 80)}",
        url=pr.get("html_url", ""),
        description=_trunc(pr.get("body") or "", 300),
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    em.set_author(name=sender, url=f"https://github.com/{sender}", icon_url=sender_avatar)

    base_label = (pr.get("base") or {}).get("label", "")
    head_label = (pr.get("head") or {}).get("label", "")
    head_sha = ((pr.get("head") or {}).get("sha") or "")[:7]
    base_sha = ((pr.get("base") or {}).get("sha") or "")[:7]
    branch_val = f"`{head_label}` → `{base_label}`"
    if head_sha and base_sha:
        branch_val += f"  (`{head_sha}` → `{base_sha}`)"
    em.add_field(name="Branch", value=branch_val, inline=False)

    changed_files = pr.get("changed_files")
    additions = pr.get("additions")
    deletions = pr.get("deletions")
    commits_count = pr.get("commits")
    diff_parts = []
    if changed_files is not None:
        diff_parts.append(f"`{changed_files}` file(s) changed")
    if additions is not None:
        diff_parts.append(f"`+{additions}`")
    if deletions is not None:
        diff_parts.append(f"`-{deletions}`")
    if diff_parts:
        em.add_field(name="Diff", value="  ".join(diff_parts), inline=True)
    if commits_count is not None:
        em.add_field(name="Commits", value=str(commits_count), inline=True)

    # Merge commit info
    if action == "merged":
        merge_sha = (pr.get("merge_commit_sha") or "")[:7]
        merged_by = (pr.get("merged_by") or {}).get("login") or ""
        merge_parts = []
        if merge_sha:
            merge_parts.append(f"`{merge_sha}`")
        if merged_by:
            merge_parts.append(f"by `{merged_by}`")
        if merge_parts:
            em.add_field(name="Merged", value="  ".join(merge_parts), inline=True)

    assignees = [a.get("login", "") for a in (pr.get("assignees") or []) if a.get("login")]
    if assignees:
        em.add_field(name="Assignees", value=" ".join(f"`{a}`" for a in assignees[:5]), inline=True)
    reviewers = _requested_reviewer_names(pr)
    if reviewers:
        em.add_field(name="Reviewers", value=" ".join(f"`{r}`" for r in reviewers[:5]), inline=True)
    labels = [lbl.get("name", "") for lbl in (pr.get("labels") or []) if lbl.get("name")]
    if labels:
        em.add_field(name="Labels", value=" ".join(f"`{l}`" for l in labels[:6]), inline=True)
    milestone = (pr.get("milestone") or {}).get("title")
    if milestone:
        em.add_field(name="Milestone", value=milestone, inline=True)
    em.set_footer(text=repo)
    return em


def _issue_embed(repo: str, payload: dict) -> discord.Embed | None:
    action = payload.get("action", "")
    if action not in ("opened", "closed", "reopened"):
        return None
    issue = payload.get("issue") or {}
    color_map = {"opened": 0x2DA44E, "closed": 0xCF222E, "reopened": 0x2DA44E}
    icon_map = {"opened": "🟢", "closed": "🔴", "reopened": "🟢"}
    sender = payload.get("sender", {}).get("login", "")
    em = discord.Embed(
        title=f"{icon_map.get(action, '⚪')} Issue #{issue.get('number')} {action}: {_trunc(issue.get('title', ''), 80)}",
        url=issue.get("html_url", ""),
        description=_trunc(issue.get("body") or "", 300),
        color=color_map.get(action, GITHUB_COLOR),
        timestamp=datetime.now(timezone.utc),
    )
    em.set_author(name=sender, url=f"https://github.com/{sender}",
                  icon_url=payload.get("sender", {}).get("avatar_url"))
    labels = [lbl.get("name", "") for lbl in (issue.get("labels") or [])]
    if labels:
        em.add_field(name="Labels", value=" ".join(f"`{l}`" for l in labels[:6]), inline=False)
    assignees = [a.get("login", "") for a in (issue.get("assignees") or []) if a.get("login")]
    if assignees:
        em.add_field(name="Assignees", value=" ".join(f"`{a}`" for a in assignees[:5]), inline=True)
    milestone = (issue.get("milestone") or {}).get("title")
    if milestone:
        em.add_field(name="Milestone", value=milestone, inline=True)
    comments = issue.get("comments")
    footer_parts = [repo]
    if comments is not None:
        footer_parts.append(f"{comments} comment(s)")
    em.set_footer(text="  •  ".join(footer_parts))
    return em


def _release_embed(repo: str, payload: dict) -> discord.Embed | None:
    action = payload.get("action", "")
    if action not in ("published", "released"):
        return None
    release = payload.get("release") or {}
    sender = payload.get("sender", {}).get("login", "")
    em = discord.Embed(
        title=f"🚀 Release: {_trunc(release.get('name') or release.get('tag_name', ''), 80)}",
        url=release.get("html_url", ""),
        description=_trunc(release.get("body") or "", 400),
        color=0xFBCA04,
        timestamp=datetime.now(timezone.utc),
    )
    em.set_author(name=sender, url=f"https://github.com/{sender}",
                  icon_url=payload.get("sender", {}).get("avatar_url"))
    em.add_field(name="Tag", value=f"`{release.get('tag_name', '?')}`", inline=True)
    em.add_field(name="Pre-release", value="Yes" if release.get("prerelease") else "No", inline=True)
    target = release.get("target_commitish")
    if target:
        em.add_field(name="Branch / Target", value=f"`{target}`", inline=True)
    assets = release.get("assets") or []
    if assets:
        total_downloads = sum(a.get("download_count", 0) for a in assets)
        em.add_field(name="Assets", value=f"{len(assets)} ({total_downloads:,} downloads)", inline=True)
    em.set_footer(text=repo)
    return em
