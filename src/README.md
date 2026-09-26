# 앱 소스

2026-09-27: [파일 계약 v1](../docs/result-format.md), 계약 검증·교사 수정 저장 모듈 `result_files.py`, 검증 화면 `result-review.html`을 구현했습니다. 설치형 앱·파일 선택 화면·OCR 실행 연결은 아직 없습니다.

검증 화면은 사유 목록이나 채점 규칙을 갖지 않습니다. 엔진이 만든 결과의 문구와 이미지 이름표를 그대로 표시하며, 교사가 지정한 답과 판정을 별도 파일에 저장합니다.

저장소 루트에서 실행합니다. Python 표준 라이브러리만 사용하는 화면입니다.

```powershell
Copy-Item -Recurse tests/fixtures/result-demo private/my-result-demo
python -S -m tools.serve_result_review private/my-result-demo/result.json --port 8140
```

표시된 로컬 주소를 브라우저에서 엽니다. 위 복사는 처음 한 번만 실행합니다. 실제 결과는 다음과 같이 내보냅니다. 같은 제출을 다시 내보낼 때 제출 ID와 문항 ID를 유지합니다.

```text
python -m tools.export_result <comparison.json> <classification.json> <출력폴더> --assessment-id <제출ID> --rules-version <규칙버전>
python -m unittest discover -s tests
```

결과 파일은 엔진, `teacher-corrections.json`은 화면이 각각 소유합니다. 재채점 시 수정 파일을 복사하거나 초기화하지 않습니다. 서로 다른 실험 안은 별도 출력 폴더로 보존합니다.
