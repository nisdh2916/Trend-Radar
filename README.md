# GitHub Trend Radar

휴대폰에서 읽기 좋은 주간 GitHub 트렌드 레이더입니다.

이 repo는 GitHub Actions에서 매주 실행되어 빠르게 성장하는 개발 도구, AI agent/MCP, 인프라, 보안, 자동화 관련 repository를 찾고 Markdown 리포트와 GitHub Issue를 만듭니다. 로컬 PC를 켜둘 필요가 없습니다.

## 동작 방식

- GitHub Search API로 후보 repository를 수집합니다.
- `github.com/trending`에서 오늘의 Trending repository 이름을 읽고, 상세 정보는 GitHub API로 다시 조회합니다.
- 별도 DB 없이 현재 시점의 stars, repo age, forks, 최근 push를 조합해 "rising score"를 계산합니다.
- `reports/latest.md`와 날짜별 리포트를 커밋합니다.
- GitHub Issue를 생성해서 GitHub 모바일 앱에서 확인할 수 있게 합니다.
- 같은 날짜 Issue가 이미 열려 있으면 중복 Issue 생성을 건너뜁니다.

## 빠른 시작

1. GitHub에서 새 repository를 만듭니다.
2. 이 폴더의 파일들을 새 repository에 push합니다.
3. GitHub repository의 `Actions` 탭에서 workflow 실행을 허용합니다.
4. GitHub 모바일 앱에서 해당 repository 알림을 켭니다.
5. `Actions > GitHub Trend Radar > Run workflow`로 수동 실행해봅니다.

기본 스케줄은 매주 월요일 오전 9시(KST)입니다.

## 결과물

리포트에는 다음이 포함됩니다.

- 빠르게 성장 중인 repository 10개
- 각 repo가 기술적으로 볼 만한 이유
- 하나의 deep dive 추천
- 30-60분 hands-on 과제
- 다음에 만들 만한 Codex/automation/plugin 아이디어

## 설정

필수 secret은 없습니다. GitHub Actions가 기본 제공하는 `GITHUB_TOKEN`을 사용합니다.

선택적으로 workflow의 env 값을 바꿀 수 있습니다.

- `CREATE_ISSUE`: `true`면 매번 GitHub Issue를 생성합니다.
- `MAX_REPOS`: 리포트에 표시할 repository 수입니다.

## agents-radar와의 차이

[duanyytop/agents-radar](https://github.com/duanyytop/agents-radar)는 GitHub, ArXiv, Hacker News, Hugging Face, Product Hunt, Dev.to, Lobste.rs 등을 모으는 큰 AI 생태계 레이더입니다. 웹 UI, RSS, MCP 서버, Telegram/Feishu 알림, LLM 요약, 일간/주간/월간 리포트까지 포함합니다.

이 repo는 그보다 작게 유지합니다.

- 필수 API secret 없음
- Python 스크립트 하나와 GitHub Actions workflow 하나
- GitHub 모바일 알림으로 읽기 좋은 Issue 생성
- 한국어 학습 과제와 Codex 자동화 아이디어에 집중

## 로컬 실행

```powershell
python scripts/radar.py --max-repos 10 --output reports/latest.md
```

GitHub API rate limit을 피하려면 token을 환경 변수로 넣습니다.

```powershell
$env:GITHUB_TOKEN="ghp_..."
python scripts/radar.py --max-repos 10 --output reports/latest.md
```

## 한계

GitHub에는 공식 Trending API가 없습니다. 이 첫 버전은 GitHub Search API만 사용하므로 "정확한 실시간 급상승"이라기보다 "최근 만들어졌고 빠르게 star를 얻으며 활동이 있는 repo"를 찾는 레이더입니다. 더 정밀하게 만들려면 GH Archive, BigQuery, 또는 일별 snapshot 저장을 추가하면 됩니다.
