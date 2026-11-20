// Theme derivation and starter palettes from the approved Prism reference.
export const palettes=[
 {id:'prism',name:'Prism',primary:'#b69ae8',secondary:'#edb8dc'},
 {id:'midnight',name:'Midnight',primary:'#8299d7',secondary:'#c7d5f6'},
 {id:'cobalt',name:'Cobalt',primary:'#4779eb',secondary:'#d4e3ff'},
 {id:'slate',name:'Slate',primary:'#849bab',secondary:'#d9e1e5'},
 {id:'teal',name:'Teal',primary:'#3ca5a7',secondary:'#b7e3d5'},
 {id:'emerald',name:'Emerald',primary:'#3c9a70',secondary:'#d7e9ad'},
 {id:'pine',name:'Pine',primary:'#568170',secondary:'#ded2a6'},
 {id:'burgundy',name:'Burgundy',primary:'#a04468',secondary:'#e7c6a4'},
 {id:'rose',name:'Rose',primary:'#d37d9d',secondary:'#e8d0f2'},
 {id:'coral',name:'Coral',primary:'#dc846c',secondary:'#f5dfb2'},
 {id:'amber',name:'Amber',primary:'#c68b38',secondary:'#ece1c6'},
 {id:'gold',name:'Gold',primary:'#c4ad46',secondary:'#e8e0a6'},
 {id:'crimson',name:'Crimson',primary:'#c84b55',secondary:'#f0d0c2'},
 {id:'ice',name:'Ice',primary:'#79b7d7',secondary:'#c6e5e9'},
 {id:'mono',name:'Monochrome',primary:'#b5b2bd',secondary:'#e4e0e9'}
];
function rgb(hex){return hex.slice(1).match(/../g).map(v=>parseInt(v,16));}
function hex(values){return '#'+values.map(v=>Math.round(v).toString(16).padStart(2,'0')).join('');}
function blend(a,b,t){const x=rgb(a),y=rgb(b);return hex(x.map((v,i)=>v*(1-t)+y[i]*t));}
function luminance(color){const c=rgb(color).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;});return .2126*c[0]+.7152*c[1]+.0722*c[2];}
function contrast(a,b){const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);}
function accessible(color,surface,dark,target=4.6){let result=color;for(let i=0;i<40&&contrast(result,surface)<target;i++)result=blend(result,dark?'#ffffff':'#11111a',.075);return result;}
export function themeTokens(theme,appearance){
 const dark=appearance==='system'?matchMedia('(prefers-color-scheme: dark)').matches:appearance==='dark';
 const p=theme.primary,s=theme.secondary;
 const bg=blend(dark?'#15101e':'#faf8fd',p,dark ? .11 : .055);
 const surface=blend(dark?'#261e34':'#ffffff',p,dark ? .08 : .025);
 const raised=blend(surface,p,dark ? .12 : .055);
 const fg=dark?'#f6f1fb':'#262132';
 return {dark,tokens:{bg,surface,raised,fg,muted:accessible(blend(fg,surface,dark ? .28 : .36),raised,dark),line:blend(surface,p,dark ? .34 : .22),'control-line':accessible(blend(surface,p,.35),raised,dark,3.1),accent:accessible(p,raised,dark),'accent-soft':blend(surface,p,dark ? .24 : .13),'on-accent':'',secondary:accessible(s,raised,dark),positive:dark?'#b2e8ce':'#155c42','positive-bg':dark?'#29453b':'#e0f0e8',negative:dark?'#ffc3ce':'#a52e45','negative-bg':dark?'#4b2b39':'#fbe8ed',warning:dark?'#f4dbad':'#725015','warning-bg':dark?'#433829':'#f7edcf',glow:blend(bg,s,dark ? .16 : .065)}};
}
