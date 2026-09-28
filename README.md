이 저장소는 2026-09-28 해커톤 제출 시점까지의 개발 이력을 담은 공개용 사본입니다(원본 비공개 저장소 main cb81b05). 실제 학생 답안 사례가 담긴 문서는 개인정보 보호를 위해 모든 기록에서 뺐고, 그래서 커밋 해시가 원본과 다릅니다. 원본 해시는 orig-로 시작하는 태그로 찾을 수 있습니다.

# English Grammar Workbench

## 결과와 재현

아래는 **f5fed75의 개발용 결과**입니다. 기본 정책은 제안안(`duplicate`)이며, 독립 검증 결과는 EGW3 보고 확인 후 별도로 추가합니다.

| 기준 커밋 | 정책 | 평가 범위 | 문항 수 | 자동확정 | 틀린 자동확정 | 보류 |
|---|---|---|---:|---:|---:|---:|
| f5fed75 (비공개 기록) | 제안안 · 기본값 | 개발용 고정 자료 | 134 | 37 | 0 | 97 |

‘틀린 자동확정’은 확인 전사와 다른 답을 자동확정하거나, 전사에서 숫자 답이 확정되지 않았는데 숫자로 자동확정한 건수입니다. 학생의 답지상 정답률과는 다릅니다. 추천은 자동확정에 포함하지 않습니다. 결과·검증 기록 (비공개 기록), [적용 규칙](docs/decisions/0037-EGW4-same-answer-causes.md), [기본 정책](src/README.md)을 함께 확인합니다.

저장된 OCR·선택 표시 측정을 재사용해 위 채점 결과를 만든 기존 명령입니다. 저장소 루트에서 해당 버전과 같은 로컬 자료·환경을 사용하며, 마지막 출력 경로는 아직 없는 새 폴더여야 합니다.

```powershell
private/paddle-env/Scripts/python.exe -m tools.dual_evidence private/e167/result/CE private/e167/CE-trial private/external-batch-20260925/4C-rerun071-source private/EGW4-markref/measurements/measurements.json private/EGW4-reproduce-f5fed75
```

출력의 `duplicate/result.json`이 기본 결과입니다. 이 명령은 전사를 입력받지 않으며, 오류0은 별도 확인 전사 대조 결과입니다. 기존 로컬 평가 근거는 `private/EGW4-same-answer-verified/EGW4-validation.json`과 `EGW4-final-checks.json`에 있습니다. 학생 자료·전사·템플릿·모델·실행 환경은 Git에 포함되지 않으므로 저장소 복제만으로 같은 수치를 재현할 수는 없습니다. 기존 명령의 입력 계약은 [결정0036](docs/decisions/0036-EGW4-dual-evidence-agreement.md)에 있습니다. 이번 문서 보강에서는 재채점·평가 기준 변경을 하지 않았습니다.

## 외부 통신

아래 표는 저장소에 남은 실행 기록과 구현 코드로 확인한 범위입니다. 이번 문서 보강에서 새 통신 감사를 실행한 것은 아닙니다.

| 항목 | 확인된 상태와 한계 | 근거 파일 |
|---|---|---|
| 채점 중 외부 통신 | 기록된 개발 실행은 로컬 OCR·채점이며 외부 OCR API를 사용하지 않았음. 현재 OCR 실행기는 Python 연결·DNS 호출을 차단함. 완성 앱 전체의 외부 통신 여부는 미확인 | 외부 묶음 실행 기록 (비공개 기록), [OCR 실행기](tools/run_added_ink_ocr.py) |
| OCR 모델 다운로드 | 준비 단계에서 PP-OCRv5 모델을 PaddlePaddle 공식 Hugging Face 배포본으로 다운로드한 기록이 있음. 현재 OCR 실행기는 로컬 `model_dir`를 지정하고 오프라인 환경값을 설정함. 완성 배포물의 첫 실행·캐시 누락 시 동작은 미확인 | [PaddleOCR 준비·실행 기록](docs/verification/2026-09-24-paddle-ocr.md), [OCR 실행기](tools/run_added_ink_ocr.py) |
| 계정·API 키 | 현재 로컬 OCR 실행기의 입력은 경로이며 계정·API 키 인수가 없음. 검증 화면은 Python 표준 라이브러리로 동작함. 모델 준비를 포함한 완성 앱 설치·배포 전체의 요구사항은 미확인 | [OCR 실행기](tools/run_added_ink_ocr.py), [검증 화면 범위](src/README.md) |
| 사용 통계 | 외부 사용 통계 수집·전송 여부 미확인. 의존 라이브러리와 완성 배포물까지 포함한 전용 감사 기록 없음 | [현재 구현 범위](src/README.md); 사용 통계 전용 검증 근거 없음 |
| 실행 중 연결 시도 감사 | 2026-09-24 로컬 모델 추론에서 Python `socket.connect`·DNS 감사 훅이 감지한 연결 시도0회. 해당 실행의 측정이며 OS·네이티브 라이브러리 전체 감사는 아님 | [Python socket·DNS 감사 기록](docs/verification/2026-09-24-paddle-ocr.md), [서술형 묶음 감사 범위](docs/verification/2026-09-24-written-batch.md) |

**OS 전체 무통신과 완성 앱 패키징 검증은 아직 완료하지 않았습니다.** 설치형 앱·OCR 실행 연결의 미완료 범위는 [src/README.md](src/README.md), 배포 환경·DLL·모델 포함 검증의 남은 범위는 독립 실행 가능성 검토 (비공개 기록)에 기록돼 있습니다.

외부 구성요소 고지는 [NOTICE](NOTICE), 오류와 방지 규칙은 개발 교훈 (비공개 기록)을 참조합니다. 문서 구성은 kordoc의 [작업 규칙](https://github.com/chrisryugj/kordoc/blob/main/AGENTS.md), [통신 범위 표](https://github.com/chrisryugj/kordoc/blob/main/SECURITY.md#outbound-network-traffic), [성능 표](https://github.com/chrisryugj/kordoc#-성능-한눈에-보기)를 참고했으며, 위 수치와 통신 설명은 이 저장소의 근거만 사용했습니다.

## 이전 상태 기록

아래 날짜별 설명은 당시 기록입니다. 현재 개발용 결과와 검증 범위는 위 두 절을 우선합니다.

현재 개발 경계(2026-09-27): [앱·엔진 파일 계약 v1](docs/result-format.md), [검증 화면 실행법](src/README.md). 교사 수정은 별도 파일로 보존합니다. 계약·출력·검증 화면까지 구현했으며 설치형 앱은 아직 없습니다. 최신 채점은 [132](docs/conversations/2026-09-27-132.md), 현재 상태는 인수인계 (비공개 기록)를 우선합니다. 아래 최근 실험 표시는 당시 기록입니다.

최근 실험: F08(b) 동그라미 예외 두 조건 비교121 (비공개 기록). 기존 OCR 66문항으로 두 안 모두 전사 일치 5 / 보류 61. 기본 규칙 채택은 미결정입니다.

최신 규칙: [F08(a) 취소, F08(b) 유지](docs/decisions/0016-disable-f08a.md). [전반부 9쪽 시뮬레이션](docs/conversations/2026-09-26-119.md)은 알파벳 보존 적용 후 자동 전사 일치 3 / 보류 63입니다. 아래 118의 전부 보류 결과는 이전 규칙의 기록입니다.

최근 확인: [목록 117 기준 101 묶음 재분류](docs/conversations/2026-09-26-118.md). F08(a)가 기존 자동 확정 209건을 모두 보류시켜 정인식 155건도 자동 처리에서 빠졌습니다. 규칙의 적용 범위 재검토가 필요하며, 운영 채점기·전체 134문항 검증 완료를 뜻하지 않습니다.

**현재 범위(2026-09-26): M1 객관식 채점·기록까지. M2 어법 구분·기록은 이번 범위에서 제외합니다.** [결정 0013](docs/decisions/0013-m1-only-scope.md), 당시 규칙·작업 스냅샷 HTML 117 — F08(a)는 후속 취소 (비공개 기록). 아래 초기 M1/M2 설명과 미실시 표시는 당시 기록입니다. 개발 도구는 시험 중이며 앱 본체는 아직 미구현입니다.

## 학생 숙제 채점·오답 어법 기록 프로그램

최근 시험(2026-09-24): [서술형 전체 묶음 OCR·답지 대조 및 한계](docs/verification/2026-09-24-written-batch.md). 새570문항 시험을 마쳤지만 전체 자동 채점은 미달이며 앱 본체는 아직 없습니다.

**현재 상태 (2026-09-23): M1 채점·기록, M2 오답 어법 구분·추가 기록을 목표로 확정했습니다. 비공개 GitHub 연결과 기존 스킬 확인을 마쳤으며 앱·성능 시험은 미구현/미실시입니다.**

- [현재 제품 목표: 입력 폴더·한 세트·M1·M2](docs/product-goals.md)
- [앱 제작 청사진: 필기 경계 추적·채점 흐름·미검증 항목](docs/app-blueprint.md)
- [원본 기반 유형 판별 로컬 AI: PC 확인·남은 일정 가능성](docs/local-classifier-feasibility.md)
- [유형 판단: 외부 LLM·Jev·로컬 구현 비용/데이터 비교](docs/type-classifier-options.md)
- [JPG·PDF 유지, OCR 가능성, Google Docs·로컬 저장 비교](docs/input-ocr-storage-review.md)
- [추후 편집을 위한 로컬 HTML 보고서 방향](docs/decisions/0008-editable-local-html.md)
- [OCR 오류와 채점 영향 — 논의 초안](docs/ocr-error-discussion.md)
- [원본 추가 후 객관식·서술형 영역 추출 시험](docs/verification/2026-09-24-mixed-reference-ocr.md)
- [새 객관식·서술형 표본 OCR 시험](docs/verification/2026-09-24-mixed-page-ocr.md)
- 필기 경계 복원·독립 실행 10회·문자 선택 근거 (비공개 기록)
- [윗줄 인쇄 글자 제외 재시험·밑줄 문자 진단](docs/verification/2026-09-24-textline-ocr.md)
- [두 번째 실제 페이지: 18문항·83칸 OCR 시험](docs/verification/2026-09-24-second-page-ocr.md)
- [밑줄 전체 범위 시험: 첫 획 누락 개선, 번호 혼입 확인](docs/verification/2026-09-24-underline-ocr.md)
- [원본 기준 변경 영역 인식: 원래 조각 9/13개 일치](docs/verification/2026-09-24-reference-difference-ocr.md)
- [PaddleOCR 재시험: 일부 개선, 채점은 중단](docs/verification/2026-09-24-paddle-ocr.md)
- [실제 학생 자료 OCR 비교: 추출 실패로 채점 중단](docs/verification/2026-09-24-real-ocr.md)
- [실사용 문제 1: 문제만 읽고 학생 답을 놓칠 위험](docs/student-answer-detection-risk.md)
- [첫 OCR 실제 실행 결과: 합성 인쇄체 8줄 중 6줄 일치](docs/verification/ocr-smoke-2026-09-23/README.md)
- [9월 28일 오전 마감·3일 개발 가능 범위](docs/deadline-and-delivery-plan.md)
- [숙제 채점용 맞춤 OCR 가능성 검토](docs/custom-ocr-feasibility.md)
- [현재 대화 원문·시각 포함 보완본](docs/conversations/2026-09-23-timestamped-session.md)

- 비공개 GitHub 저장소 (비공개 기록)
- [기존 스킬 확보 상태·기능 이식표·첫 구현 제안](docs/skill-mapping.md)
- [실제 Git·인증·원격 검증 기록](docs/verification/2026-09-23-repository.md)
- [이번 대화와 범위 조정](docs/conversations/2026-09-23-003.md)
- [구현 보류 결정](docs/decisions/0004-source-audit-before-implementation.md)
- [대화 → 실행 절차 실제 예시와 버전별 보기](docs/workflow-example.md)
- [사용자 지정 버전 규칙: 큰 변화 a / 자잘한 변화 b / 리뷰 수정 c](docs/decisions/0005-version-numbering.md)

학생 숙제 스캔 폴더와 해당 숙제의 답지 폴더를 받아, 외부 프로그램 없이 채점하고 기록하는 것이 M1입니다. 학생이 틀린 어법을 구분해 추가 기록하는 것이 M2입니다. 한 세트는 학생 한 명의 1회분 숙제이며 수동 채점 시간은 사용자가 나중에 제공할 예정입니다. 기존의 실행 중 AI 없음 요구도 유지합니다. 인식 방법·기록 형식·세부 지원 범위는 아직 정하지 않았습니다.

이 패키지는 ChatGPT 작업 환경에서 만든 **로컬 Git 저장소**에서 시작했습니다. 초기 이력 2개를 유지해 사용자 PC에서 지정 계정의 비공개 원격을 만들고 업로드했습니다. 인증정보는 저장소에 포함하지 않습니다.

### Codex에서 이어서 시작하기

이 폴더를 Codex의 로컬 프로젝트로 열고 [시작 지시문](CODEX_START_PROMPT.md)을 첫 메시지로 전달합니다. 인수인계 문서 (비공개 기록)에 프로젝트 조건, 기존 스킬 확인, GitHub 연결, 첫 작업과 검증 범위를 정리했습니다. README 한 파일만 전달하는 대신 이 저장소 전체를 사용합니다.

초기 인수인계 당시의 미실시 기록은 역사적 기록으로 보존합니다. 현재 확인 상태는 위 검증 기록을 따릅니다. 다른 환경에서 이어갈 때는 실제 인증·원격 상태를 다시 확인해야 합니다.

### 바로 읽을 문서

- [요구사항: 확인된 조건과 설계 제안](docs/requirements.md)
- [기록 시작 이전 맥락 — 요약이며 원문이 아닙니다](docs/context-before-log.md)
- [기록 시작 요청의 대화](docs/conversations/2026-09-23-001.md)
- [Codex 전환 요청의 대화](docs/conversations/2026-09-23-002.md)
- [설계 결정 기록](docs/decisions/README.md)
- [검증 계획 — 아직 결과 없음](docs/evaluation-plan.md)
- 대화·결정·코드·시험 연결표 (비공개 기록)
- [포트폴리오 구성 계획](docs/portfolio-plan.md)
- [GitHub에 게시하는 절차](docs/github-setup.md)
- [미완료 작업 목록](docs/backlog.md)

### 목표 처리 흐름 — 미구현

폴더1(학생 숙제 스캔) + 폴더2(해당 숙제 답지) → M1: 채점·기록 → M2: 틀린 어법 구분·추가 기록

### 이번 초기 상태

| 항목 | 상태 |
|---|---|
| 프로젝트 범위·기록 원칙 문서 | 작성됨 |
| 대화 기록 | 001~012 및 현재 대화 시각 포함 보완본; 각 파일에 실제 수록 범위 표시 |
| 기존 스킬 원문·실제 답지 | 로컬 관련 스킬 2개 확인; 원본은 미복제, 실제 답지는 없음 |
| 정확한 기존 어법 분류표·HTML 양식 | 시작용 어법 13개·유형 9개와 배치 규격·참고 이미지 확인; 최종 체계·완성 HTML 미확인 |
| 분류 엔진·앱·실행 파일 | 미구현 |
| 분류 성능·업무 시간 실험 | 미실시 |
| GitHub 생성·업로드 | 비공개 생성·초기 커밋 업로드 및 로컬/원격 일치 확인 |

### 운영 원칙

대화는 사용자/assistant 발화와 요약을 구분하고, AI 제안은 사용자 결정으로 둔갑시키지 않습니다. 실패와 정정 기록도 남깁니다. 대화 로그는 작업 기록이지, 독립적인 실력 인증이나 대회 평가 점수를 의미하지 않습니다.

대화 전체 자동 동기화 기능은 없습니다. 기록 파일 작성, 로컬 커밋, 원격 업로드, 원격 확인은 서로 다른 단계입니다. 완료한 단계만 보고합니다.

공개 전 개인정보·비밀값·재배포 범위를 확인합니다. 초기 원격 저장소의 권장 가시성은 비공개입니다. 공개 전환은 별도 승인 사항입니다. 공개 라이선스는 아직 선택하지 않았습니다.

- [소형 로컬 유형 판별 모델 비교](docs/local-model-shortlist.md): 후보별 장단점과 시험안, 실행 성능 미측정.
- 외부 폴더 순차 OCR 채점·검토 (비공개 기록): 2026-09-25 별도 요청의 처리 범위·검증·한계. 상세 학생 보고서는 로컬에만 보관합니다.
