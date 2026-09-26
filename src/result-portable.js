// File transfer only; the shared screen still owns rendering. No OCR or reason lookup.
window.reviewTransport = (() => {
  const result = portableData.result;
  let corrections = portableData.corrections, revision = 0;
  const own = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);
  const object = v => v !== null && typeof v === 'object' && !Array.isArray(v);
  const nonempty = v => typeof v === 'string' && !!v.trim();
  function validate(data) {
    if (!object(data) || data.schema_version !== 1 || data.assessment_id !== result.assessment_id || !object(data.corrections))
      throw Error('이 제출의 교사 수정 파일이 아닙니다. 기존 수정은 유지했습니다.');
    for (const [id, c] of Object.entries(data.corrections)) {
      if (!nonempty(id) || !object(c) || !(c.read_answer === null || typeof c.read_answer === 'string') ||
          !['정답', '오답', '보류'].includes(c.judgement) || typeof c.note !== 'string' ||
          !nonempty(c.based_on_result_id) || !nonempty(c.based_on_rules_version) ||
          typeof c.updated_at !== 'string' || !/(Z|[+-]\d{2}:\d{2})$/.test(c.updated_at) || !Number.isFinite(Date.parse(c.updated_at)))
        throw Error('교사 수정 파일의 형식이 잘못됐습니다. 기존 수정은 유지했습니다.');
    }
    return data;
  }
  function load() {
    const rows = result.questions.map(q => {
      const teacher = own(corrections.corrections, q.id) ? corrections.corrections[q.id] : null;
      const value = teacher || q;
      return {automatic:q, teacher, effective:{read_answer:value.read_answer, judgement:value.judgement},
        differs:!!teacher && (teacher.read_answer !== q.read_answer || teacher.judgement !== q.judgement)};
    });
    const ids = new Set(result.questions.map(q => q.id));
    return {result, corrections, revision, rows, orphaned:Object.keys(corrections.corrections).filter(id => !ids.has(id))};
  }
  async function save(data) {
    if (data.revision !== revision || data.result_id !== result.result_id) throw Error('다시 불러온 뒤 저장하세요.');
    const q = result.questions.find(q => q.id === data.question_id);
    if (!q) throw Error('현재 결과에 해당 문항이 없습니다.');
    const updated = {...corrections, corrections:{...corrections.corrections, [q.id]:{
      ...(own(corrections.corrections, q.id) ? corrections.corrections[q.id] : {}),
      read_answer:typeof data.read_answer === 'string' ? data.read_answer.trim() : data.read_answer,
      judgement:data.judgement, note:data.note, updated_at:new Date().toISOString(),
      based_on_result_id:result.result_id, based_on_rules_version:q.rules_version
    }}};
    validate(updated);
    const url = URL.createObjectURL(new Blob([JSON.stringify(updated, null, 2)], {type:'application/json'}));
    const link = document.createElement('a'); link.href = url; link.download = 'teacher-corrections.json';
    document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 10000);
    corrections = updated; revision++;
    return load();
  }
  document.getElementById('import-corrections').onclick = () => {
    if (!mayLeave()) return;
    const input = document.getElementById('correction-file'); input.value = ''; input.click();
  };
  document.getElementById('correction-file').onchange = async event => {
    const file = event.target.files[0]; if (!file) return;
    try {
      if (file.size > 16 * 1024 * 1024) throw Error('수정 파일이 너무 큽니다.');
      const incoming = validate(JSON.parse(await file.text()));
      if (!confirm('현재 화면의 교사 수정 목록을 선택한 JSON의 수정 목록으로 바꿀까요?')) return;
      corrections = incoming; revision++; dirty = false;
      await reload(); notice('교사 수정 JSON을 불러왔습니다. 원본 HTML은 바뀌지 않습니다.');
    } catch (error) { notice(error.message, true); }
  };
  return {load, save, image:e => portableData.images[e.path],
    saveNotice:'수정 JSON 다운로드를 요청했습니다. 다운로드된 파일을 보관하세요.'};
})();
