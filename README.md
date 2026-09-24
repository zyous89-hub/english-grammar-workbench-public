# English Grammar Workbench
## 학생 숙제 채점·오답 어법 기록 프로그램

**현재 상태 (2026-09-23): M1 채점·기록, M2 오답 어법 구분·추가 기록을 목표로 확정했습니다. 비공개 GitHub 연결과 기존 스킬 확인을 마쳤으며 앱·성능 시험은 미구현/미실시입니다.**

- [현재 제품 목표: 입력 폴더·한 세트·M1·M2](docs/product-goals.md)
- [앱 제작 청사진: 필기 경계 추적·채점 흐름·미검증 항목](docs/app-blueprint.md)
- [유형 판단: 외부 LLM·Jev·로컬 구현 비용/데이터 비교](docs/type-classifier-options.md)
- [JPG·PDF 유지, OCR 가능성, Google Docs·로컬 저장 비교](docs/input-ocr-storage-review.md)
- [추후 편집을 위한 로컬 HTML 보고서 방향](docs/decisions/0008-editable-local-html.md)
- [OCR 오류와 채점 영향 — 논의 초안](docs/ocr-error-discussion.md)
- [원본 추가 후 객관식·서술형 영역 추출 시험](docs/verification/2026-09-24-mixed-reference-ocr.md)
- [새 객관식·서술형 표본 OCR 시험](docs/verification/2026-09-24-mixed-page-ocr.md)
- [필기 경계 복원·독립 실행 10회·문자 선택 근거](docs/verification/2026-09-24-adaptive-repeat-ocr.md)
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

- [비공개 GitHub 저장소]((비공개 기록))
- [기존 스킬 확보 상태·기능 이식표·첫 구현 제안](docs/skill-mapping.md)
- [실제 Git·인증·원격 검증 기록](docs/verification/2026-09-23-repository.md)
- [이번 대화와 범위 조정](docs/conversations/2026-09-23-003.md)
- [구현 보류 결정](docs/decisions/0004-source-audit-before-implementation.md)
- [대화 → 실행 절차 실제 예시와 버전별 보기](docs/workflow-example.md)
- [사용자 지정 버전 규칙: 큰 변화 a / 자잘한 변화 b / 리뷰 수정 c](docs/decisions/0005-version-numbering.md)

학생 숙제 스캔 폴더와 해당 숙제의 답지 폴더를 받아, 외부 프로그램 없이 채점하고 기록하는 것이 M1입니다. 학생이 틀린 어법을 구분해 추가 기록하는 것이 M2입니다. 한 세트는 학생 한 명의 1회분 숙제이며 수동 채점 시간은 사용자가 나중에 제공할 예정입니다. 기존의 실행 중 AI 없음 요구도 유지합니다. 인식 방법·기록 형식·세부 지원 범위는 아직 정하지 않았습니다.

이 패키지는 ChatGPT 작업 환경에서 만든 **로컬 Git 저장소**에서 시작했습니다. 초기 이력 2개를 유지해 사용자 PC에서 지정 계정의 비공개 원격을 만들고 업로드했습니다. 인증정보는 저장소에 포함하지 않습니다.

### Codex에서 이어서 시작하기

이 폴더를 Codex의 로컬 프로젝트로 열고 [시작 지시문](CODEX_START_PROMPT.md)을 첫 메시지로 전달합니다. [인수인계 문서](CODEX_HANDOFF.md)에 프로젝트 조건, 기존 스킬 확인, GitHub 연결, 첫 작업과 검증 범위를 정리했습니다. README 한 파일만 전달하는 대신 이 저장소 전체를 사용합니다.

초기 인수인계 당시의 미실시 기록은 역사적 기록으로 보존합니다. 현재 확인 상태는 위 검증 기록을 따릅니다. 다른 환경에서 이어갈 때는 실제 인증·원격 상태를 다시 확인해야 합니다.

### 바로 읽을 문서

- [요구사항: 확인된 조건과 설계 제안](docs/requirements.md)
- [기록 시작 이전 맥락 — 요약이며 원문이 아닙니다](docs/context-before-log.md)
- [기록 시작 요청의 대화](docs/conversations/2026-09-23-001.md)
- [Codex 전환 요청의 대화](docs/conversations/2026-09-23-002.md)
- [설계 결정 기록](docs/decisions/README.md)
- [검증 계획 — 아직 결과 없음](docs/evaluation-plan.md)
- [대화·결정·코드·시험 연결표](docs/evidence-index.md)
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
