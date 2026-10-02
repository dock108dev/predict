"""Check inert seals, or reserve and supervise one explicitly approved session."""
import argparse,subprocess,sys
import master

def main():
 p=argparse.ArgumentParser();p.add_argument('--run',action='store_true');p.add_argument('--reason',default='counterpart completion: current NFL/NCAAF H1 refresh');p.add_argument('--offline-evidence',action='append',default=[]);a=p.parse_args()
 if not a.run:
  m,s=master.checked(False);rows=master.ledger(m)
  print('PASS: sealed, '+str(len(rows))+'/2 reservations; no approval, dispatch or credentials accessed');return
 child=master.reserve(a.reason,a.offline_evidence)
 # Each child supervisor has its own 240-second wall bound and owned cleanup.
 subprocess.run([sys.executable,str(child/'execute.py'),'--run'],check=True,timeout=245)
if __name__=='__main__':main()
