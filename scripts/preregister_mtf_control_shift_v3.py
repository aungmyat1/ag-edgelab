from __future__ import annotations
import hashlib,json
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path('.')
OUT=ROOT/'artifacts/mtf_control_shift_v1'
V2=ROOT/'strategies/ST_MTF_CONTROL_SHIFT_V2.yaml'; V3=ROOT/'strategies/ST_MTF_CONTROL_SHIFT_V3.yaml'

def main():
    temporal=json.loads((OUT/'v2_temporal_coupling.json').read_text())
    cases=temporal['cases_detail']
    assert len(cases)==18
    v2_eligible=18
    same=[]; prior=[]; future=[]
    for x in cases:
        session_date=datetime.fromisoformat(x['timestamp']).astimezone(timezone.utc).date()
        shift_date=datetime.fromisoformat(x['h1_shift_time']).astimezone(timezone.utc).date()
        if shift_date==session_date:same.append(x)
        elif shift_date<session_date:prior.append(x)
        else:future.append(x)
    v3_eligible=len(same)
    assert len(prior)==18 and len(future)==0 and v3_eligible==0
    prereg={
      'preregistration_status':'PREREGISTERED_BEFORE_V3_DEV_REPLAY',
      'parent_strategy':{'strategy_id':'ST_MTF_CONTROL_SHIFT_V2','version':'2.0.0','yaml_sha256':hashlib.sha256(V2.read_bytes()).hexdigest()},
      'new_strategy':{'strategy_id':'ST_MTF_CONTROL_SHIFT_V3','version':'3.0.0','yaml_sha256':hashlib.sha256(V3.read_bytes()).hexdigest()},
      'single_changed_rule':{'name':'H1_SHIFT_SESSION_DATE_COUPLING','old_semantic':'V2 accepts a qualifying H1 shift when shift_age_h1_bars <= 24 closed H1 bars.','new_semantic':'In addition to V2 freshness, the H1 shift creation timestamp UTC calendar date must equal the active session date.'},
      'timestamp_date_semantics':{
        'timezone_authority':'UTC after the pinned HistData America/New_York -> UTC normalization; session assignment is UTC.',
        'active_session_date':'The UTC calendar date of the evaluation M15 candle/session observation. ASIAN_LONDON and LONDON_NEWYORK both use the date of the M15 bucket open; both windows remain same-date windows.',
        'session_boundaries':'ASIAN_LONDON [06:00,09:00) UTC; LONDON_NEWYORK [11:00,14:00) UTC. Start is inclusive and end is exclusive, unchanged from V2.',
        'midnight_behavior':'A timestamp exactly at 00:00 UTC belongs to that UTC date. No session crosses midnight, so no rollover exception exists.',
        'dst_behavior':'DST is resolved only while normalizing raw America/New_York timestamps to UTC. Session-date comparison itself is UTC and has no DST adjustment.',
        'equality':'shift UTC date == active session UTC date is accepted.',
        'before_session_start':'A shift before session start is accepted if it is on the same UTC calendar date; the existing in-session M15 creation rule remains unchanged.',
        'future_date':'A shift UTC date after the active session date is invalid and rejected.'
      },
      'structural_precheck':{'location_pass':170,'v2_structural_eligible':v2_eligible,'v3_structural_eligible':v3_eligible,'same_session_date':len(same),'prior_session_date':len(prior),'future_date_invalid':len(future),'cases': [{'analysis_unit_id':x['analysis_unit_id'],'session_date':datetime.fromisoformat(x['timestamp']).date().isoformat(),'shift_created_time':x['h1_shift_time'],'shift_date':datetime.fromisoformat(x['h1_shift_time']).date().isoformat(),'classification':'SAME_SESSION_DATE' if x in same else ('PRIOR_SESSION_DATE' if x in prior else 'FUTURE_DATE_INVALID')} for x in cases]},
      'development_window':{'warmup':['2017-01-01','2017-03-01'],'dev':['2017-03-01','2017-09-01'],'oos':['2017-09-01','2017-12-01'],'sealed_holdout':['2017-12-01','2018-01-01'],'holdout_touched':False},
      'symbols':['EURUSD','GBPUSD','USDJPY','XAUUSD'],
      'sessions':{'ASIAN_LONDON':['06:00','09:00'],'LONDON_NEWYORK':['11:00','14:00']},
      'dataset_lineage':'PR_10_HISTDATA_2017; same pinned raw hashes and causal M1->M15/H1/H4/D1 lineage as V2',
      'friction':'PR_10_APPROVED_FX_FRICTION; unchanged symbol-specific spread/slippage/commission model',
      'funnel_mapping':{'TRIGGER':['D1_H4_ALIGNED','FRESH_H4_POI','H4_POI_REACHED','TRUE_H1_CONTROL_SHIFT','LIQUIDITY_SWEEP'],'CONFIRMATION':['FVG_REBALANCE','M15_REFINEMENT','VALID_GEOMETRY'],'OUTCOME':['LIMIT_FILLED','LIMIT_EXPIRED','TP1','TP2','RUNNER_BE','FORCED_FLAT']},
      'gates':{'existing_edge_lab_dev_gates':True,'no_parameter_optimization':True,'earliest_valid_signal_wins':True,'one_entry_per_symbol_session_day':True,'post_signal_m1_limit_fill':True,'force_flat_utc':'21:00','no_overnight':True},
      'economic_replay_started':False,'oos_opened':False,'holdout_touched':False
    }
    (OUT/'v3_preregistration.json').write_text(json.dumps(prereg,indent=2)+'\n')
    report={'parent':'ST_MTF_CONTROL_SHIFT_V2@2.0.0','v3_id':'ST_MTF_CONTROL_SHIFT_V3@3.0.0','v3_hash':prereg['new_strategy']['yaml_sha256'],'only_rule_changed':'H1_SHIFT_SESSION_DATE_COUPLING','location_pass':170,'v2_structural_eligible':18,'v3_structural_eligible':v3_eligible,'same_session_date':len(same),'prior_session_date':len(prior),'future_date_invalid':len(future),'preregistered':True,'economic_replay_started':False,'oos_opened':False,'holdout_touched':False,'status':'V3_STRUCTURALLY_ZERO_BUT_PREREGISTERED' if v3_eligible==0 else 'READY_FOR_V3_DEV_REPLAY'}
    (OUT/'v3_hypothesis_report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
