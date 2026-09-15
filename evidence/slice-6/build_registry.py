"""Reproducible curated registry build; reads existing sanitized captures only."""
import json
from pathlib import Path
from app.normalization.names import name_key
ROOT = Path(__file__).resolve().parents[2]
NFL = '''ARI|Arizona|Cardinals
ATL|Atlanta|Falcons
BAL|Baltimore|Ravens
BUF|Buffalo|Bills
CAR|Carolina|Panthers
CHI|Chicago|Bears
CIN|Cincinnati|Bengals
CLE|Cleveland|Browns
DAL|Dallas|Cowboys
DEN|Denver|Broncos
DET|Detroit|Lions
GB|Green Bay|Packers
HOU|Houston|Texans
IND|Indianapolis|Colts
JAX|Jacksonville|Jaguars
KC|Kansas City|Chiefs
LV|Las Vegas|Raiders
LAC|Los Angeles|Chargers
LAR|Los Angeles|Rams
MIA|Miami|Dolphins
MIN|Minnesota|Vikings
NE|New England|Patriots
NO|New Orleans|Saints
NYG|New York|Giants
NYJ|New York|Jets
PHI|Philadelphia|Eagles
PIT|Pittsburgh|Steelers
SF|San Francisco|49ers
SEA|Seattle|Seahawks
TB|Tampa Bay|Buccaneers
TEN|Tennessee|Titans
WAS|Washington|Commanders'''
MLB = '''ARI|Arizona|Diamondbacks
ATL|Atlanta|Braves
BAL|Baltimore|Orioles
BOS|Boston|Red Sox
CHC|Chicago|Cubs
CWS|Chicago|White Sox
CIN|Cincinnati|Reds
CLE|Cleveland|Guardians
COL|Colorado|Rockies
DET|Detroit|Tigers
HOU|Houston|Astros
KC|Kansas City|Royals
LAA|Los Angeles|Angels
LAD|Los Angeles|Dodgers
MIA|Miami|Marlins
MIL|Milwaukee|Brewers
MIN|Minnesota|Twins
NYM|New York|Mets
NYY|New York|Yankees
ATH||Athletics
PHI|Philadelphia|Phillies
PIT|Pittsburgh|Pirates
SD|San Diego|Padres
SF|San Francisco|Giants
SEA|Seattle|Mariners
STL|St. Louis|Cardinals
TB|Tampa Bay|Rays
TEX|Texas|Rangers
TOR|Toronto|Blue Jays
WSH|Washington|Nationals'''
d={'schema_version':1,'version':'2026-09-12.1','verified_at':'2026-09-12',
   'planned_leagues':['NFL','NCAAF','MLB','NBA','NHL'],'entities':[],'aliases':[],'native_mappings':[]}
aliases={}
def alias(kind,league,text,target,source,venue=None):
 key=(kind,league,venue,name_key(text))
 if key not in aliases: aliases[key]={'kind':kind,'league':league,'venue':venue,'text':text,'targets':[],'source':source}
 if target not in aliases[key]['targets']: aliases[key]['targets'].append(target)
for league,rows,source,full in [('NFL',NFL,'https://www.nfl.com/teams/','National Football League'),('MLB',MLB,'https://www.mlb.com/team','Major League Baseball')]:
 d['entities'].append({'kind':'league','id':league,'name':full,'source':source})
 for n in (league,full):alias('league',None,n,league,source)
 for row in rows.splitlines():
  code,city,nickname=row.split('|');name=f'{city} {nickname}'.strip();id=f'{league}:{code}'
  d['entities'].append({'kind':'team','id':id,'league':league,'name':name,'source':source})
  for n in (name,code,city,nickname,id):
   if n: alias('team',league,n,id,source+'; curated explicit shorthand v1')
# Common exact alternate forms; city disambiguators retain the team distinction.
for id,names in {'NFL:JAX':['JAC'],'NFL:WAS':['WSH'],'NFL:LAC':['LA Chargers','Los Angeles C'], 'NFL:LAR':['LA Rams','Los Angeles R'], 'NFL:NYJ':['NY Jets','New York J'],'NFL:NYG':['NY Giants','New York G'],'MLB:NYY':['NY Yankees'],'MLB:NYM':['NY Mets'],'NFL:TB':['Tampa Bay Bucs','Bucs']}.items():
 for n in names:alias('team',id.split(':')[0],n,id,'curated-explicit-shorthand:v1')
by_name={e['name']:e['id'] for e in d['entities']}
seen={}
def mapping(kind,venue,env,league,native,target,source):
 key=(kind,venue,env,league,str(native))
 if key in seen:
  assert seen[key]==target
  return
 seen[key]=target
 d['native_mappings'].append({'kind':kind,'venue':venue,'environment':env,'league':league,'native_id':str(native),'target':target,'source':source})
p='evidence/phase-0/pmus-nfl-events.json';data=json.loads((ROOT/p).read_text())
mapping('league','polymarket_us','production',None,data['league']['id'],'NFL',p+'#/league')
for i,e in enumerate(data['events']):
 for j,t in enumerate(e['teams']):
  mapping('team','polymarket_us','production','NFL',t['id'],by_name[t['name']],f'{p}#/events/{i}/teams/{j}')
p='evidence/slice-3/sandbox-qualification-20260912/attempt-1/sandbox-20260912T005720Z/market-002.json'
for i,e in enumerate(json.loads((ROOT/p).read_text())['data']['sport_events']):
 mapping('league','prophetx','sandbox',None,e['tournament_id'],'NFL',f'{p}#/data/sport_events/{i}/tournament_id')
 for j,t in enumerate(e['competitors']):
  mapping('team','prophetx','sandbox','NFL',t['id'],by_name[t['name']],f'{p}#/data/sport_events/{i}/competitors/{j}')
d['aliases']=list(aliases.values())
(ROOT/'app/normalization/registry-v1.json').write_text(json.dumps(d,indent=2,sort_keys=True)+'\n')
