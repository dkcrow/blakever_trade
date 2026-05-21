@echo off
chcp 65001 >nul
cd /d "C:\Users\blakehao\.qclaw\workspace\strategy_arena"
python "七星拉普拉斯高斯_backtrader.py" > backtest_output.txt 2>&1
echo.
echo 回测完成！输出已保存到 backtest_output.txt
pause
