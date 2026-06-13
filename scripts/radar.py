#!/usr/bin/env python3
import argparse
import json
import math
import os
import sys
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path


API_ROOT = "https://api.github.com"
KST = timezone(timedelta(hours=9))
TRENDING_REPO_LIMIT = 10


@dataclass
class Candidate:
    full_name: str
    html_url: str
    description: str
    language: str
    topics: list[str]
    stars: int
    forks: int
    open_issues: int
    created_at: datetime
    pushed_at: datetime
    query_name: str
    score: float


class TrendingRepoNameParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.article_depth = 0
        self.in_heading = False
        self.names: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name: value or "" for name, value in attrs}
        class_name = attr_map.get("class", "")

        if tag == "article" and "Box-row" in class_name:
            self.article_depth += 1
            return

        if self.article_depth and tag == "h2":
            self.in_heading = True
            return

        if self.article_depth and self.in_heading and tag == "a":
            href = attr_map.get("href", "").strip()
            parts = [part for part in href.strip("/").split("/") if part]
            if len(parts) == 2:
                full_name = "/".join(parts)
                if full_name not in self.names:
                    self.names.append(full_name)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2":
            self.in_heading = False
        elif tag == "article" and self.article_depth:
            self.article_depth -= 1


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def github_request(path: str, token: str | None) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-trend-radar",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(f"{API_ROOT}{path}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API error {exc.code}: {detail}") from exc


def search_repositories(query: str, token: str | None, per_page: int = 20) -> list[dict]:
    params = urllib.parse.urlencode(
        {
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": per_page,
        }
    )
    data = github_request(f"/search/repositories?{params}", token)
    return data.get("items", [])


def fetch_repository(full_name: str, token: str | None) -> dict:
    encoded = urllib.parse.quote(full_name, safe="/")
    return github_request(f"/repos/{encoded}", token)


def fetch_github_trending_repo_names() -> list[str]:
    req = urllib.request.Request(
        "https://github.com/trending?since=daily&spoken_language_code=",
        headers={
            "Accept": "text/html",
            "User-Agent": "Mozilla/5.0 (compatible; github-trend-radar/1.0)",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        parser = TrendingRepoNameParser()
        parser.feed(res.read().decode("utf-8", errors="replace"))
        return parser.names[:TRENDING_REPO_LIMIT]


def build_queries(now: datetime) -> list[tuple[str, str]]:
    since_90 = (now - timedelta(days=90)).date().isoformat()
    since_180 = (now - timedelta(days=180)).date().isoformat()
    pushed_30 = (now - timedelta(days=30)).date().isoformat()

    return [
        ("new-high-signal", f"created:>={since_90} stars:>80 fork:false archived:false"),
        ("ai-agents", f"topic:ai-agents created:>={since_180} stars:>20 fork:false archived:false"),
        ("mcp", f"topic:mcp created:>={since_180} stars:>20 fork:false archived:false"),
        ("llm-tools", f"topic:llm created:>={since_180} stars:>30 fork:false archived:false"),
        ("devtools", f"topic:developer-tools pushed:>={pushed_30} stars:>100 fork:false archived:false"),
        ("automation", f"topic:automation pushed:>={pushed_30} stars:>80 fork:false archived:false"),
        ("observability", f"topic:observability pushed:>={pushed_30} stars:>100 fork:false archived:false"),
        ("security", f"topic:security-tools pushed:>={pushed_30} stars:>80 fork:false archived:false"),
        ("browser-automation", f"topic:browser-automation pushed:>={pushed_30} stars:>30 fork:false archived:false"),
        ("databases", f"topic:database pushed:>={pushed_30} stars:>200 fork:false archived:false"),
    ]


def score_repo(repo: dict, now: datetime) -> float:
    stars = int(repo.get("stargazers_count") or 0)
    forks = int(repo.get("forks_count") or 0)
    open_issues = int(repo.get("open_issues_count") or 0)
    created_at = parse_time(repo["created_at"])
    pushed_at = parse_time(repo["pushed_at"])

    age_days = max(1, (now - created_at).days)
    stale_days = max(0, (now - pushed_at).days)
    stars_per_day = stars / age_days
    capped_growth = min(stars_per_day, 250)
    fork_ratio = forks / max(stars, 1)

    recency_bonus = max(0, 30 - stale_days) * 0.35
    issue_penalty = min(open_issues, 500) * 0.004

    return (
        math.log1p(stars) * 8
        + capped_growth * 28
        + math.log1p(forks) * 3
        + min(fork_ratio, 0.45) * 16
        + recency_bonus
        - issue_penalty
    )


def build_candidate(repo: dict, query_name: str, now: datetime, score_bonus: float = 0.0) -> Candidate:
    return Candidate(
        full_name=repo["full_name"],
        html_url=repo["html_url"],
        description=(repo.get("description") or "").strip(),
        language=repo.get("language") or "Unknown",
        topics=repo.get("topics") or [],
        stars=int(repo.get("stargazers_count") or 0),
        forks=int(repo.get("forks_count") or 0),
        open_issues=int(repo.get("open_issues_count") or 0),
        created_at=parse_time(repo["created_at"]),
        pushed_at=parse_time(repo["pushed_at"]),
        query_name=query_name,
        score=score_repo(repo, now) + score_bonus,
    )


def technical_reason(candidate: Candidate) -> str:
    text = " ".join(
        [
            candidate.full_name,
            candidate.description,
            candidate.language,
            " ".join(candidate.topics),
        ]
    ).lower()

    if "mcp" in text:
        return "MCP 생태계와 agent-tool 연결 방식을 읽어볼 수 있습니다."
    if "agent" in text or "llm" in text or "ai" in text:
        return "AI agent 구조, tool orchestration, LLM 통합 패턴을 관찰하기 좋습니다."
    if "browser" in text or "playwright" in text or "automation" in text:
        return "브라우저/업무 자동화 흐름을 실제 코드로 확인하기 좋습니다."
    if "observability" in text or "monitor" in text or "telemetry" in text:
        return "운영 관측성, 이벤트 모델, 대시보드 데이터 흐름을 공부하기 좋습니다."
    if "security" in text or "scanner" in text or "vulnerability" in text:
        return "보안 자동화와 코드/의존성 분석 파이프라인을 살펴보기 좋습니다."
    if "database" in text or "query" in text or "storage" in text:
        return "스토리지, 쿼리 엔진, 성능 최적화 관점을 익히기 좋습니다."
    return "최근 성장 속도와 활동성이 높아 구현 방식과 제품 포지셔닝을 확인할 가치가 있습니다."


def automation_idea(candidate: Candidate) -> str:
    text = " ".join([candidate.description, " ".join(candidate.topics)]).lower()
    if "mcp" in text:
        return "자주 쓰는 SaaS나 로컬 도구를 MCP 서버로 감싸 Codex에서 호출하는 실험을 해보세요."
    if "agent" in text or "llm" in text:
        return "README를 입력하면 agent loop, tools, memory, eval 구조를 자동 추출하는 repo reader를 만들어보세요."
    if "browser" in text or "automation" in text:
        return "반복 웹 작업을 Playwright script로 녹화하고 Codex가 유지보수하는 자동화 템플릿을 만들어보세요."
    if "security" in text:
        return "매주 dependency/security 릴리스를 요약하고 위험도별 이슈를 여는 보안 레이더를 만들어보세요."
    return "관심 repo의 README, examples, issues를 요약해 1시간 학습 과제로 바꾸는 Codex workflow를 만들어보세요."


def collect_candidates(token: str | None, now: datetime) -> tuple[list[Candidate], list[str]]:
    seen: dict[str, Candidate] = {}
    warnings: list[str] = []

    try:
        trending_names = fetch_github_trending_repo_names()
        if not trending_names:
            warnings.append("github-trending: parsed 0 repositories from github.com/trending")
        for full_name in trending_names:
            try:
                repo = fetch_repository(full_name, token)
            except Exception as exc:
                warnings.append(f"github-trending/{full_name}: {exc}")
                continue
            seen[full_name] = build_candidate(repo, "github-trending", now, score_bonus=70)
    except Exception as exc:
        warnings.append(f"github-trending: {exc}")

    for name, query in build_queries(now):
        try:
            repos = search_repositories(query, token)
        except Exception as exc:
            warnings.append(f"{name}: {exc}")
            continue

        for repo in repos:
            full_name = repo["full_name"]
            if full_name in seen:
                continue

            seen[full_name] = build_candidate(repo, name, now)

    return sorted(seen.values(), key=lambda item: item.score, reverse=True), warnings


def render_report(candidates: list[Candidate], warnings: list[str], max_repos: int, now: datetime) -> str:
    top = candidates[:max_repos]
    local_now = now.astimezone(KST)
    date_text = local_now.strftime("%Y-%m-%d")
    lines: list[str] = [
        f"# GitHub Trend Radar - {date_text}",
        "",
        "빠르게 성장 중인 개발 도구, AI agent/MCP, 인프라, 보안, 자동화 관련 repository 후보입니다.",
        "",
    ]

    if not top:
        lines.extend(
            [
                "수집된 후보가 없습니다.",
                "",
                "GitHub API rate limit, 네트워크, 검색 조건을 확인하세요.",
            ]
        )
        return "\n".join(lines) + "\n"

    lines.extend(["## Top Repositories", ""])
    for idx, candidate in enumerate(top, start=1):
        desc = candidate.description or "No description."
        age_days = max(1, (now - candidate.created_at).days)
        stars_per_day = candidate.stars / age_days
        topic_text = ", ".join(candidate.topics[:6]) if candidate.topics else "no topics"
        lines.extend(
            [
                f"### {idx}. [{candidate.full_name}]({candidate.html_url})",
                "",
                f"- Score: {candidate.score:.1f}",
                f"- Stars: {candidate.stars:,} ({stars_per_day:.1f}/day since creation)",
                f"- Forks: {candidate.forks:,}",
                f"- Language: {candidate.language}",
                f"- Created: {candidate.created_at.date().isoformat()}",
                f"- Last push: {candidate.pushed_at.date().isoformat()}",
                f"- Signal: `{candidate.query_name}`",
                f"- Topics: {topic_text}",
                f"- Summary: {desc}",
                f"- Why it matters: {technical_reason(candidate)}",
                "",
            ]
        )

    deep = top[0]
    lines.extend(
        [
            "## Deep Dive Pick",
            "",
            f"[{deep.full_name}]({deep.html_url})",
            "",
            "30-60분 과제:",
            "",
            "1. README에서 핵심 문제 정의와 target user를 5줄로 요약합니다.",
            "2. `examples`, `cmd`, `src`, `packages` 중 실제 entrypoint 하나를 찾아 실행 흐름을 추적합니다.",
            "3. dependency 3개를 골라 왜 필요한지 적습니다.",
            "4. 가장 작은 기능 하나를 로컬에서 실행하거나 테스트합니다.",
            "5. 내 작업 흐름에 붙일 수 있는 자동화 지점 하나를 적습니다.",
            "",
            "## Codex Automation Idea",
            "",
            automation_idea(deep),
            "",
        ]
    )

    if warnings:
        lines.extend(["## Warnings", ""])
        for warning in warnings:
            wrapped = textwrap.fill(warning, width=100)
            lines.append(f"- {wrapped}")
        lines.append("")

    return "\n".join(lines) + "\n"


def create_issue(token: str, repo_name: str, title: str, body: str) -> None:
    payload = json.dumps({"title": title, "body": body}).encode("utf-8")
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "github-trend-radar",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    req = urllib.request.Request(
        f"{API_ROOT}/repos/{repo_name}/issues",
        data=payload,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        if res.status not in (200, 201):
            raise RuntimeError(f"Unexpected issue response: {res.status}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a GitHub trend radar report.")
    parser.add_argument("--output", default="reports/latest.md", help="Markdown report path.")
    parser.add_argument("--max-repos", type=int, default=int(os.getenv("MAX_REPOS", "10")))
    parser.add_argument("--create-issue", action="store_true", default=os.getenv("CREATE_ISSUE") == "true")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    token = os.getenv("GITHUB_TOKEN")
    candidates, warnings = collect_candidates(token, now)
    report = render_report(candidates, warnings, args.max_repos, now)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")

    dated_output = output.parent / f"{now.astimezone(KST).date().isoformat()}.md"
    dated_output.write_text(report, encoding="utf-8")

    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        Path(summary_path).write_text(report, encoding="utf-8")

    if args.create_issue:
        repo_name = os.getenv("GITHUB_REPOSITORY")
        if not token or not repo_name:
            print("Skipping issue creation: GITHUB_TOKEN or GITHUB_REPOSITORY is missing.", file=sys.stderr)
        else:
            title = f"GitHub Trend Radar - {now.astimezone(KST).date().isoformat()}"
            create_issue(token, repo_name, title, report)

    print(f"Wrote {output}")
    print(f"Candidates: {len(candidates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
