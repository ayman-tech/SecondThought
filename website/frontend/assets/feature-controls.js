import { FeatureExperiment } from './feature-state.js';
import { mixFrame,featureAngle,featurePoint,pointStrength } from './mix-geometry.js';

const colours=['#7954df','#208c89','#ce7c3b','#b7508b','#3f76bd','#887032','#527b50'];
export function mountFeatureLayers(onChange,onCommit=()=>{}) {
  const $=id=>document.getElementById(id);
  const experiment=new FeatureExperiment(JSON.parse($('layer-vector-data').textContent));
  const sources=JSON.parse($('feature-source-data').textContent);
  document.querySelector('.model-visual').style.setProperty('--extra-features',Math.min(2,Math.max(0,experiment.features.length-2)));
  const buttons=[...document.querySelectorAll('[data-layer]')];
  const signed=n=>`${n>=0?'+':'−'}${Math.abs(n).toFixed(1)}`;
  const colour=id=>{const index=experiment.features.findIndex(f=>f.id===id);
    return colours[index]||`hsl(${(index*137.508)%360} 55% 42%)`;};
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
    const wheel=$('mix-wheel'),nodes=[],count=experiment.features.length;
    const frame=mixFrame(count);
    wheel.setAttribute('viewBox',`0 0 ${frame.width} ${frame.height}`);
    const focused=document.activeElement?.dataset.mixFeature;
    const points=fraction=>experiment.features.map((_,i)=>featurePoint(i,count,-2+4*fraction))
      .map(p=>`${p.x},${p.y}`).join(' ');
    const defs=svg('defs',{}),gradient=svg('linearGradient',{id:'mix-fill',x1:'0%',y1:'0%',x2:'100%',y2:'100%'});
    for(const [offset,fill] of [['0%','#7954df'],['55%','#ce7c3b'],['100%','#208c89']])
      gradient.append(svg('stop',{offset,'stop-color':fill,'stop-opacity':'.22'}));
    defs.append(gradient);nodes.push(defs);
    for(const fraction of [.25,.5,.75,1])
      nodes.push(svg('polygon',{points:points(fraction),fill:fraction===1?'#f7f8fc':'none',
        stroke:fraction===.5?'#bcb0cf':'#dfe5ef','stroke-width':fraction===.5?1.4:1,
        'stroke-dasharray':fraction===1?'3 3':'none',class:'mix-web-ring'}));
    // Move the outer background behind the inner grid lines.
    nodes.splice(1,0,nodes.pop());
    const positions=experiment.features.map((feature,i)=>{
      const bank=experiment.banks.get(feature.id),vector=bank.vectorChoices[bank.focused];
      const active=experiment.enabled.has(feature.id)&&bank.selected.has(bank.focused)&&bank.available.has(bank.focused);
      return featurePoint(i,count,active?bank.values[bank.focused]:0,vector?.strength_min??-2,vector?.strength_max??2);
    });
    nodes.push(svg('polygon',{points:positions.map(p=>`${p.x},${p.y}`).join(' '),fill:'url(#mix-fill)',
      stroke:'#9870e9','stroke-width':2,'stroke-linejoin':'round',class:'mix-web-shape'}));
    for (const [i,feature] of experiment.features.entries()) {
      const bank=experiment.banks.get(feature.id),summary=experiment.featureSummary(feature.id);
      const active=summary.enabled&&summary.editingSelected&&bank.available.has(bank.focused);
      const vector=bank.vectorChoices[bank.focused],point=positions[i],end=featurePoint(i,count,2);
      nodes.push(svg('line',{x1:frame.x,y1:frame.y,x2:end.x,y2:end.y,stroke:'#c9d2e2','stroke-width':1,'pointer-events':'none'}));
      const knob=svg('circle',{cx:point.x,cy:point.y,r:6,fill:active?colour(feature.id):'#fff',
        stroke:active?'#fff':colour(feature.id),'stroke-width':2,'data-mix-feature':feature.id,
        class:'mix-knob',tabindex:active?0:-1,role:'slider','aria-label':`${feature.label} layer ${bank.focused} strength`,
        'aria-valuemin':vector?.strength_min??-2,'aria-valuemax':vector?.strength_max??2,
        'aria-valuenow':active?bank.values[bank.focused]:0,'aria-disabled':String(!active)});
      const title=svg('title',{});title.textContent=`${feature.label}: ${active?signed(bank.values[bank.focused]):'off'} at layer ${bank.focused}. ${summary.active.length} active layers.`;
      knob.append(title);nodes.push(knob);
      const top=i===0,left=Math.cos(featureAngle(i,count))<0;
      let x=top?160:left?8:312,y=top?12:224,anchor=top?'middle':left?'start':'end';
      if(count>3) {
        const angle=featureAngle(i,count),dx=Math.cos(angle);
        x=frame.x+dx*180;y=frame.y+Math.sin(angle)*180-22;
        anchor=Math.abs(dx)<.2?'middle':dx<0?'end':'start';
        const width=feature.label.length*9.6;
        if(anchor==='end')x=Math.max(width+8,x);
        if(anchor==='start')x=Math.min(frame.width-width-8,x);
      }
      const label=svg('text',{x,y,fill:colour(feature.id),'text-anchor':anchor,class:'mix-axis-label'});
      label.textContent=feature.label;nodes.push(label);
      const width=count>3?108:84,badgeX=anchor==='middle'?x-width/2:anchor==='start'?x:x-width;
      nodes.push(svg('rect',{x:badgeX,y:y+6,width,height:20,rx:5,fill:colour(feature.id),'fill-opacity':'.08',stroke:colour(feature.id),'stroke-opacity':'.2'}));
      const value=svg('text',{x:badgeX+width/2,y:y+20,fill:colour(feature.id),'text-anchor':'middle',class:'mix-axis-value'});
      value.textContent=active?`${signed(bank.values[bank.focused])} α`:'0.0 (Off)';nodes.push(value);
      const status=svg('text',{x,y:y+38,fill:'#8c8198','text-anchor':anchor,class:'mix-axis-status'});
      status.textContent=summary.enabled?`L${bank.focused} · ${summary.active.length} active`:`${summary.saved.length} saved layer${summary.saved.length===1?'':'s'}`;
      nodes.push(status);
    }
    nodes.push(svg('circle',{cx:frame.x,cy:frame.y,r:2,fill:'#a9a1b7','pointer-events':'none'}));
    wheel.replaceChildren(...nodes);
    if(focused) wheel.querySelector(`[data-mix-feature="${CSS.escape(focused)}"]`)?.focus({preventScroll:true});
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
      controls.slider.step=vector?.strength_step??.1;
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
    const source=sources[current?.artifact_id]||{};
    $('feature-data-name').textContent=feature.label;
    $('feature-data-dataset').textContent=source.dataset||'Dataset provenance unavailable';
    $('feature-data-pairs').textContent=`${source.pair_construction||'Target-minus-source revision pairs'}. Extraction: ${source.extraction_pairs??'unknown'}; held-out: ${source.heldout_pairs??'unknown'}.`;
    $('feature-data-limits').textContent=source.limitations||'Experimental direction. Meaning preservation and task transfer are not established.';
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
    const point=wheel.createSVGPoint();point.x=event.clientX;point.y=event.clientY;
    const local=point.matrixTransform(wheel.getScreenCTM().inverse());
    const value=pointStrength(local.x,local.y,experiment.features.findIndex(f=>f.id===drag.feature),experiment.features.length,
      vector.strength_min,vector.strength_max,vector.strength_step||.1);
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
  wheel.addEventListener('keydown',event=>{
    const feature=event.target.dataset.mixFeature,bank=experiment.banks.get(feature);
    if(!bank||!experiment.enabled.has(feature)||!bank.selected.has(bank.focused)||!bank.available.has(bank.focused))return;
    const vector=bank.vectorChoices[bank.focused],step=vector.strength_step||.1;
    const next={ArrowUp:bank.values[bank.focused]+step,ArrowRight:bank.values[bank.focused]+step,
      ArrowDown:bank.values[bank.focused]-step,ArrowLeft:bank.values[bank.focused]-step,
      Home:vector.strength_min,End:vector.strength_max}[event.key];
    if(next===undefined)return;
    event.preventDefault();change(()=>{bank.values[bank.focused]=Number(Math.max(vector.strength_min,Math.min(vector.strength_max,next)).toFixed(6));});
  });
  wheel.addEventListener('keyup',event=>{
    const feature=event.target.dataset.mixFeature,bank=experiment.banks.get(feature);
    if(bank&&experiment.enabled.has(feature)&&bank.selected.has(bank.focused)&&bank.available.has(bank.focused)&&
      ['ArrowUp','ArrowDown','ArrowLeft','ArrowRight','Home','End'].includes(event.key))onCommit();
  });
  render();return experiment;
}
