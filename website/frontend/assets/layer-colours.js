// Selection colours are independent of extraction statistics and alpha magnitude.
export const FEATURE_COLOURS = {
  formality:'#7954df', fluency:'#ce7c3b', empathy:'#b7508b', politeness:'#208c89',
};
export function layerAppearance(features) {
  const ids=Object.keys(FEATURE_COLOURS).filter(id=>features.includes(id));
  if (!ids.length) return {fill:'#edf0f5', border:'#b9c1ce', features:[]};
  const tint=id=>{
    const hex=FEATURE_COLOURS[id];
    return `rgba(${[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)).join(', ')}, 0.24)`;
  };
  const fill=ids.length===1?tint(ids[0]):`linear-gradient(90deg, ${ids.map((id,i)=>
    `${tint(id)} ${100*i/ids.length}% ${100*(i+1)/ids.length}%`).join(', ')})`;
  return {fill,border:FEATURE_COLOURS[ids[0]],features:ids};
}
