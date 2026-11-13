// RESEARCH PROTOTYPE ONLY — NOT THE CANONICAL PROJECT EA.
// No verified edge. Tester-only. Disabled orders by default.
#property strict
#property version "2.00"
#include <Trade/Trade.mqh>
CTrade trade;
input bool InpEnableTesterOrders=false; // V2: never permits orders (hard-disabled)
input bool InpRequireVerifiedNewsCalendar=true; // V2 policy declaration, not a live calendar integration
input bool InpRequireApprovedDataAdmission=true; // V2 policy declaration, not an automated D0 verifier
input double InpFixedLots=0.01;
input int InpStopPoints=300;
input int InpTargetPoints=450;
input int InpMaxSpreadPoints=30;
input int InpLookbackBars=24;
input int InpMagicNumber=114498531;
input int InpFastMAPeriod=12;
input int InpSlowMAPeriod=36;
datetime lastbar=0;
int OnInit()
{
  if(!MQLInfoInteger(MQL_TESTER)) { Print("TESTER ONLY — refusing non-tester execution"); return INIT_FAILED; }
  if(InpFixedLots<=0 || InpStopPoints<=0 || InpTargetPoints<=0 || InpLookbackBars<5 || InpFastMAPeriod<2 || InpSlowMAPeriod<=InpFastMAPeriod) return INIT_PARAMETERS_INCORRECT;
  trade.SetExpertMagicNumber((ulong)InpMagicNumber);
  return INIT_SUCCEEDED;
}
bool HavePosition()
{
  for(int i=PositionsTotal()-1;i>=0;i--)
  {
    ulong t=PositionGetTicket(i);
    if(t>0 && PositionSelectByTicket(t) && PositionGetString(POSITION_SYMBOL)==_Symbol && PositionGetInteger(POSITION_MAGIC)==InpMagicNumber) return true;
  }
  return false;
}
int Signal()
{
  MqlRates r[]; ArraySetAsSeries(r,true);
  int need=MathMax(InpLookbackBars+5,InpSlowMAPeriod+5);
  if(CopyRates(_Symbol,PERIOD_M5,0,need,r)<need) return 0;
  double hi=r[2].high,lo=r[2].low;
  for(int i=3;i<InpLookbackBars+2;i++){hi=MathMax(hi,r[i].high);lo=MathMin(lo,r[i].low);}
  // All decisions use completed bars (indices >=1), never the forming bar.
  // Simplified sweep + trend proxy. This is NOT an LSMC implementation.
  double fast=0,slow=0;
  for(int i=1;i<=InpFastMAPeriod;i++) fast+=r[i].close;
  for(int i=1;i<=InpSlowMAPeriod;i++) slow+=r[i].close;
  fast/=InpFastMAPeriod;slow/=InpSlowMAPeriod;
  if(fast>slow && r[1].low<lo && r[1].close>lo) return 1;
  if(fast<slow && r[1].high>hi && r[1].close<hi) return -1;
  return 0;
}
void OnTick()
{
  datetime t=iTime(_Symbol,PERIOD_M5,0);
  if(t<=0 || t==lastbar) return;
  lastbar=t;
  int signal=Signal();
  if(signal==0) return;
  PrintFormat("RESEARCH_SIGNAL,%s,%s,%d,%s",_Symbol,TimeToString(t,TIME_DATE|TIME_MINUTES),signal,"NO_EDGE_CLAIM");
  if(!InpEnableTesterOrders || HavePosition()) return;
  // V2 fail-closed: this prototype has no authenticated news feed, approved D0 gate,
  // broker-cost proof, or canonical PortfolioGuard integration. NEVER place orders.
  Print("V2_ORDER_BLOCKED_UNVERIFIED_GATES");
  return;
  MqlTick tick; if(!SymbolInfoTick(_Symbol,tick)) return;
  double point=SymbolInfoDouble(_Symbol,SYMBOL_POINT);
  if(point<=0 || tick.ask<=tick.bid || (tick.ask-tick.bid)/point>InpMaxSpreadPoints) return;
  double volume_min=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
  double volume_step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
  double volume_max=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
  if(volume_step<=0 || InpFixedLots<volume_min || InpFixedLots>volume_max) return;
  double steps=MathRound((InpFixedLots-volume_min)/volume_step);
  if(MathAbs((volume_min+steps*volume_step)-InpFixedLots)>0.0000001) return;
  double entry=(signal>0?tick.ask:tick.bid);
  double sl=NormalizeDouble(entry-signal*InpStopPoints*point,_Digits);
  double tp=NormalizeDouble(entry+signal*InpTargetPoints*point,_Digits);
  int stops=(int)SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL);
  if(InpStopPoints<=stops || InpTargetPoints<=stops) return;
  trade.SetDeviationInPoints(10);
  bool sent=(signal>0?trade.Buy(InpFixedLots,_Symbol,0,sl,tp,"RESEARCH_ONLY"):trade.Sell(InpFixedLots,_Symbol,0,sl,tp,"RESEARCH_ONLY"));
  if(!sent) PrintFormat("ORDER_REJECTED,%d,%s",trade.ResultRetcode(),trade.ResultRetcodeDescription());
}
