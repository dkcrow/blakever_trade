
# 策略: Main
# 来源: multi:google_github
# 自动生成时间: 2026-04-30 20:18:23

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "Main"
STRATEGY_TYPE = "其他"
STRATEGY_PARAMS = {}

import re
import pandas as pd
import datetime
import talib
import yfinance as yf
import time
import threading
import os
from collections import deque



SYMBOLS = ["^NSEBANK","^NSEI","INFY.NS","RELIANCE.NS","TATAMOTORS.NS","ICICIBANK.NS","SBIN.NS"]

DATA_RANGE = "5y"
DATA_INTERVAL = "1d"
LOOKBACK_PERIOD = 30
ENTER_TRIGGER_PERCENTAGE = 14
EXIT_TRIGGER_PERCENTAGE = 10
TARGET_PERCENTAGE = 14

Trades = []

# Cache data from downloads folder, else download from Yahoo Finance
def get_data(symbol='SBIN.NS', data_range='30d', data_interval='1m'):
        name = symbol+"-"+data_range+"-"+data_interval+".csv"
        downloads_dir = os.path.join(os.getcwd(),"downloads")
        if name in os.listdir(downloads_dir):
                data = pd.read_csv(os.path.join(downloads_dir,name))
                return data

        data = yf.download(tickers=[symbol],period = data_range,interval =data_interval)

        data['Date'] = pd.to_datetime(data.index.values).date
        data['Date'] = [d.strftime("%y-%m-%d") for d in data['Date'].values]

        data=data.drop(['Open','Close',"High","Low",'Volume'],axis=1)
        data.to_csv(os.path.join(os.path.join(os.getcwd(),"downloads"),name+".csv"))
        return data


def Sliding_window_min(arr, k):
        n=len(arr)
        Qi = deque()
        ans=[]
        for i in range(k):
                while Qi and arr[i] <= arr[Qi[-1]] :
                        Qi.pop()
                Qi.append(i)
                ans.append(Qi[0])
        for i in range(k, n):
                while Qi and Qi[0] <= i-k:
                        Qi.popleft()
                while Qi and arr[i] <= arr[Qi[-1]] :
                        Qi.pop()
                Qi.append(i)
                ans.append(Qi[0])
        return ans


def Sliding_window_max(arr, k):
        n=len(arr)
        Qi = deque()
        ans=[]
        for i in range(k):
                while Qi and arr[i] >= arr[Qi[-1]] :
                        Qi.pop()
                Qi.append(i)
                ans.append(Qi[0])
        for i in range(k, n):
                while Qi and Qi[0] <= i-k:
                        Qi.popleft()
                while Qi and arr[i] >= arr[Qi[-1]] :
                        Qi.pop()
                Qi.append(i)
                ans.append(Qi[0])
        return ans


def backtest_trend_follow_strategy(symbol):
        # print("Thread Started For Symbol - "+symbol)
        global ENTER_TRIGGER_PERCENTAGE,EXIT_TRIGGER_PERCENTAGE,TARGET_PERCENTAGE
        data = get_data(symbol=symbol,data_range=DATA_RANGE,data_interval=DATA_INTERVAL)

        global Trades
        nrows = data.shape[0]
        state = 0
        trade_details = {}

        closing_vals = []
        for index,row in data.iterrows():
               closing_vals.append(row["Adj Close"]) 

        lookback_min_index = Sliding_window_min(closing_vals,LOOKBACK_PERIOD)
        lookback_max_index = Sliding_window_max(closing_vals,LOOKBACK_PERIOD)

        for i in range(LOOKBACK_PERIOD,nrows):
                curr_row = data.iloc[i]
                prev_min_row = data.iloc[lookback_min_index[i]]
                prev_max_row = data.iloc[lookback_max_index[i]]
                
                if state==0:
                        if curr_row["Adj Close"]>=prev_min_row["Adj Close"]*(100+ENTER_TRIGGER_PERCENTAGE)/100:
                                #Long on STOCK
                                trade_details["symbol"]=symbol
                                trade_details["type"]="LONG"
                                trade_details["Buy Price"]=curr_row["Adj Close"]
                                trade_details["Buy Date"]=curr_row["Date"]
                                state=1

                        elif curr_row["Adj Close"]<=prev_max_row["Adj Close"]*(100-ENTER_TRIGGER_PERCENTAGE)/100:
                                #Short Stock
                                trade_details["symbol"]=symbol
                                trade_details["type"]="SHORT"
                                trade_details["Sell Price"]=curr_row["Adj Close"]
                                trade_details["Sell Date"]=curr_row["Date"]
                                state=2

                elif state==1:
                        if curr_row["Adj Close"]<=prev_max_row["Adj Close"]*(100-EXIT_TRIGGER_PERCENTAGE)/100 \
                                or curr_row["Adj Close"]>=trade_details["Buy Price"]*(100+TARGET_PERCENTAGE)/100:
                                #Exit long position
                                trade_details["Sell Price"]=curr_row["Adj Close"]
                                trade_details["Sell Date"]=curr_row["Date"]
                                Trades.append(trade_details)
                                trade_details={}
                                state=0

                elif state==2:
                        if curr_row["Adj Close"]>=prev_min_row["Adj Close"]*(100+EXIT_TRIGGER_PERCENTAGE)/100 \
                                or curr_row["Adj Close"]<=trade_details["Sell Price"]*(100-TARGET_PERCENTAGE)/100:
                                #Exit long position
                                trade_details["Buy Price"]=curr_row["Adj Close"]
                                trade_details["Buy Date"]=curr_row["Date"]
                                Trades.append(trade_details)
                                trade_details={}
                                state=0

                

def generate_results():
        global Trades
        # print("\n\nPrinting Results")
        print(ENTER_TRIGGER_PERCENTAGE,EXIT_TRIGGER_PERCENTAGE,TARGET_PERCENTAGE)
        num_long_trades = 0
        num_short_trades = 0
        total_profit_percent=0

        for trade in Trades:
                profit = 0
                if trade["type"]=="LONG":
                        profit = ((trade["Sell Price"]-trade["Buy Price"])/trade["Buy Price"])*100
                        num_long_trades+=1
                        total_profit_percent+=profit
                else:
                        profit = ((trade["Buy Price"]-trade["Sell Price"])/trade["Sell Price"])*100
                        num_short_trades+=1
                        total_profit_percent+=profit
                trade["Profit (in %)"]=profit

        results = pd.DataFrame(Trades)

        if results.shape[0]==0:
                print("No Trades Executed")
                return 0
        else:
                av_profit = results["Profit (in %)"].sum()/results.shape[0]
                print(results)
                print("Avg Profit : "+str(av_profit)+"%")
                print("Total number of trades executed : "+str(results.shape[0]))
        print("\n")
        return av_profit

        
                

def main(arr=[]):
        if "downloads" not in os.listdir():
                os.mkdir("downloads")
        global ENTER_TRIGGER_PERCENTAGE,EXIT_TRIGGER_PERCENTAGE,TARGET_PERCENTAGE
        if len(arr):
                ENTER_TRIGGER_PERCENTAGE=arr[0]
                EXIT_TRIGGER_PERCENTAGE=arr[1]
                TARGET_PERCENTAGE=arr[2]
        global Trades
        Trades=[]
        threads=[]

        for symbol in SYMBOLS:
                t1 = threading.Thread(target=backtest_trend_follow_strategy(symbol),name=symbol)
                threads.append(t1)
                t1.start()

        for thread_ in threads:
                thread_.join()
        return generate_results()


main()
