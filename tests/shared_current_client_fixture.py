"""Authored complete native matrix for client rendering; no SQL or providers."""
import asyncio,json
from datetime import datetime,timezone
from types import SimpleNamespace
from app.storage.comparison_board import ReadContext,observation_identity
from app.dashboard.comparison_board import response,expand_odds
from app.comparison.estimated_policy import DEFAULT_POLICY
from tests.broad_pipeline_fixtures import captured_core_matrix

async def main():
 at=datetime.now(timezone.utc);rows,_=await captured_core_matrix(at)
 context=ReadContext(SimpleNamespace(db=None),at=at.isoformat(),frame=dict(epoch='authored-shared-current',revision='authored',records=rows))
 boards=[]
 for b in context.observation_bundles():
  b['calculation_context']=observation_identity(b,context)
  boards.append(expand_odds(response(b,None,DEFAULT_POLICY,view='odds',filter='all',at=at.isoformat())))
 print(json.dumps(dict(boards=boards,games=context.catalog()['games'],at=at.isoformat(),evidence_class='authored',provider_requests=0)))
if __name__=='__main__':asyncio.run(main())
