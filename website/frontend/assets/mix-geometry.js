// Signed radial scale: -2 at the centre, 0 halfway, +2 at the perimeter.
// Geometry is a UI coordinate system, not measured activation-vector geometry.
export const MIX = {x:160,y:145,radius:88};
export const featureAngle=(index,count)=>-Math.PI/2-2*Math.PI*index/count;
export const strengthRadius=(value,min=-2,max=2)=>Math.max(0,Math.min(1,(value-min)/(max-min)))*MIX.radius;
export function featurePoint(index,count,strength,min=-2,max=2) {
  const angle=featureAngle(index,count),radius=strengthRadius(strength,min,max);
  return {x:MIX.x+Math.cos(angle)*radius,y:MIX.y+Math.sin(angle)*radius};
}
export function pointStrength(x,y,index,count,min=-2,max=2,step=.1) {
  const angle=featureAngle(index,count);
  const radius=(x-MIX.x)*Math.cos(angle)+(y-MIX.y)*Math.sin(angle);
  const value=min+radius/MIX.radius*(max-min);
  return Number(Math.max(min,Math.min(max,Math.round(value/step)*step)).toFixed(6));
}
