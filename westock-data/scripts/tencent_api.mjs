#!/usr/bin/env node
/**
 * 腾讯行情 API 轻量封装 - 替代 galileo SDK 的 SSE 通道
 * 直接调用腾讯公开接口，无需 galileo 依赖
 */

import https from 'https';

function httpGet(url) {
  return new Promise((resolve, reject) => {
    https.get(url, { headers: { 'User-Agent': 'Mozilla/5.0' } }, (res) => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => resolve(data));
    }).on('error', reject);
  });
}

// 实时行情
async function quote(codes) {
  const url = `https://qt.gtimg.cn/q=${codes}`;
  const raw = await httpGet(url);
  const result = {};
  raw.split(';').filter(l => l.trim()).forEach(line => {
    const m = line.match(/v_(\w+)="(.+)"/);
    if (m) {
      const p = m[2].split('~');
      if (p.length > 40) {
        result[m[1]] = {
          code: m[1], name: p[1], price: +p[3], lastClose: +p[4],
          open: +p[5], volume: +p[6], amount: +p[37] || p[6],
          high: +p[33] || +p[3], low: +p[34] || +p[3],
          change: +p[31], changePct: +p[32], turnover: +p[38],
          pe: +p[39], pb: +p[46] || 0, totalMarketCap: +p[45] || 0,
          circulationMarketCap: +p[44] || 0
        };
      }
    }
  });
  return result;
}

// K线数据
async function kline(code, period = 'day', count = 60, fq = 'qfq') {
  // 周期映射: day -> qfqday/hfqday, week -> qfqweek, month -> qfqmonth
  const key = fq === 'hfq' ? `hfq${period}` : (fq === 'qfq' ? `qfq${period}` : period);
  const url = `https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=${code},${period},,,${count},${fq}`;
  const raw = await httpGet(url);
  const json = JSON.parse(raw);
  // json.data 的 key 可能是 sh600519 或 market+code
  const stock = json.data[code] || Object.values(json.data)[0];
  if (!stock) return [];
  // 按优先级查找 key: qfqday > day
  const nodes = stock[key] || stock[period] || stock['qfqday'] || stock['day'] || [];
  return nodes.map(n => ({
    date: n[0], open: +n[1], close: +n[2], high: +n[3], low: +n[4],
    volume: +n[5] || 0, amount: +n[6] || 0
  }));
}

// 搜索
async function search(keyword) {
  const url = `https://smartbox.gtimg.cn/s3/?q=${encodeURIComponent(keyword)}&t=all`;
  const raw = await httpGet(url);
  const results = [];
  const lines = raw.split(';');
  for (const line of lines) {
    const m = line.match(/v_hint="(.+)"/);
    if (m) {
      const items = m[1].split('^');
      for (const item of items) {
        const parts = item.split('~');
        if (parts.length >= 3) {
          results.push({ code: parts[0], name: parts[1], type: parts[2] });
        }
      }
    }
  }
  return results;
}

// CLI 入口
const args = process.argv.slice(2);
const cmd = args[0];
try {
  if (cmd === 'quote') {
    const r = await quote(args[1]);
    console.log(JSON.stringify({ success: true, data: r }, null, 2));
  } else if (cmd === 'kline') {
    const r = await kline(args[1], args[2] || 'day', +args[3] || 60, args[4] || 'qfq');
    console.log(JSON.stringify({ success: true, data: { code: args[1], period: args[2] || 'day', nodes: r } }, null, 2));
  } else if (cmd === 'search') {
    const r = await search(args[1]);
    console.log(JSON.stringify({ success: true, data: r }, null, 2));
  } else {
    console.log('Usage: tencent_api.mjs <quote|kline|search> <args...>');
  }
} catch (e) {
  console.log(JSON.stringify({ success: false, error: e.message }));
}
