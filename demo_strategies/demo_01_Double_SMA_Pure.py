"""
==== Double-SMA 双均线策略 ====
类通达信伪代码：
M1 = 5;
M2 = 10;
MA_FAST = MA(CLOSE,M1);
MA_SLOW = MA(CLOSE,M2);
GOLD = CROSS(MA_FAST, MA_SLOW);
DEATH = CROSS(MA_SLOW, MA_FAST);
BUY(GOLD, OPEN(T+1));
SELL(DEATH, OPEN(T+1));

策略信号来源：
T-1日收盘	MA(close,5) <= MA(close,10)
T日收盘		MA(close,5) > MA(close,10) 形成金叉 发出买入信号
T+1日开盘	以 open 开盘价全仓买入

信号来源为 close 收盘
交易操作和点位为 open 开盘
P-M-C-T 均以 open 为参考

【暂时不考虑做空 只考虑不持仓和持有多仓 两种情况】  ###################################

参数设置：
默认双均线指标周期参数对 MA(5, 10) 后续按照多进程/梯度下降算法 进行参数优化
初始资金 = 100000
手续费 = 2 / 1000 * 交易金额
最低成交量（股数） = 100

"""


import numpy as np
import pandas as pd
pd.set_option('expand_frame_repr', False)
pd.set_option('display.max_rows', 20000)


period_fast = 20
period_slow = 120


df = pd.read_csv(filepath_or_buffer=r'../data_example/hs300etf_day.csv',
				 usecols=['date', 'code', 'open', 'close'],
				 parse_dates=['date'],
				 index_col=['date'],
				 )

df['open_pct_change'] = df['open'].pct_change().fillna(0)


df['ma_fast'] = df['close'].rolling(window=period_fast).mean()
df['ma_slow'] = df['close'].rolling(window=period_slow).mean()


df['past_ma_fast'] = df['ma_fast'].shift(periods=1)
df['past_ma_slow'] = df['ma_slow'].shift(periods=1)
df.dropna(how='any', inplace=True)


# 生成 [T日收盘] 的金叉死叉信号 [信号来源于:T-1日和T日的 MA(5, 10)]
df['signal'] = np.NAN
for i in df.index:
	if df.loc[i, 'past_ma_fast'] <= df.loc[i, 'past_ma_slow'] and df.loc[i, 'ma_fast'] > df.loc[i, 'ma_slow']:  # 金叉做多
		df.loc[i, 'signal'] = 1
	elif df.loc[i, 'past_ma_fast'] >= df.loc[i, 'past_ma_slow'] and df.loc[i, 'ma_fast'] < df.loc[i, 'ma_slow']:  # 死叉做空
		df.loc[i, 'signal'] = -1


# 生成 [T+1日开盘] 的交易操作 [信号来源于:T日的 signal]
df['trade'] = df['signal'].shift(1).fillna(0)


# 删除无用列 添加 position market_value cash total_asset [P-M-C-T] 列
df = df[['code', 'open', 'open_pct_change', 'trade']]
df.loc[df.index[0], 'position'] = 0
df.loc[df.index[0], 'market_value'] = 0
df.loc[df.index[0], 'total_asset'] = 100000
df.loc[df.index[0], 'cash'] = 100000


def max_pos(price, cash, commission, min_size):
	cash_available = cash * (1 - commission)
	pos = cash_available / price // min_size * min_size
	return pos


# 根据 [T+1日开盘] 的交易信号 进行交易
for i in range(1, len(df)):

	index = df.index[i]
	past_index = df.index[i - 1]

	if df.loc[index, 'trade'] == 0:  # 当日无交易
		df.loc[index, 'position'] = df.loc[past_index, 'position']  # P
		df.loc[index, 'cash'] = df.loc[past_index, 'cash']  # C
		if df.loc[index, 'position'] != 0:  # 若有持仓
			df.loc[index, 'market_value'] = df.loc[past_index, 'market_value'] * (1 + df.loc[index, 'open_pct_change'])  # M
			df.loc[index, 'total_asset'] = df.loc[index, 'market_value'] + df.loc[index, 'cash']  # T
		else:  # 若无持仓
			df.loc[index, 'market_value'] = 0  # M
			df.loc[index, 'total_asset'] = df.loc[past_index, 'total_asset']  # T

	elif df.loc[index, 'trade'] == 1:  # 当日有交易 买入做多
		buy_position = max_pos(price=df.loc[index, 'open'],
							   cash=df.loc[past_index, 'cash'],
							   commission=2 / 1000,
							   min_size=100)
		buy_value = buy_position * df.loc[index, 'open']
		df.loc[index, 'position'] = buy_position  # P
		df.loc[index, 'market_value'] = buy_value  # M
		df.loc[index, 'cash'] = df.loc[past_index, 'cash'] - buy_value  # C
		df.loc[index, 'cash'] -= buy_value * (2 / 1000)
		df.loc[index, 'total_asset'] = df.loc[index, 'market_value'] + df.loc[index, 'cash']  # T

	elif df.loc[index, 'trade'] == -1:  # 当日有交易 卖出做空
		sell_position = df.loc[past_index, 'position']
		sell_value = sell_position * df.loc[index, 'open']
		df.loc[index, 'position'] = 0  # P
		df.loc[index, 'market_value'] = 0  # M
		df.loc[index, 'cash'] = df.loc[past_index, 'cash'] + sell_value  # C
		df.loc[index, 'cash'] -= sell_value * (2 / 1000)
		df.loc[index, 'total_asset'] = df.loc[index, 'cash']  # T


# 打印 dataframe 末尾部分
print(df.tail())
print('Final Total Asset = {} RMB'.format(df.loc[df.index[-1], 'total_asset']))


# 策略绩效分析 生成策略报告
import quantstats, webbrowser
df['stra_pct_returns'] = df['total_asset'].pct_change().fillna(0)
df_bench = pd.read_csv(filepath_or_buffer=r'E:\qi_learn\bt\data\hs300_bench_day.csv',
                       usecols=['date', 'close'],
                       parse_dates=['date'],
                       index_col='date')
df_bench['bench_pct_returns'] = df_bench['close'].pct_change().fillna(0)

quantstats.reports.html(returns=df['stra_pct_returns'],
                        benchmark=df_bench['bench_pct_returns'],
                        output=r'./output_test.html',
                        title='test')
webbrowser.open(r'./output_test.html')







