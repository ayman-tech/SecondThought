import { FeatureExperiment } from './feature-state.js';

const colours=['#7954df','#208c89','#ce7c3b','#c75b97','#4c83c2'];
export function mountFeatureLayers(onChange,onCommit=()=>{}) {
  const $=id=>document.getElementById(id);
  const experiment=new FeatureExperiment(JSON.parse($('layer-vector-data').textContent));
  const buttons=[...document.querySelectorAll('[data-layer]')];
  const signed=n=>`${n>=0?'+':'−'}${Math.abs(n).toFixed(1)}`;
  const colour=id=>colours[experiment.features.findIndex(f=>f.id===id)%colours.length];
  const angleAt=i=>experiment.features.length===2 ? (i===0?-Math.PI/2:0) : -Math.PI/2+2*Math.PI*i/experiment.features.length;
  const checks=new Map(), sliders=new Map();
  const ns='http://www.w3.org/2000/svg';
  const svg=(tag,attributes)=>{
    const node=document.createElementNS(ns,tag);
    for (const [key,value] of Object.entries(attributes)) node.setAttribute(key,value);
    return node;
  };
  function change(action) {
    const before=JSON.stringify(experiment.interventions());
    action();render();
    if (before!==JSON.stringify(experiment.interventions())) onChange();
  }
  for (const [position,feature] of experiment.features.entries()) {
    const label=document.createElement('label');label.className='feature-check';
    const check=document.createElement('input');check.type='checkbox';
    check.dataset.feature=feature.id;check.id=`feature-${feature.id}`;
    const text=document.createElement('span');text.textContent=feature.label;
    text.style.setProperty('--feature-colour',colour(feature.id));
    label.append(check,text);$('feature-selection').append(label);checks.set(feature.id,check);
    check.addEventListener('change',()=>change(()=>experiment.enableFeature(feature.id,check.checked)));
    const option=document.createElement('option');option.value=feature.id;option.textContent=feature.label;
    $('focused-feature').append(option);

    const row=document.createElement('div');row.className='mix-control';row.style.setProperty('--feature-colour',colour(feature.id));
    const heading=document.createElement('div');heading.className='mix-heading';
    const edit=document.createElement('button');edit.type='button';edit.className='mix-edit';edit.textContent=feature.label;
    edit.addEventListener('click',()=>change(()=>experiment.selectFeature(feature.id)));
    const target=document.createElement('span');target.className='mix-target';
    const output=document.createElement('output');
    const status=document.createElement('button');status.type='button';status.className='mix-status';
    status.id=`mix-status-${feature.id}`;
    const detail=document.createElement('div');detail.className='mix-layer-popover';detail.popover='auto';
    detail.id=`mix-layers-${feature.id}`;detail.setAttribute('aria-label',`${feature.label} layer configuration`);
    status.setAttribute('popovertarget',detail.id);
    const detailHeading=document.createElement('strong');detailHeading.textContent=feature.label;
    const list=document.createElement('div');list.className='mix-layer-list';
    const clear=document.createElement('button');clear.type='button';clear.textContent='Clear this feature';
    clear.addEventListener('click',()=>change(()=>experiment.banks.get(feature.id).selected.clear()));
    const close=document.createElement('button');close.type='button';close.textContent='Close';
    close.addEventListener('click',()=>detail.hidePopover());detail.append(detailHeading,list,clear,close);
    const slider=document.createElement('input');slider.type='range';slider.min=-2;slider.max=2;slider.step=.1;
    slider.id=`mix-${feature.id}`;slider.setAttribute('aria-label',`${feature.label} strength`);
    heading.append(edit,target,output);row.append(heading,status,slider,detail);$('mix-controls').append(row);
    slider.addEventListener('input',()=>change(()=>{
      const bank=experiment.banks.get(feature.id);bank.values[bank.focused]=Number(slider.value);
    }));
    slider.addEventListener('change',()=>{
      const bank=experiment.banks.get(feature.id);
      if (experiment.enabled.has(feature.id) && bank.selected.has(bank.focused) && bank.available.has(bank.focused)) onCommit();
    });
    sliders.set(feature.id,{slider,output,target,edit,row,status,list,clear});
  }
  function renderWheel() {
    const wheel=$('mix-wheel');const nodes=[];let x=100,y=100;
    for (const [i,feature] of experiment.features.entries()) {
      const angle=angleAt(i);
      const dx=Math.cos(angle),dy=Math.sin(angle), bank=experiment.banks.get(feature.id);
      const active=experiment.enabled.has(feature.id);
      const strength=active && bank.selected.has(bank.focused) ? bank.values[bank.focused] : 0;
      nodes.push(svg('line',{x1:100-dx*68,y1:100-dy*68,x2:100+dx*68,y2:100+dy*68,
        stroke:colour(feature.id),'stroke-opacity':active ? 0.35 : 0.1,'stroke-width':1,'stroke-dasharray':'3 4'}));
      nodes.push(svg('circle',{cx:100+dx*68*strength/2,cy:100+dy*68*strength/2,r:active?5:3,
        fill:colour(feature.id),opacity:active?1:.2,'data-mix-feature':feature.id,class:'mix-knob'}));
      const label=svg('text',{x:100+dx*85,y:104+dy*85,fill:colour(feature.id),'text-anchor':'middle','font-size':16});
      label.textContent=feature.label[0];nodes.push(label);
      x+=dx*strength/2*48/Math.max(1,experiment.enabled.size);
      y+=dy*strength/2*48/Math.max(1,experiment.enabled.size);
    }
    nodes.push(svg('line',{x1:100,y1:100,x2:x,y2:y,stroke:'#8a7b9b','stroke-width':1}));
    nodes.push(svg('circle',{cx:x,cy:y,r:7,fill:'white',stroke:'#77678f','stroke-width':1.5,'pointer-events':'none'}));
    wheel.replaceChildren(...nodes);
  }
  function render() {
    const state=experiment.bank;
    for (const feature of experiment.features) {
      const bank=experiment.banks.get(feature.id), controls=sliders.get(feature.id);
      checks.get(feature.id).checked=experiment.enabled.has(feature.id);
      checks.get(feature.id).disabled=!experiment.vectors.some(v=>v.selectable&&v.available&&v.feature_id===feature.id);
      controls.slider.value=bank.values[bank.focused];
      controls.slider.disabled=!experiment.enabled.has(feature.id) || !bank.selected.has(bank.focused) || !bank.available.has(bank.focused);
      const vector=bank.vectorChoices[bank.focused];
      const summary=experiment.featureSummary(feature.id);
      controls.slider.min=vector?.strength_min??-2;controls.slider.max=vector?.strength_max??2;
      controls.output.textContent=controls.slider.disabled?'—':signed(bank.values[bank.focused]);
      controls.target.textContent=!summary.enabled?'Feature off':`Editing L${bank.focused}${summary.editingSelected?'':' · disabled'}`;
      controls.status.textContent=!summary.enabled?`Off · ${summary.saved.length} saved layer${summary.saved.length===1?'':'s'}`:
        !summary.editingSelected&&summary.active.length?`${summary.active.length} other layer${summary.active.length===1?'':'s'} still active`:
        summary.active.length?`${summary.active.length} active layer${summary.active.length===1?'':'s'} · peak |α| ${summary.peak.toFixed(1)}`:'No nonzero steering';
      controls.status.title='Show every layer and retained strength for this feature';
      const detailRows=summary.saved.map(entry=>{
        const line=document.createElement('div');line.textContent=`L${entry.layer}  ${signed(entry.strength)}${summary.enabled?'':' · saved, feature off'}${entry.strength===0?' · zero shift':''}`;return line;
      });
      if(!detailRows.length){const empty=document.createElement('p');empty.textContent='No layers enabled.';detailRows.push(empty);}
      controls.list.replaceChildren(...detailRows);controls.clear.disabled=summary.saved.length===0;
      controls.edit.setAttribute('aria-pressed',String(experiment.editing===feature.id));
      controls.row.classList.toggle('inactive',!experiment.enabled.has(feature.id));
    }
    $('focused-feature').value=experiment.editing;
    $('focused-pooling').value=state.pooling;
    for (const option of $('focused-pooling').options)
      option.disabled=!experiment.vectors.some(v=>v.available&&v.selectable&&v.feature_id===experiment.editing&&v.pooling===option.value);
    const entries=experiment.entries();
    buttons.forEach((button,index)=>{
      button.classList.toggle('selected',experiment.enabled.has(experiment.editing)&&state.selected.has(index));
      button.classList.toggle('focused',index===state.focused);
      button.classList.toggle('available',state.available.has(index));button.classList.toggle('preview',!state.available.has(index));
      button.setAttribute('aria-pressed',String(experiment.enabled.has(experiment.editing)&&state.selected.has(index)));
      const atLayer=entries.filter(e=>e.layer===index);
      button.dataset.appliedFeatures=atLayer.map(e=>`${e.label} ${signed(e.strength)}`).join(', ');
      const marks=button.querySelector('.layer-feature-marks');
      if (marks) marks.replaceChildren(...atLayer.map(entry=>{
        const mark=document.createElement('i');mark.style.background=colour(entry.feature);return mark;
      }));
    });
    const current=state.vectorChoices[state.focused];
    const feature=experiment.features.find(f=>f.id===experiment.editing);
    $('layer-name').textContent=`Layer ${String(state.focused).padStart(2,'0')}`;
    $('layer-kind').textContent=`${feature.label}${experiment.enabled.has(feature.id)?'':' · feature off'}`;
    $('focused-vector').textContent=current?`Focused vector: ${current.id} · ${current.scale}`:'No vector at this layer';
    $('layer-enabled').checked=state.selected.has(state.focused);
    $('layer-enabled').disabled=!state.available.has(state.focused);
    $('layer-mode-single').checked=state.mode==='single';$('layer-mode-multi').checked=state.mode==='multi';
    $('layer-mode-help').textContent=`Layer mode and pooling apply to ${feature.label}. Other features keep their own settings.`;
    const active=entries.filter(e=>e.strength!==0);
    $('active-layer-summary').textContent=active.length?`${active.length} active direction${active.length===1?'':'s'}`:'Prompt only';
    $('multi-layer-note').hidden=active.length<2;
    $('clear-layers').disabled=entries.length===0;
    const chips=entries.map(entry=>{
      const chip=document.createElement('button');chip.type='button';chip.className='active-layer-chip';
      chip.style.setProperty('--chip-colour',colour(entry.feature));
      chip.textContent=`${entry.label} L${entry.layer} ${signed(entry.strength)} ×`;
      chip.setAttribute('aria-label',`Disable ${entry.label} layer ${entry.layer}`);
      chip.addEventListener('click',()=>change(()=>experiment.banks.get(entry.feature).selected.delete(entry.layer)));
      return chip;
    });
    $('active-layer-list').replaceChildren(...chips);
    renderWheel();
    document.dispatchEvent(new CustomEvent('layer-settings-changed',{detail:state.vectorChoices}));
  }
  $('focused-feature').addEventListener('change',()=>change(()=>experiment.selectFeature($('focused-feature').value)));
  $('focused-pooling').addEventListener('change',()=>change(()=>experiment.bank.useVectorSet(experiment.editing,$('focused-pooling').value)));
  for (const mode of ['single','multi']) $('layer-mode-'+mode).addEventListener('change',()=>{
    if ($('layer-mode-'+mode).checked) change(()=>experiment.bank.setMode(mode));
  });
  buttons.forEach((button,index)=>{
    button.addEventListener('click',()=>change(()=>experiment.bank.focus(index)));
    button.addEventListener('keydown',event=>{
      const count=buttons.length;
      const target={ArrowRight:(index+1)%count,ArrowLeft:(index+count-1)%count,Home:0,End:count-1}[event.key];
      if(target!==undefined){event.preventDefault();change(()=>experiment.bank.focus(target));buttons[target].focus();}
    });
  });
  $('layer-enabled').addEventListener('change',()=>change(()=>experiment.bank.setEnabled($('layer-enabled').checked)));
  $('reset-layers').addEventListener('click',()=>change(()=>experiment.reset()));
  $('clear-layers').addEventListener('click',()=>change(()=>experiment.clear()));
  const wheel=$('mix-wheel');let drag=null;
  function moveKnob(event) {
    if(!drag)return;
    const bank=experiment.banks.get(drag.feature);
    if(!experiment.enabled.has(drag.feature)||bank.focused!==drag.layer||!bank.selected.has(drag.layer)){drag=null;return;}
    const vector=bank.vectorChoices[drag.layer];
    const box=wheel.getBoundingClientRect(),angle=angleAt(experiment.features.findIndex(f=>f.id===drag.feature));
    const x=(event.clientX-box.left)/box.width*200-100,y=(event.clientY-box.top)/box.height*200-100;
    const step=vector.strength_step||.1;
    const value=Math.max(vector.strength_min,Math.min(vector.strength_max,
      Math.round(((x*Math.cos(angle)+y*Math.sin(angle))/68*2)/step)*step));
    change(()=>{bank.values[bank.focused]=Number(value.toFixed(6));});
  }
  wheel.addEventListener('pointerdown',event=>{
    const feature=event.target.dataset.mixFeature,bank=experiment.banks.get(feature);
    if(!bank||!experiment.enabled.has(feature)||!bank.selected.has(bank.focused)||!bank.available.has(bank.focused))return;
    event.preventDefault();drag={feature,layer:bank.focused,pointer:event.pointerId};wheel.setPointerCapture(event.pointerId);moveKnob(event);
  });
  wheel.addEventListener('pointermove',event=>{if(drag?.pointer===event.pointerId)moveKnob(event);});
  wheel.addEventListener('pointerup',event=>{
    if(drag?.pointer!==event.pointerId)return;
    moveKnob(event);drag=null;wheel.releasePointerCapture(event.pointerId);onCommit();
  });
  wheel.addEventListener('pointercancel',()=>{drag=null;});
  render();return experiment;
}
