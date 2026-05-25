        # 获取当日数据（用最低价判断止损，收盘价计算盈亏）
        df_current = load_etf_data(current_etf)
        if df_current is not None:
            daily_data = df_current[df_current.index.date == current_date.date()]
            if len(daily_data) > 0:
                current_price = daily_data['close'].iloc[0]  # 收盘价用于盈亏计算
                low_price = daily_data['low'].iloc[0]      # 最低价用于止损判断
            else:
                current_price = top['price']
                low_price = top['price']
        else:
            current_price = top['price']
            low_price = top['price']
        
        entry_price = positions[current_etf]['entry_price']
        max_price = positions[current_etf]['max_price']
        pnl_pct = (current_price - entry_price) / entry_price * 100
        
        # 更新最高价
        if current_price > max_price:
            positions[current_etf]['max_price'] = current_price
        
        # 检查止损
        stop_loss_reason = None
        stop_price = entry_price * 0.92  # 止损线
        
        # 硬止损 -8%（用最低价判断，按止损线卖出）
        if low_price <= stop_price:
            stop_loss_reason = '硬止损（-8%）'
            sell_price = stop_price  # 按止损线卖出，不是收盘价
            pnl_pct = (sell_price - entry_price) / entry_price * 100
        # 盈利保护：盈利>5%且回撤>5%
        elif pnl_pct > 5 and current_price < max_price * 0.95:
            stop_loss_reason = '盈利保护（回撤>5%）'
            sell_price = current_price  # 盈利保护按收盘价卖出
        
        # 检查是否换仓
        need_switch = (current_etf != top['etf'])
        
        # 优先止损，其次换仓
        if stop_loss_reason:
            # 止损卖出（用止损线价格）
            trade_id += 1
            trades.append({
                "id": trade_id,
                "etf": current_etf,
                "name": positions[current_etf]['name'],
                "action": "卖出",
                "date": current_date.strftime('%Y-%m-%d'),
                "price": round(sell_price, 3),
                "reason": stop_loss_reason,
                "pnl_pct": round(pnl_pct, 1)
            })
            print(f"{current_date.strftime('%Y-%m-%d')}: 卖出 {current_etf} {positions[current_etf]['name']} @ {sell_price:.3f} (止损: {pnl_pct:.1f}%) - {stop_loss_reason}")
            positions.pop(current_etf)
            
            # 止损后冷却期：当天不买入
            print(f"{current_date.strftime('%Y-%m-%d')}: 止损后冷却，不买入")
            last_top_etf = None  # 清空last_top_etf，防止重复买入
            
        elif need_switch:
