
# 策略: Data Manager
# 来源: multi:google_github
# 类型: 熊市策略
# 自动生成时间: 2026-04-30 20:15:38

# Windows 兼容：UTF-8 输出
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "Data Manager"
STRATEGY_TYPE = "其他"
STRATEGY_PARAMS = {}

from src.data.data_loader import BLP
from datetime import datetime
from utils.utilities import Utilities

class DataManager:
    
    @staticmethod
    def get_historical_compositions(start_date: datetime, end_date: datetime, ticker: str, frequency: str, rebalance_at: str) -> dict:
        """
        Obtient les compositions historiques pour un ticker donné entre deux dates.

        Paramètres:
            start_date (datetime): La date de début.
            end_date (datetime): La date de fin.
            ticker (str): Le ticker de l'actif.
            frequency (str): La fréquence de rebalancement.
            rebalance_at (str): Le moment du rebalancement.

        Retourne:
            dict: Un dictionnaire où les clés sont les dates de rebalancement et les valeurs sont des listes de tickers.
        """
        strFields = ["INDX_MWEIGHT_HIST"]
        blp = BLP()
        
        # Création du calendrier de rebalancement
        rebalancing_dates = Utilities.create_rebalancing_calendar(start_date, end_date, frequency, rebalance_at)
        composition_par_date = {}

        # Obtention des compositions pour chaque date de rebalancement
        for date in rebalancing_dates:
            str_date = date.strftime('%Y%m%d')
            compo = blp.bds(strSecurity=[ticker], strFields=strFields, strOverrideField="END_DATE_OVERRIDE", strOverrideValue=str_date)
            list_tickers = compo[strFields[0]].index.tolist()
            composition_par_date[date] = [ticker.split(' ')[0] + ' US Equity' for ticker in list_tickers]
            
        return composition_par_date
        
    @staticmethod
    def get_historical_prices(start_date: datetime, end_date: datetime, tickers: list[str], curr: str) -> tuple[dict, list[str]]:
        """
        Obtient les prix historiques pour une liste de tickers entre deux dates.

        Paramètres:
            start_date (datetime): La date de début.
            end_date (datetime): La date de fin.
            tickers (list[str]): La liste des tickers.
            curr (str): La devise.

        Retourne:
            tuple: Un tuple contenant un dictionnaire des données de marché globales et une liste des tickers sans données.
        """
        blp = BLP()
        global_market_data = {}
        tickers_a_supp = []
        
        # Obtention des prix historiques pour chaque ticker
        for ticker in tickers:
            try:
                historical_prices = blp.bdh(strSecurity=[ticker], strFields=["PX_LAST"], startdate=start_date, enddate=end_date, curr=curr, fill="NIL_VALUE")
                historical_prices["PX_LAST"] = historical_prices["PX_LAST"].sort_index(ascending=True)
                
                if not historical_prices["PX_LAST"].empty:
                    global_market_data[ticker] = historical_prices["PX_LAST"]
                else:
                    tickers_a_supp.append(ticker)
                    
            except Exception as e:
                print(f"Erreur lors du traitement du ticker {ticker}: {str(e)}")
        
        return global_market_data, tickers_a_supp
    
    @staticmethod
    def fetch_backtest_data(start_date: datetime, end_date: datetime, ticker: str, curr: str, frequency: str, rebalance_at: str, sign: int) -> tuple[dict, dict]:
        """
        Récupère les données nécessaires pour effectuer un backtest.

        Paramètres:
            start_date (datetime): La date de début.
            end_date (datetime): La date de fin.
            ticker (str): Le ticker de l'actif.
            curr (str): La devise.
            frequency (str): La fréquence de rebalancement.
            rebalance_at (str): Le moment du rebalancement.
            sign (int): Indicateur de direction du rebalancement.

        Retourne:
            tuple: Un tuple contenant les compositions historiques par date et les données de marché globales.
        """
        # Obtention des compositions historiques
        composition_par_date = DataManager.get_historical_compositions(start_date, end_date, ticker, frequency, rebalance_at)
    
        tickers_uniques = list({ticker for composition in composition_par_date.values() for ticker in composition})
        start_date = Utilities.get_rebalancing_date(start_date, sign, frequency, rebalance_at, step=-6)   
       
        global_market_data, tickers_a_supp = DataManager.get_historical_prices(start_date, end_date, tickers_uniques, curr)
        
        # Suppression des tickers sans données
        composition_par_date = {date: [ticker for ticker in tickers if ticker not in tickers_a_supp] for date, tickers in composition_par_date.items()}    
        
        return composition_par_date, global_market_data     
    

    @staticmethod
    def fetch_other_US_data(start_date: datetime, end_date: datetime, ticker: str, risk_free_rate_ticker: str, curr: str) -> dict:
        """
        Récupère d'autres données de marché américaines pour une période donnée.

        Paramètres:
            start_date (datetime): La date de début.
            end_date (datetime): La date de fin.
            ticker (str): Le ticker de l'actif.
            risk_free_rate_ticker (str): Le ticker du taux sans risque.
            curr (str): La devise.

        Retourne:
            dict: Un dictionnaire des autres données de marché américaines.
        """
        tickers = ["USRINDEX Index", risk_free_rate_ticker]
        tickers.append(ticker)
        other_US_data = {}
        
        # Obtention des données de marché pour les tickers spécifiés
        other_US_data = DataManager.get_historical_prices(start_date, end_date, tickers, curr)
        
        return other_US_data
