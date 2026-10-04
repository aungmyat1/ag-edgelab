from __future__ import annotations
import csv,json,sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,'src')
sys.path.insert(0,'.')
import mtf_control_shift.engine as engine
from ag_edgelab.data.fx_histdata import *
from scripts.run_mtf_control_shift_v1_campaign import replay_symbol, stats, DEV, SESSIONS, candle, _validate_raw_path_local

OUT=Path('artifacts/mtf_control_shift_v1')

def main():
    # Candidate-only runtime override. The frozen V1 source/artifacts are never edited.
    original=engine.H1_SHIFT_MAX_AGE_BARS
    engine.H1_SHIFT_MAX_AGE_BARS=24
    try:
      matrix=[]; all_rows=[]; total=Counter(); false=Counter()
      for symbol in SYMBOLS:
        path=Path('data/raw/fx_histdata')/f'HISTDATA_COM_ASCII_{symbol}_M1_2017.zip'
        raw=_validate_raw_path_local(path,symbol); m=load_m1(path,symbol,end=DEV[1]); bars,_=derive_all(m,symbol,raw)
        rows,fun,fc=replay_symbol(symbol,bars,DEV); all_rows += rows; total.update(fun); false.update(fc)
        for sess in SESSIONS:
          rr=[r for r in rows if r['session']==sess]; st=stats(rr)
          st.update({'symbol':symbol,'session':sess,'status':'SURVIVES_DEV_SCREEN' if st['net_expectancy'] is not None and st['net_expectancy']>0 else ('INSUFFICIENT_SAMPLE' if not rr else 'FAILS_DEV_SCREEN')})
          matrix.append(st)
      (OUT/'v2_dev_result.json').write_text(json.dumps({'strategy_id':'ST_MTF_CONTROL_SHIFT_V2','version':'2.0.0','max_h1_shift_age_bars':24,'partition':'DEV','matrix':matrix},indent=2,default=str)+'\n')
      with (OUT/'v2_dev_matrix.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(matrix[0])); w.writeheader(); w.writerows(matrix)
      (OUT/'v2_ledger.jsonl').write_text('\n'.join(json.dumps(x,default=str) for x in all_rows)+'\n')
      (OUT/'v2_funnel_analysis.json').write_text(json.dumps({'strategy_id':'ST_MTF_CONTROL_SHIFT_V2','totals':dict(total),'false_choch':dict(false)},indent=2)+'\n')
      print(json.dumps({'matrix':matrix,'funnel':dict(total),'false_choch':dict(false),'trades':len(all_rows)},indent=2,default=str))
    finally:
      engine.H1_SHIFT_MAX_AGE_BARS=original
if __name__=='__main__': main()
