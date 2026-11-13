// DATA EXPORT SCRIPT — read-only, no trading. Not part of the V2 strategy identity.
// Exports M5 bars [InpFromServer, InpToServer) and terminal/symbol facts for the dataset manifest.
// Output goes to the terminal COMMON files folder. Records NO credentials (no login number).
#property script_show_inputs
#property strict
input string   InpSymbol     = "EURUSD-VIP";
input datetime InpFromServer = D'2025.11.01 00:00'; // include warm-up before the tester FromDate (>= 2 days)
input datetime InpToServer   = D'2026.09.01 00:00'; // exclusive; DEVELOPMENT ends 2026-08-31
input string   InpTag        = "EURUSD-VIP_M5_DEV";

void OnStart()
{
  if(!SymbolSelect(InpSymbol,true)){ Print("SYMBOL_NOT_FOUND ",InpSymbol); return; }
  MqlRates r[]; ArraySetAsSeries(r,false);
  int n=-1;
  for(int k=0;k<20;k++){ n=CopyRates(InpSymbol,PERIOD_M5,InpFromServer,InpToServer-1,r); if(n>0) break; Sleep(1000); }
  if(n<=0){ Print("COPYRATES_FAILED err=",GetLastError()); return; }
  int dg=(int)SymbolInfoInteger(InpSymbol,SYMBOL_DIGITS);
  int h=FileOpen("bars_"+InpTag+".csv",FILE_WRITE|FILE_COMMON|FILE_ANSI|FILE_TXT);
  if(h==INVALID_HANDLE){ Print("FILE_OPEN_FAILED ",GetLastError()); return; }
  FileWriteString(h,"time_server_open,open,high,low,close,tick_volume,spread_points\n");
  for(int i=0;i<n;i++)
    FileWriteString(h,TimeToString(r[i].time,TIME_DATE|TIME_MINUTES)+","+DoubleToString(r[i].open,dg)+","+DoubleToString(r[i].high,dg)+","
      +DoubleToString(r[i].low,dg)+","+DoubleToString(r[i].close,dg)+","+(string)r[i].tick_volume+","+(string)r[i].spread+"\n");
  FileClose(h);
  int g=FileOpen("facts_"+InpTag+".txt",FILE_WRITE|FILE_COMMON|FILE_ANSI|FILE_TXT);
  FileWriteString(g,"company="+AccountInfoString(ACCOUNT_COMPANY)+"\n");
  FileWriteString(g,"server="+AccountInfoString(ACCOUNT_SERVER)+"\n");
  FileWriteString(g,"account_trade_mode="+(string)AccountInfoInteger(ACCOUNT_TRADE_MODE)+" (0=demo,1=contest,2=real)\n");
  FileWriteString(g,"terminal_build="+(string)TerminalInfoInteger(TERMINAL_BUILD)+"\n");
  FileWriteString(g,"terminal_name="+TerminalInfoString(TERMINAL_NAME)+"\n");
  FileWriteString(g,"symbol="+InpSymbol+"\n");
  FileWriteString(g,"digits="+(string)dg+"\n");
  FileWriteString(g,"point="+DoubleToString(SymbolInfoDouble(InpSymbol,SYMBOL_POINT),dg+2)+"\n");
  FileWriteString(g,"contract_size="+DoubleToString(SymbolInfoDouble(InpSymbol,SYMBOL_TRADE_CONTRACT_SIZE),2)+"\n");
  FileWriteString(g,"symbol_path="+SymbolInfoString(InpSymbol,SYMBOL_PATH)+"\n");
  FileWriteString(g,"symbol_description="+SymbolInfoString(InpSymbol,SYMBOL_DESCRIPTION)+"\n");
  FileWriteString(g,"server_time_now="+TimeToString(TimeTradeServer(),TIME_DATE|TIME_SECONDS)+"\n");
  FileWriteString(g,"gmt_now="+TimeToString(TimeGMT(),TIME_DATE|TIME_SECONDS)+"\n");
  FileWriteString(g,"server_minus_gmt_seconds_now="+(string)((long)TimeTradeServer()-(long)TimeGMT())+" (current only; DST rule must be documented separately)\n");
  FileWriteString(g,"bars_exported="+(string)n+"\n");
  FileWriteString(g,"first_bar="+TimeToString(r[0].time,TIME_DATE|TIME_MINUTES)+"\n");
  FileWriteString(g,"last_bar="+TimeToString(r[n-1].time,TIME_DATE|TIME_MINUTES)+"\n");
  FileClose(g);
  PrintFormat("EXPORT_DONE bars=%d first=%s last=%s",n,TimeToString(r[0].time),TimeToString(r[n-1].time));
}
