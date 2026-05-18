
# 策略: Portfolio Builder
# 来源: multi:github
# 类型: 熊市策略
# 自动生成时间: 2026-04-30 20:09:31

# Windows 兼容：UTF-8 输出
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

import numpy as np
import pandas as pd
import talib

STRATEGY_NAME = "Portfolio Builder"
STRATEGY_TYPE = "其他"
STRATEGY_PARAMS = {}

import pandas as pd
import numpy as np

class PortfolioBuilder:
    """
    Build portfolios based on factor scores
    
    Strategy: For each factor, select top N stocks
    Then create equal-weight portfolio
    """
    
    def __init__(self, factor_scores):
        """
        Args:
            factor_scores: DataFrame with factor scores for each stock
        """
        self.factors = factor_scores
        
    def build_factor_portfolio(self, factor_name, top_n=10):
        """
        Build a portfolio of top N stocks for a given factor
        
        Args:
            factor_name: Which factor to use ('value', 'momentum', etc.)
            top_n: How many stocks to include
            
        Returns:
            Series with portfolio weights (sums to 1.0)
        """
        # Get top N stocks for this factor
        top_stocks = self.factors.nlargest(top_n, factor_name).index
        
        # Equal weight each stock
        weights = pd.Series(index=top_stocks, data=1.0/top_n)
        
        return weights
    
    def build_all_portfolios(self, top_n=10):
        """
        Build portfolios for all factors
        
        Args:
            top_n: Number of stocks in each portfolio
            
        Returns:
            Dictionary of {factor_name: weights}
        """
        portfolios = {}
        
        factor_names = ['value', 'momentum', 'quality', 'size', 'low_vol', 'composite']
        
        for factor in factor_names:
            portfolios[factor] = self.build_factor_portfolio(factor, top_n)
            print(f"{factor.capitalize()} portfolio: {len(portfolios[factor])} stocks")
        
        return portfolios
    
    def get_portfolio_stocks(self, portfolios):
        """
        Get list of all unique stocks across all portfolios
        
        Args:
            portfolios: Dictionary of portfolios
            
        Returns:
            List of unique tickers
        """
        all_stocks = set()
        for portfolio in portfolios.values():
            all_stocks.update(portfolio.index)
        
        return list(all_stocks)


# Test the code
if __name__ == "__main__":
    # Load factor scores
    factors = pd.read_csv('factor_scores.csv', index_col=0)
    
    # Build portfolios
    builder = PortfolioBuilder(factors)
    portfolios = builder.build_all_portfolios(top_n=10)
    
    print("\nPortfolio Summary:")
    for name, weights in portfolios.items():
        print(f"\n{name.upper()} Portfolio:")
        print(weights.sort_values(ascending=False))
    
    # Save portfolios
    portfolio_df = pd.DataFrame(portfolios).fillna(0)
    portfolio_df.to_csv('portfolio_weights.csv')
    print("\nPortfolios saved to portfolio_weights.csv")
