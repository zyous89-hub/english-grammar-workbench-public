# 결정0035 — EGW4 문항 context 직접 측정

- 기록일: 2026-09-28.
- 상태: 개발용 134문항에서 기준 재현 및 추천 평가 완료.
- 근거: EGW4 검증 기록 (비공개 기록).
- 대체: 결정0034의 PDF 좌표·추가 잉크 측정. 채점 이후 근거만 추가하는 경계는 유지.

`tools/choice_mark_recommendations.py`는 기존 결과의 `evidence_images[id=context]`에 연결된 정렬된 300dpi 문항 이미지를 그대로 읽습니다. 각 인쇄 번호를 사용자 제공 40×40 중앙값 템플릿의 32×32 중심으로 직접 찾습니다. 재정렬·크기 변경·PDF 글자 위치는 사용하지 않습니다.

| 항목 | 모든 문항에 고정한 조건 |
|---|---|
| 검출 | TM_CCOEFF_NORMED 점수 ≥0.72, 점수/번호/x/y 튜플 내림차순, x·y 모두 18px 이내 후보 억제 |
| 잉크 | 밝기 <150 |
| 번호 주변 | 검출된 32px 중심 둘레 4px 창에서 40×40 템플릿 글자(<150)를 5×5로 한 번 확장해 제외 |
| 왼쪽 띠 | 40px 창 왼쪽 12px, 중심 번호 위부터 아래로 40px(번호 높이+8px)의 원본 잉크를 더함 |
| 표시 | 위 두 잉크량의 합 ≥40. 동그라미도 형태 제한 없이 포함 |
| 취소 | 중심 번호 y+8:y+24, x+36부터 오른쪽 480px 내에서 잉크가 있는 열이 끊김 없이 ≥200px |
| 추천 | ①~⑤ 각각 정확히 한 번 검출, 취소 아닌 표시 정확히 하나, 기존 보류, 답지 단일 정답 |
| 보고서 | 확인 전사 일치/전체 추천 ≥90%일 때만 추천 목록·이름표·이미지 표시 |

경계 창이 문항 이미지를 벗어나면 해당 번호를 제외합니다. 다섯 번호가 완전히 검출되지 않으면 추천하지 않습니다. 문항별 문턱값 조정이나 답지 숫자를 이용한 선택은 없습니다. 전사는 추천 생성 입력이 아닙니다.

추천은 `evidence_images`의 `choice-mark-recommendation` 이미지·이름표와 별도 `recommendations.json`에만 추가합니다. 원래 결과의 읽은 답·확정·채점·사유·기존 근거는 유지하며 새 결과 ID와 생성 시각만 부여합니다. 모든 출력 폴더는 새 폴더여야 합니다. 기존 입력을 덮어쓰지 않고 교사 수정 파일을 복사 보존합니다.

## 로컬 실행

`templates` 폴더에는 첨부 `mark_ref.py`의 TMPL을 PNG로 그대로 풀어 놓은 `1.png`~`5.png`가 필요합니다. 스캔에서 만든 이미지이므로 저장소에 포함하지 않습니다. 현재 로컬 위치는 `private/EGW4-markref/templates/`이며, 기준 스크립트도 같은 상위 폴더에 보존했습니다. 측정 파일에 템플릿과 입력의 SHA-256을 기록합니다. 새 환경에서는 사용자 제공 로컬 자산이 필요합니다.

아래 출력 경로는 예시이며 기존 실행 폴더를 다시 쓰지 않습니다.

```powershell
private/paddle-env/Scripts/python.exe -m tools.choice_mark_recommendations inspect private/page-first147/result/duplicate/result.json private/EGW4-markref/templates private/EGW4-new-measurements
private/paddle-env/Scripts/python.exe -m tools.choice_mark_recommendations attach private/e167/result/CE/duplicate/result.json private/EGW4-new-measurements/measurements.json private/EGW4-new-result/duplicate
private/paddle-env/Scripts/python.exe -m tools.choice_mark_recommendations attach private/e167/result/CE/broad/result.json private/EGW4-new-measurements/measurements.json private/EGW4-new-result/broad
private/paddle-env/Scripts/python.exe -m tools.report_choice_recommendations private/EGW4-new-result private/manual-transcription097/transcription.json private/EGW4-new-result/EGW4-report.html
```

추천 제안안39/전사일치36/불일치3, 사용자안38/36/2. 자동확정31/33 및 오류0은 그대로입니다. 이 결과는 같은 개발 표본 재평가이며 독립 자료에서의 추천 성능이나 자동확정 안전성을 뜻하지 않습니다. 기본 제안안 표시는 별도 선행 커밋 c5fe315를 유지합니다.
