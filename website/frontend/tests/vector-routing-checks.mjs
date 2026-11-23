import assert from 'node:assert/strict';

// Exercise actual controls/request construction for every displayed vector.
// Only completion text is stubbed. Every request resolves against the real API.
export async function checkEveryVectorRoute({evaluate,until}) {
  await evaluate(`
    window.__vectorQA={fetch:window.fetch,requests:[]};
    window.fetch=async function(url,options){
      if(String(url).endsWith('/cancel'))return new Response('{}');
      if(!String(url).endsWith('/runs/stream'))return window.__vectorQA.fetch.call(window,url,options);
      const body=JSON.parse(options.body);
      const response=await window.__vectorQA.fetch.call(window,'/api/v2/lab/runs/resolve',{
        method:'POST',headers:{'Content-Type':'application/json'},body:options.body});
      if(!response.ok)throw new Error('Vector resolution failed: '+await response.text());
      const resolved=(await response.json()).resolved;
      window.__vectorQA.requests.push({body,resolved});
      const completed={event:'completed',revision:body.revision,text:'Routing audit response.',
        finish_reason:'stop',generated_tokens:4,latency_ms:0,applied:resolved};
      return new Response(JSON.stringify(completed)+'\\n',{
        headers:{'Content-Type':'application/x-ndjson'}});
    };
  `);
  const features=await evaluate(`[...document.querySelector('#focused-feature').options].map(o=>o.value)`);
  const report=[];
  try {
    for(const feature of features) for(const pooling of ['mean','final_token']) {
      await evaluate(`document.querySelector('#clear').click();window.__chooseFamily('${feature}','${pooling}')`);
      for(let layer=0;layer<24;layer++) {
        const strength=layer%2?-.4:.7,count=report.length+1;
        await evaluate(`
          document.querySelector('#draft').value='Vector audit ${feature} ${pooling} ${layer}';
          document.querySelector('#draft').dispatchEvent(new Event('input'));
          document.querySelector('[data-layer="${layer}"]').click();
          document.querySelector('#mix-${feature}').value=${strength};
          document.querySelector('#mix-${feature}').dispatchEvent(new Event('input'));
          document.querySelector('#mix-${feature}').dispatchEvent(new Event('change'));
        `);
        await until(`window.__vectorQA.requests.length===${count} && document.querySelector('#output-card').getAttribute('aria-busy')==='false'`,10);
        const actual=await evaluate(`(() => {
          const request=window.__vectorQA.requests.at(-1),button=document.querySelector('[data-layer="${layer}"]');
          return {...request,colourVector:button.dataset.evidenceVectorId,score:Number(button.dataset.evidenceValue)};
        })()`);
        const expectedId=`qwen-${feature}-l${layer}-${pooling}-v1`;
        assert.deepEqual(actual.body.interventions,[{vector_id:expectedId,strength}]);
        const resolved=actual.resolved.plan.interventions;
        assert.equal(resolved.length,1);
        assert.equal(resolved[0].vector_id,expectedId);
        assert.equal(resolved[0].feature_id,feature);
        assert.equal(resolved[0].layer_index,layer);
        assert.equal(resolved[0].pooling,pooling);
        assert.equal(resolved[0].strength,strength);
        assert.equal(actual.colourVector,expectedId);
        report.push({vector_id:expectedId,layer,pooling,feature,strength,score:actual.score,
          artifact_id:resolved[0].artifact_id,artifact_sha256:resolved[0].artifact_sha256});
      }
    }
  } finally {
    await evaluate(`document.querySelector('#clear').click();document.querySelector('#reset-layers').click();window.fetch=window.__vectorQA.fetch`);
  }
  console.log('Verified '+report.length+' actual frontend requests against backend vector resolution.');
  return report;
}
