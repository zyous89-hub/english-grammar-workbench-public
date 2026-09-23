# GitHub 게시 절차

## 현재 상태

2026-09-23 사용자 PC에서 지정 비공개 원격을 생성하고 초기 커밋을 업로드했습니다. [실행·검증 기록](verification/2026-09-23-repository.md)을 따릅니다. 아래 내용은 초기 패키지의 준비 절차이며 생성 명령을 다시 실행하지 않습니다.

현재 패키지에는 로컬 `.git/`과 초기 커밋이 포함됩니다. 원격 저장소는 없으며 인증정보도 없습니다. 이 문서는 실행 방법이고, 아래 명령이 이미 실행됐다는 뜻은 아닙니다.

권장 저장소 이름: `english-grammar-workbench`.
확인된 연결 계정: `zyous89-hub`.
기본 권장 설정: 비공개. 같은 이름이 이미 있다면 덮어쓰거나 강제로 푸시하지 말고 기존 저장소인지 먼저 확인합니다.

## 준비

Git과 GitHub CLI(`gh`)가 설치된 사용자 PC에서 진행합니다. CLI의 로그인은 ChatGPT 연결과 별개입니다. 비밀번호·토큰을 채팅에 붙여넣지 않습니다. 다음은 압축을 푼 프로젝트 폴더의 터미널에서 실행합니다.

```powershell
git status
git log -1 --oneline
git remote -v
gh auth status
```

로그인이 필요한 경우에만 다음을 실행하고 본인이 브라우저에서 인증합니다.

```powershell
gh auth login --hostname github.com --git-protocol https --web
```

## 생성과 첫 업로드

파일과 이력을 확인한 뒤, 계정이 `zyous89-hub`이며 같은 이름의 저장소를 새로 만들려는 것이 맞을 때 실행합니다.

```powershell
gh repo create zyous89-hub/english-grammar-workbench --private --source . --remote origin --push
```

위 명령은 GitHub에 비공개 저장소를 만들고 현재 로컬 커밋을 업로드합니다. 읽기 전용 명령이 아닙니다. 오류가 나면 자동으로 덮어쓰기·공개 전환·강제 푸시하지 않습니다.

## 완료 확인

```powershell
gh repo view zyous89-hub/english-grammar-workbench --json nameWithOwner,isPrivate,url
git rev-parse HEAD
git ls-remote origin refs/heads/main
```

로컬 HEAD와 원격 main의 해시를 비교합니다. 원격 조회 결과를 확인한 뒤에만 GitHub 저장 완료라고 기록합니다.

## 이후 작업

초기 커밋의 작성자는 자동 생성 사실을 드러내는 `AI-assisted scaffold`이며 사용자 기여인 척하지 않습니다. 다음 커밋부터 사용할 본인 Git 작성자 설정은 실제 값으로 설정합니다. 과거 커밋을 사용자 작성으로 위장하거나 날짜를 소급하지 않습니다.

변경 파일을 확인하고 필요한 경로만 스테이징합니다. `git diff --cached`를 검토하고 의미 있는 변경 단위로 커밋합니다. 대화 기록은 대화 파일로, 기능과 시험 변경은 해당 파일로 남깁니다. GitHub 업로드는 네트워크·권한이 확보될 때 수행하고 성공 여부를 별도 확인합니다.

## Codex에서 이어서 작업하는 경우

이 폴더를 작업 대상으로 열고 AGENTS.md와 docs/backlog.md를 읽도록 요청합니다. 계정 로그인·권한을 확인한 뒤 위 생성/업로드를 수행하게 할 수 있습니다. 특정 Codex 환경에서 Git/gh 또는 저장 권한이 있다는 것은 여기서 확인하지 않았습니다.

## 공식 참고

- https://cli.github.com/manual/gh_repo_create
- https://cli.github.com/manual/gh_auth_login
- https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository
