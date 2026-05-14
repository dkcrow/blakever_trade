#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, os, math, json, numpy as np, pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt, plotly.io as pio, plotly.graph_objects as go, warnings
warnings.filterwarnings('ignore')
from datetime import datetime, timedelta

def get_3y_heatmap_analysis():
    import plotly.express as px, plotly.subplots as sp, seaborn as sns
    base = os.path.join('/data/workspace', 'strategy_arena')
    
    # 载入回测结果
    with open(os.path.join(base, 'cn_3y_rerank_result.json')) as f:
        res = json.load(f)
    
    # 过滤有效结果
    has_results = [r for r in res['rankings'] if 'annual_return' in r and r['annual_return']]
    if not has_results:
        return "无有效回测结果"
    
    strategies = {
        r['strategy_name']: (
            r['annual_return'], r['max_drawdown'], r['sharpe'],
            r['profit_factor'], r['win_rate'], r['monthly_positive_rate']
        ) for r in has_results
    }
    
    fig = sp.make_subplots(
        rows=2, cols=3,
        subplot_titles=(
            '①年化vs回撤二维散点', '②最佳年化＞20%主流策略聚焦',
            '③盈亏比vs胜率均衡视角', '④夏普vs月度正率稳定性',
            '⑤回撤vs胜率平衡考验', '⑥策略聚类关系热力图'
        ),
        specs=[[{}, {}, {}], [{}, {}, {}]]
    )
    
    # 准备数据
    names = list(strategies.keys())
    short_names = [n[:15]+'…' if len(n)>15 else n for n in names]
    ann_vals = [strategies[n][0] for n in names]
    dd_vals = [strategies[n][1] for n in names]
    sharpe_vals = [strategies[n][2] for n in names]
    pf_vals = [strategies[n][3] for n in names]
    win_vals = [strategies[n][4] for n in names]
    mon_vals = [strategies[n][5]*100 for n in names]
    
    # ① 年化vs回撤散点
    colors = ['red' if dd>30 else 'orange' if dd>20 else 'green' if dd>0 else 'gray' for dd in dd_vals]
    sizes = [ann*0.03 for ann in ann_vals]
    marker_text = [f'{short_names[i]}<br>{ann_vals[i]:.1f}%/{dd_vals[i]:.1f}%' for i in range(len(names))]
    fig.add_trace(
        go.Scatter(x=dd_vals, y=ann_vals, mode='markers+text',
                   text=short_names, textposition='top center',
                   marker=dict(size=sizes, color=colors, line=dict(width=1,color='darkgray')),
                   hovertemplate="策略:%{text}<br>回撤:%{x:.1f}%<br>年化:%{y:.1f}%<extra></extra>"),
        row=1, col=1
    )
    
    # 基准位置线条
    fig.add_hline(y=10, line=dict(color='lightgray', dash='dot'), row=1, col=1)
    fig.add_vline(x=15, line=dict(color='lightgray', dash='dot'), row=1, col=1)
    fig.update_xaxes(title_text="最大回撤(%) →", row=1, col=1)
    fig.update_yaxes(title_text="←年化收益(%)", row=1, col=1)
    
    # ② 聚焦年化＞20%策略
    high_ann_idx = [i for i,a in enumerate(ann_vals) if a>=20]
    if high_ann_idx:
        high_names = [names[i] for i in high_ann_idx]
        high_shorts = [short_names[i] for i in high_ann_idx]
        high_dd = [dd_vals[i] for i in high_ann_idx]
        high_sh = [sharpe_vals[i] for i in high_ann_idx]
        fig.add_trace(
            go.Bar(x=high_shorts, y=high_dd, name='回撤%', marker_color='red', opacity=0.7),
            row=1, col=2
        )
        fig.add_trace(
            go.Scatter(x=high_shorts, y=[0]*len(high_shorts), mode='none', name=''),
            row=1, col=2
        )
        fig.update_xaxes(title_text="策略", row=1, col=2, tickangle=45)
        fig.update_yaxes(title_text="回撤(%) →", row=1, col=2)
    
    # ③ 盈亏比vs胜率
    fig.add_trace(
        go.Scatter(x=win_vals, y=pf_vals, mode='markers',
                   marker=dict(size=[ann*0.025 for ann in ann_vals], color=dd_vals,
                               colorscale='RdYlGn_r', showscale=True,
                               colorbar=dict(title="回撤程度", thickness=15)),
                   text=short_names, hovertemplate="策略:%{text}<br>胜率:%{x:.1f}%<br>盈亏比:%{y:.2f}<extra></extra>"),
        row=1, col=3
    )
    fig.update_xaxes(title_text="胜率(%) →", row=1, col=3)
    fig.update_yaxes(title_text="←盈亏比", row=1, col=3)
    
    # ④ 夏普vs月度正率
    fig.add_trace(
        go.Scatter(x=mon_vals, y=sharpe_vals, mode='markers',
                   marker=dict(size=[ann*0.035 for ann in ann_vals], color=dd_vals,
                               colorscale='RdBu_r', showscale=False),
                   text=short_names, hovertemplate="策略:%{text}<br>月正率:%{x:.1f}%<br>夏普:%{y:.2f}<extra></extra>"),
        row=2, col=1
    )
    fig.update_xaxes(title_text="月度正率(%) →", row=2, col=1)
    fig.update_yaxes(title_text="←夏普比率", row=2, col=1)
    
    # ⑤ 回撤vs胜率
    fig.add_trace(
        go.Scatter(x=win_vals, y=dd_vals, mode='markers',
                   marker=dict(size=[ann*0.028 for ann in ann_vals], color=sharpe_vals,
                               colorscale='Viridis', showscale=True,
                               colorbar=dict(title="夏普", thickness=15)),
                   text=short_names, hovertemplate="策略:%{text}<br>胜率:%{x:.1f}%<br>回撤:%{y:.1f}%<extra></extra>"),
        row=2, col=2
    )
    fig.update_xaxes(title_text="胜率(%) →", row=2, col=2)
    fig.update_yaxes(title_text="←最大回撤(%)", row=2, col=2)
    
    # ⑥ 相关性热力图（标准化六维权重）
    dims = ['年化','夏普','回撤','盈亏比','胜率','月正']
    dim_weights = [7, 6, -8, 4, 5, 3]  # 价值取向
    zmat = []
    for i,d in enumerate(names):
        vals = strategies[d]
        normed = [
            math.log((vals[0]/15)+1)*dim_weights[0],  # 年化
            vals[2]*dim_weights[1],                  # 夏普
            -math.exp(-0.045*(vals[1]-10))*dim_weights[2],  # 回撤惩罚
            math.log(vals[3])*dim_weights[3],        # 盈亏比
            ((vals[4]-20)/40)*dim_weights[4] if vals[4]>20 else 0,  # 胜率
            (vals[5]*6)*dim_weights[5]              # 月正
        ]
        zmat.append(normed)
    zarr = np.array(zmat).T
    corr_arr = np.corrcoef(zarr)
    
    fig.add_trace(
        go.Heatmap(z=corr_arr, x=dims, y=dims, colorscale='RdBu_r',
                   zmid=0, hoverongaps=False,
                   colorbar=dict(title="相关系数", thickness=15)),
        row=2, col=3
    )
    fig.update_xaxes(title_text="维度指标", row=2, col=3, tickangle=45)
    fig.update_yaxes(title_text="←维度指标", row=2, col=3)
    
    # 布局完善
    fig.update_layout(
        title=f" 🧠十大策略近3年回撤逻辑矩阵 | {res['backtest_period']}\n❋七星巨降主因：32.55%回撤吞噬212%历史优势，其它稳健策略反而崛起",
        height=1000, width=1450,
        showlegend=False,
        font_size=10,
        title_font_size=16,
        margin=dict(t=100, b=30, l=30, r=30)
    )
    
    out_path = os.path.join(base, 'cn_3y_analysis_matrix.html')
    fig.write_html(out_path, include_plotlyjs='cdn', full_html=False)
    return out_path

if __name__ == '__main__':
    path = get_3y_heatmap_analysis()
    print(f"✅ 维度矩阵可视化已保存: {path}")
