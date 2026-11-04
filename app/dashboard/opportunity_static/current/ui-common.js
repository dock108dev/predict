// Shared presentation only. Exact calculations and conversions belong to Python.
const UI = (() => {
  const el = (tag, text, cls) => { const e=document.createElement(tag); if(text!=null)e.textContent=text;if(cls)e.className=cls;return e; };
  const num = v => {if(v==null)return null;const p=String(v).split('/');return Number(p[0])/(p.length===2?Number(p[1]):1);};
  const fmt = (v,d=2) => v==null?'Unavailable':num(v).toLocaleString('en-US',{maximumFractionDigits:d,minimumFractionDigits:d});
  const names={kalshi:'Kalshi',polymarket_us:'Polymarket US',novig:'Novig',prophetx:'ProphetX',pinnacle:'Pinnacle',winner:'Winner',spread:'Spread',total:'Total'};
  const name=v=>names[v]||v;
  let format='american';try{format=localStorage.getItem('predict-odds-format')==='decimal'?'decimal':'american';}catch{}
  function updateOdds(){for(const e of document.querySelectorAll('[data-american]'))e.textContent=e.dataset[format]||'Unavailable';for(const b of document.querySelectorAll('[data-format]'))b.setAttribute('aria-pressed',String(b.dataset.format===format));}
  function odd(o,cls='p-odds'){const e=el('span',null,cls);e.dataset.american=o?.american||'';e.dataset.decimal=o?.decimal?fmt(o.decimal):'';e.textContent=e.dataset[format]||'Unavailable';return e;}
  function link(text,path,cls){const a=el('a',text,cls);a.href=path;return a;}
  function button(text,fn,cls='p-outline'){const b=el('button',text,cls);b.type='button';b.onclick=fn;return b;}
  function shell(){
    const host=document.querySelector('[data-shell]');if(!host)return;
    const h=el('header',null,'p-chrome'),brand=link('Predict.','/','p-brand'),nav=el('nav',null,'p-nav');nav.setAttribute('aria-label','Predict');
    nav.append(link('Opportunities','/'),link('Markets','/odds'));
    const f=el('div',null,'p-format');f.setAttribute('aria-label','Odds format');
    for(const [key,label] of [['american','American'],['decimal','Decimal']]){const b=button(label,()=>{format=key;try{localStorage.setItem('predict-odds-format',key);}catch{}updateOdds();},'');b.dataset.format=key;f.append(b);}
    h.append(brand,nav,f,link('Admin','/admin','p-admin'));host.replaceChildren(h);
    const path=location.pathname;for(const a of h.querySelectorAll('a'))if(a.pathname===(path==='/arbs'||path==='/ev'?'/':path))a.setAttribute('aria-current','page');
    updateOdds();
  }
  function adminNav(){const nav=el('nav',null,'p-adminnav');nav.setAttribute('aria-label','Admin sections');for(const [key,label] of [['overview','Overview'],['timing','Quote timing'],['coverage','Coverage'],['usage','Usage & budget'],['calculations','Calculations'],['inspection','Exact inspection']]){const a=link(label,'/admin?section='+key);if((new URLSearchParams(location.search).get('section')||'overview')===key)a.setAttribute('aria-current','page');nav.append(a);}return nav;}
  function localURL(raw){
    if(!raw)return null;
    try{
      const url=new URL(raw,location.origin);
      return url.origin===location.origin?url:null;
    }catch{
      // A damaged saved return link must not prevent the comparison rendering.
      return null;
    }
  }
  function carry(result){
    const here=new URL(location.href);
    for(const a of document.querySelectorAll('.p-chrome a,.p-adminnav a')){
      const u=new URL(a.href);if(result)u.searchParams.set('result_id',result);
      if(u.pathname==='/admin'){
        for(const key of ['selection','selected_metric','back'])if(here.searchParams.get(key))u.searchParams.set(key,here.searchParams.get(key));
        if(here.pathname!=='/admin')u.searchParams.set('back',here.pathname+here.search);
      }else if(here.searchParams.has('back')){
        const back=localURL(here.searchParams.get('back'));
        if(back&&back.pathname===u.pathname){if(result)back.searchParams.set('result_id',result);a.href=back;continue;}
      }
      a.href=u;
    }
  }
  shell();return {el,num,fmt,name,odd,link,button,updateOdds,adminNav,carry,localURL};
})();
window.PredictUI=UI;
