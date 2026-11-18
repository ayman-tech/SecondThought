// Applied instructions are independent of draft edits in the collapsed editor.
export function mountPromptControls(onChange) {
  const $ = id => document.getElementById(id);
  const presets = JSON.parse($('task-presets').textContent);
  const limits = JSON.parse($('prompt-limits').textContent);
  let applied = {task:'rewrite', system_prompt:presets.rewrite.system_prompt,
    max_input_tokens:limits.input.default, max_new_tokens:limits.output.default};
  const settings = () => ({...applied});
  function update() {
    $('experiment-prompt').value = applied.task;
    $('system-prompt').value = applied.system_prompt ?? '';
    $('system-prompt').readOnly = applied.task === 'none';
    $('input-budget').value = applied.max_input_tokens;
    $('output-budget').value = applied.max_new_tokens;
    $('apply-prompt').disabled = true;
    $('prompt-state').textContent = applied.task === 'none' ? 'No system message' : 'Applied';
    $('changes-toggle').hidden = applied.task !== 'rewrite';
    const placeholders = {rewrite:'What would you like to rephrase?', answer:'Ask a question…',
      summarize:'Paste the text to summarize…', continue:'Start a passage to continue…',
      custom:'Enter input for your instructions…', none:'Enter a task or question…'};
    $('draft').placeholder = placeholders[applied.task];
  }
  function commit(next) {
    const changed = JSON.stringify(applied) !== JSON.stringify(next);
    applied = next; update();
    if (changed) onChange();
  }
  $('experiment-prompt').addEventListener('change', () => {
    const task = $('experiment-prompt').value;
    const preset = presets[task];
    if (task === 'custom') {
      $('prompt-settings').open = true;
      $('system-prompt').readOnly = false;
      $('output-budget').value = preset.output_tokens;
      $('apply-prompt').disabled = false;
      $('prompt-state').textContent = 'Unapplied edits';
      $('system-prompt').focus();
      return;
    }
    commit({...applied, task, system_prompt:preset.system_prompt, max_new_tokens:preset.output_tokens});
  });
  for (const id of ['system-prompt','input-budget','output-budget'])
    $(id).addEventListener('input', () => {
      $('system-prompt').setCustomValidity('');
      $('apply-prompt').disabled = false;
      $('prompt-state').textContent = 'Unapplied edits';
    });
  $('apply-prompt').addEventListener('click', () => {
    if (!$('input-budget').reportValidity() || !$('output-budget').reportValidity()) return;
    const editingTask = $('experiment-prompt').value;
    const prompt = editingTask === 'none' ? null : $('system-prompt').value;
    if (prompt !== null && !prompt.trim()) {
      $('system-prompt').setCustomValidity('Enter instructions or select No system instruction.');
      $('system-prompt').reportValidity(); return;
    }
    if (!$('system-prompt').reportValidity()) return;
    commit({...applied, task:editingTask === 'custom' || prompt !== applied.system_prompt ? 'custom' : applied.task,
      system_prompt:prompt, max_input_tokens:Number($('input-budget').value),
      max_new_tokens:Number($('output-budget').value)});
  });
  update();
  return {settings};
}
