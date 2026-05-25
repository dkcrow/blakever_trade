"""
使用示例 - Usage Examples
展示如何使用重构后的项目
"""

# ==================== 示例1：数据获取 ====================
def example_1_fetch_data():
    """示例1：获取股票数据"""
    print("=" * 50)
    print("示例1：数据获取")
    print("=" * 50)

    # 导入配置
    from config.settings import PATHS
    import os

    # 导入数据获取器
    from data.fetchers.base_fetcher import BaseFetcher

    # 创建数据获取器
    fetcher = BaseFetcher()

    # 获取股票数据
    data = fetcher.fetch_stock_data(
        code='sh600519',
        start_date='2020-01-01',
        end_date='2025-12-31'
    )

    # 保存数据
    output_path = os.path.join(PATHS['stock_data_dir'], 'sh600519.csv')
    data.to_csv(output_path, index=False)
    print(f"数据已保存到：{output_path}")


# ==================== 示例2：策略回测 ====================
def example_2_backtest():
    """示例2：策略回测"""
    print("=" * 50)
    print("示例2：策略回测")
    print("=" * 50)

    # 导入配置
    from config.settings import PATHS
    from config.strategy_params import STRATEGY_PARAMS
    import os

    # 导入策略
    from strategies.alpha.alpha_factor_backtest import AlphaFactorBacktest

    # 创建策略
    strategy = AlphaFactorBacktest(params=STRATEGY_PARAMS['alpha_factor'])

    # 加载数据
    data_path = os.path.join(PATHS['stock_data_dir'], 'sh600519.csv')
    data = strategy.load_data(data_path)

    # 运行回测
    results = strategy.run_backtest(data)

    # 保存结果
    output_path = os.path.join(PATHS['results_dir'], 'alpha_factor_results.html')
    results.to_html(output_path)
    print(f"回测结果已保存到：{output_path}")


# ==================== 示例3：策略优化 ====================
def example_3_optimization():
    """示例3：策略优化"""
    print("=" * 50)
    print("示例3：策略优化")
    print("=" * 50)

    # 导入配置
    from config.settings import PATHS
    import os

    # 导入优化器
    from optimization.parameter.step_optimizer import StepOptimizer

    # 创建优化器
    optimizer = StepOptimizer()

    # 加载数据
    data_path = os.path.join(PATHS['stock_data_dir'], 'sh600519.csv')
    data = optimizer.load_data(data_path)

    # 运行优化
    best_params = optimizer.optimize(data)

    # 保存结果
    output_path = os.path.join(PATHS['results_dir'], 'optimization_results.json')
    import json
    with open(output_path, 'w') as f:
        json.dump(best_params, f, indent=4)
    print(f"优化结果已保存到：{output_path}")


# ==================== 示例4：生成报告 ====================
def example_4_generate_report():
    """示例4：生成报告"""
    print("=" * 50)
    print("示例4：生成报告")
    print("=" * 50)

    # 导入配置
    from config.settings import PATHS
    import os

    # 导入报告生成器
    from reporting.html_reporter import HTMLReporter

    # 创建报告生成器
    reporter = HTMLReporter()

    # 加载回测结果
    results_path = os.path.join(PATHS['results_dir'], 'alpha_factor_results.html')
    results = reporter.load_results(results_path)

    # 生成报告
    report_path = os.path.join(PATHS['report_dir'], 'backtest_report.html')
    reporter.generate_report(results, output_path=report_path)
    print(f"报告已保存到：{report_path}")


# ==================== 主函数 ====================
def main():
    """主函数"""
    print("Blakever Trade - 使用示例")
    print("=" * 50)

    # 运行示例
    # example_1_fetch_data()
    # example_2_backtest()
    # example_3_optimization()
    # example_4_generate_report()

    print("请根据需要取消注释并运行相应的示例")


if __name__ == '__main__':
    main()
