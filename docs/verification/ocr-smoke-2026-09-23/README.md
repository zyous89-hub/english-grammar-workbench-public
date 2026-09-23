# 최초 OCR 실행 시험 — 합성 인쇄체 JPG

2026-09-23. 실제 학생 숙제·손글씨 자료가 아닌 기본 동작 시험입니다. 프로젝트와 상위 작업 폴더에서 JPG/PNG/PDF 표본을 검색했으나 찾지 못했습니다. 실제 자료는 추후 제공 예정입니다.

## 입력과 실행

- 직접 작성한 문장 8개를 Windows Arial 42px, 1400×760, JPEG 품질 90, 300dpi로 렌더링했습니다. 문법·철자 오류를 의도적으로 포함한 합성 자료입니다.
- 이미지 [synthetic-printed-answers.jpg](synthetic-printed-answers.jpg)를 실제로 열어 8문장·잘림 없음·문구를 확인했습니다. 폰트 파일은 배포하지 않았습니다.
- 이미 설치된 Tesseract 5.4.0.20240606, eng 모델, PSM 6으로 실행했습니다. 설치·추가 학습·사전 조정은 하지 않았습니다.
- 실행: 프로젝트 루트에서 `python scripts/ocr_smoke_test.py`. Pillow, Tesseract, Windows Arial이 필요합니다.
- 원문 [expected.txt](expected.txt), 가공 전 인식 [recognized.txt](recognized.txt), 환경·실행 명령·시각·해시 [result.json](result.json), 표준 오류 [stderr.txt](stderr.txt)를 저장했습니다.
- result.json의 source_commit은 실행 직전 기반 커밋입니다. 당시 새 스크립트는 미커밋 상태였으며 script_sha256으로 실행한 내용을 식별합니다. 이 기록과 스크립트를 같은 후속 커밋으로 저장합니다.

## 실제 결과

8줄 검출, 6줄 완전 일치, 2줄 불일치, 추가 줄 0개. 비교는 빈 줄과 줄 양끝 공백만 제외했고 철자·문장부호를 보정하지 않았습니다.

| 입력 | 출력 | 결과 |
|---|---|---|
| He gose home. | He gose home. | 일치 |
| She walk to school. | She walk to school. | 일치 |
| They walks to school. | They walks to school. | 일치 |
| He has finished his homework. | He has finished his homework. | 일치 |
| He had finished his homework. | He had finished his homework. | 일치 |
| The boy playing soccer is my brother. | The boy playing soccer is my brother. | 일치 |
| I am interesting in music. | &#124; am interesting in music. | 대문자 I를 세로줄로 오인 |
| I am interested in music. | &#124; am interested in music. | 같은 오인 |

OCR 프로세스 실행 시간(시작 비용 포함)은 0.217254초입니다. 단일 합성 이미지 1회 측정이며 이미지 생성·교사 검토·채점·보고서 시간은 포함하지 않습니다. 실제 숙제 한 세트 시간이나 평균 처리 속도가 아닙니다.

## 해석과 한계

이 표본에서는 잘못된 철자 gose와 문법을 정상 문장으로 자동 교정하지 않았습니다. 그러나 선명한 인쇄체에서도 I/세로줄 혼동이 발생했습니다. 이 결과를 전체 정확도·손글씨 정확도·자동 채점 정확도로 일반화할 수 없습니다. 이번 오류를 숨기거나 자동 치환하지 않았으며 설정 변경·재시험은 하지 않았습니다.

로컬 실행 파일과 모델을 사용했습니다. 외부 OCR 서비스를 호출하는 코드는 없지만 네트워크 차단·송신 감시는 수행하지 않아 무통신 검증 완료라고 주장하지 않습니다. 실제 손글씨, 취소선·화살표, 문제지/답지 연결, M1/M2, 독립 실행 앱 패키징은 아직 미검증입니다. 실제 표본을 받으면 동일한 원문 전사 대조 방식으로 다음 시험을 합니다.
