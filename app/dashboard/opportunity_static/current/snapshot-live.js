// Revision-bound inspection independent of the rolling list. No financial math.
const SnapshotLive = (() => {
  const copy=value=>structuredClone(value);
  const canonical=value=>JSON.stringify(value,(_,v)=>v&&typeof v==='object'&&!Array.isArray(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])):v);
  function facts(row){
    if(!row)return null;
    const reference=row.reference_calculation||{};
    const fee=value=>value?{...Object.fromEntries(['ranking_basis','quantity','quantity_unit','fill_count','liquidity_role',
      'trade_fee_usd','normalization_risk_usd','return_percent','formula','fee_payment','assumptions','reason'].map(k=>[k,value[k]??null])),
      evidence:Object.fromEntries(['version','sha256','reviewed_at','review_before'].map(k=>[k,value.evidence?.[k]??null]))}:null;
    return {price_revision:row.price_revision??null,economic_revision:row.economic_revision??null,
      original:row.original,offered:row.display?.offered??null,before_trade_fee:row.gross_return_percent??null,after_trade_fee:row.conditional_return_percent??null,
      conservative_estimate:row.conservative_return_percent??null,price_current:row.price_current??null,
      probability:row.probability??null,reference_pair:(reference.pair||[]).map(r=>({id:r.id,source:r.source,original:r.original,selection:r.selection})),
      reference_venue:reference.venue??row.display?.benchmark_venue??null,
      reference_selected:reference.selected??null,fee_basis:fee(row.conditional_trade_benchmark),
      conservative_fee_basis:fee(row.conservative_trade_benchmark),
      metric_status:Object.fromEntries(Object.entries(row.metric_status||{}).map(([k,v])=>[k,{state:v.state,reasons:[...(v.reasons||[])].sort()}])),
      reasons:[...(row.current_reasons||[])].sort(),settings_revision:row.settings_revision,
      fee_revision:row.current_authority?.fee_revision};
  }
  function create({request,release,onChange=()=>{},onError=()=>{}}){
    let pinned=null,notice=null,opening=null,error=null,epoch=0,checks=0;
    const emit=()=>onChange({pinned,notice,opening,error});
    const fail=message=>{error=message;emit();onError(message);};
    function compare(latest){
      const old=facts(pinned.row),next=facts(latest.row);
      notice=canonical(old)===canonical(next)?null:{state:latest.state,old,latest:next,
        result_id:latest.result_id,cursor:latest.cursor,can_adopt:latest.state==='ready'};
      emit();return latest;
    }
    async function retain(row,result,metric,ticket,verifyLatest=false){
      const candidate={row:copy(row),result:copy(result),metric,lease:null,details:null};
      const resultId=row.evidence_result_id||result.id||result.result_id;
      let token;
      try{
        token=await request('/api/comparison-current/lease',{result_id:resultId});
        const details=await request('/api/comparison-snapshot/details?'+new URLSearchParams({result_id:resultId,id:row.id,lease_id:token.lease_id}));
        if(details.row.id!==row.id||details.row.price_revision!==row.price_revision||details.row.economic_revision!==row.economic_revision)throw Error('Selected evidence does not match the displayed revision');
        if(verifyLatest){
          const latest=await request('/api/comparison-current/selection?'+new URLSearchParams({id:row.id}));
          if(latest.state!=='ready'||canonical(facts(latest.row))!==canonical(facts(row))){
            if(ticket===epoch)compare(latest);
            throw Error('Latest inputs changed while retaining them; previous calculation remains pinned');
          }
        }
        if(ticket!==epoch){release(token.lease_id);return false;}
        candidate.lease=token;candidate.details=copy(details);
        const previous=pinned;pinned=candidate;opening=null;notice=null;error=null;++checks;
        emit();if(previous?.lease)release(previous.lease.lease_id);
        return true;
      }catch(e){if(token)release(token.lease_id);if(ticket===epoch){opening=null;fail('Exact selection unavailable: '+e.message);}return false;}
    }
    async function open(row,result,metric){
      const ticket=++epoch;++checks;error=null;opening={row:copy(row),result:copy(result),metric};emit();
      return retain(row,result,metric,ticket);
    }
    async function check(){
      if(!pinned||opening)return null;
      const ticket=++checks,version=epoch,id=pinned.row.id;
      const latest=await request('/api/comparison-current/selection?'+new URLSearchParams({id}));
      if(ticket!==checks||version!==epoch||pinned?.row.id!==id)return null;
      return compare(latest);
    }
    async function adopt(){
      if(!pinned||opening)return false;
      const previous=pinned,ticket=++epoch;++checks;
      try{
        const latest=await request('/api/comparison-current/selection?'+new URLSearchParams({id:previous.row.id}));
        if(ticket!==epoch)return false;
        compare(latest);
        if(latest.state!=='ready'||!latest.row)return false;
        const result={...previous.result,...latest,id:latest.result_id};
        opening={row:copy(latest.row),result,metric:previous.metric};emit();
        return await retain(latest.row,result,previous.metric,ticket,true);
      }catch(e){if(ticket===epoch)fail('Latest selection unavailable: '+e.message);return false;}
    }
    function close(){++epoch;++checks;const previous=pinned;pinned=null;notice=null;opening=null;error=null;emit();if(previous?.lease)release(previous.lease.lease_id);}
    async function renew(){
      const selected=pinned;if(!selected?.lease)return;
      try{await request('/api/comparison-current/lease',{result_id:selected.lease.result_id,lease_id:selected.lease.lease_id});}
      catch(e){if(selected===pinned)fail('Retained evidence lease unavailable: '+e.message);}
    }
    return {open,check,adopt,close,renew,get state(){return {pinned,notice,opening,error};}};
  }
  return {create,facts};
})();
