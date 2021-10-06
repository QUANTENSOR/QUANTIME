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


def My_Double_SMA_Opt(df, period_fast, period_slow):

	# print('period_fast = {}, period_slow = {}'.format(period_fast, period_slow))

	df['open_pct_change'] = df['open'].pct_change().fillna(value=0)

	df['ma_fast'] = df['close'].rolling(window=period_fast).mean()
	df['ma_slow'] = df['close'].rolling(window=period_slow).mean()

	df['past_ma_fast'] = df['ma_fast'].shift(periods=1)
	df['past_ma_slow'] = df['ma_slow'].shift(periods=1)
	df.dropna(how='any', inplace=True)

	# 生成 [T日收盘] 的金叉死叉信号 [信号来源于:T-1日和T日的 MA(5, 10)]
	df['signal'] = np.NAN
	for i in df.index:
		if df.loc[i, 'past_ma_fast'] <= df.loc[i, 'past_ma_slow'] and df.loc[i, 'ma_fast'] > df.loc[
			i, 'ma_slow']:  # 金叉做多
			df.loc[i, 'signal'] = 1
		elif df.loc[i, 'past_ma_fast'] >= df.loc[i, 'past_ma_slow'] and df.loc[i, 'ma_fast'] < df.loc[
			i, 'ma_slow']:  # 死叉做空
			df.loc[i, 'signal'] = -1

	# 生成 [T+1日开盘] 的交易操作 [信号来源于:T日的 signal]
	df['trade'] = df['signal'].shift(1).fillna(0)

	# 生成 [T+1日开盘] 的持仓这状态 无仓/多仓/空仓
	df['position_side'] = 999999999999999

	# 初始化设置
	init_cash = 100000
	init_commission = 2 / 1000
	init_min_size = 100
	init_slippage = 0.01

	# 删除无用列 添加 position market_value cash total_asset [P-M-C-T] 列
	df = df.copy()
	df = df[['code', 'open', 'open_pct_change', 'trade']]
	df.loc[df.index[0], 'position'] = 0
	df.loc[df.index[0], 'market_value'] = 0
	df.loc[df.index[0], 'total_asset'] = init_cash
	df.loc[df.index[0], 'cash'] = init_cash

	def max_pos(price, cash, commission, min_size):
		cash_available = cash * (1 - commission)
		pos = cash_available / price // min_size * min_size
		return pos

	# 根据 [T+1日开盘] 的交易信号 进行交易
	for i in range(1, len(df)):

		index = df.index[i]
		past_index = df.index[i - 1]

		trade = [df.loc[past_index, 'trade'], df.loc[index, 'trade']]
		position = [df.loc[past_index, 'position'], df.loc[index, 'position']]
		market_value = [df.loc[past_index, 'market_value'], df.loc[index, 'market_value']]
		cash = [df.loc[past_index, 'cash'], df.loc[index, 'cash']]
		total_asset = [df.loc[past_index, 'total_asset'], df.loc[index, 'total_asset']]
		open = [df.loc[index, 'open']]
		open_pct_change = [df.loc[index, 'open_pct_change']]

		# ==== -1 表示 T 日当前 bar, -2 表示 T-1日 past_bar ====
		# ==== market_value 默认为 abs() 值 即空仓也视为正数的市值 ====
		if trade[-1] == 0:  # 当日无交易
			position[-1] = position[-2]  # P
			cash[-1] = cash[-2]  # C
			if position[-1] > 0:  # 持有多仓
				market_value[-1] = market_value[-2] * (1 + open_pct_change[-1])  # M
				total_asset[-1] = market_value[-1] + cash[-1]  # T
			elif position[-1] < 0:  # 持有空仓
				market_value[-1] = market_value[-2] * (1 - open_pct_change[-1])  # M
				total_asset[-1] = market_value[-1] + cash[-1]  # T
			elif position[-1] == 0:  # 若无持仓
				market_value[-1] = 0  # M
				total_asset[-1] = total_asset[-2]  # T

		elif trade[-1] == 1:  # 当日有交易 买入做多
			if position[-2] == 0:  # first-start
				buy_price = open[-1] + init_slippage  # 滑点注入
				buy_position = max_pos(price=buy_price,
									   cash=cash[-2],
									   commission=init_commission,
									   min_size=init_min_size)  # P
				position[-1] = buy_position  # P
				buy_value = buy_position * buy_price  # Buy-Value !== Market-Value 考虑加仓情况
				market_value[-1] = buy_value  # M
				cash[-1] = cash[-2] - buy_value  # C
				cash[-1] -= buy_value * (2 / 1000)  # C
				total_asset[-1] = market_value[-1] + cash[-1]  # T

			elif position[-2] < 0:  # already-start
				buy_price = open[-1] + init_slippage  # 滑点注入
				cash[-1] = cash[-2] + market_value[-2]  # 平空 C
				position[-1] = 0  # 平空 P
				market_value[-1] = 0  # 平空 M
				total_asset[-1] = market_value[-1] + cash[-1]  # 平空 T
				buy_position = max_pos(price=buy_price,
									   cash=cash[-1],
									   commission=init_commission,
									   min_size=init_min_size)
				position[-1] = buy_position  # P
				buy_value = buy_position * buy_price
				market_value[-1] = buy_value
				cash[-1] = cash[-1] - buy_value  # C
				cash[-1] -= buy_value * (2 / 1000)  # C
				total_asset[-1] = market_value[-1] + cash[-1]  # T

		elif trade[-1] == -1:  # 当日有交易 卖出做空
			if position[-2] == 0:  # first-start
				sell_price = open[-1] - init_slippage  # 滑点注入
				sell_position = - max_pos(price=sell_price,
										  cash=cash[-2],  # C
										  commission=init_commission,
										  min_size=init_min_size)  # --
				sell_value = abs(sell_position) * sell_price  # ++
				position[-1] = sell_position  # P --
				market_value[-1] = sell_value  # M ++
				cash[-1] = cash[-2] - sell_value  # C
				cash[-1] -= sell_value * (2 / 1000)
				total_asset[-1] = market_value[-1] + cash[-1]  # T

			elif position[-2] > 0:  # already-start
				sell_price = open[-1] - init_slippage  # 滑点注入
				cash[-1] = cash[-2] + market_value[-2]  # 平多 C
				position[-1] = 0  # 平多 P
				market_value[-1] = 0  # 平多 M
				total_asset[-1] = market_value[-1] + cash[-1]  # 平多 T
				sell_position = - max_pos(price=sell_price,
										  cash=cash[-1],  # C
										  commission=init_commission,
										  min_size=init_min_size)  # --
				sell_value = abs(sell_position) * sell_price  # --
				position[-1] = sell_position  # P --
				market_value[-1] = sell_value  # M ++
				cash[-1] = cash[-1] - sell_value  # C
				cash[-1] -= sell_value * (2 / 1000)
				total_asset[-1] = market_value[-1] + cash[-1]  # T

		df.loc[index, 'trade'] = trade[-1]
		df.loc[index, 'position'] = position[-1]
		df.loc[index, 'market_value'] = market_value[-1]
		df.loc[index, 'cash'] = cash[-1]
		df.loc[index, 'total_asset'] = total_asset[-1]
		df.loc[index, 'open'] = open[-1]
		df.loc[index, 'open_pct_change'] = open_pct_change[-1]

	final_total_asset = round(df.loc[df.index[-1], 'total_asset'], 4)
	final_total_returns = round(final_total_asset - init_cash, 4)
	print('Params = {}\tFinal Total Asset = {} RMB\tTotal Returns = {} RMB'.
		  format(str(period_fast) + '-' + str(period_slow),
				 final_total_asset,
				 final_total_returns))

	return final_total_returns


if __name__ == '__main__':

	df = pd.read_csv(filepath_or_buffer=r'../data_example/hs300etf_day.csv',
					 usecols=['date', 'code', 'open', 'close'],
					 parse_dates=['date'],
					 index_col=['date'],
					 )

	params = []
	period_fast_array = np.arange(5, 201, 5)
	period_slow_array = np.arange(10, 201, 5)
	for i in period_fast_array:
		for j in period_slow_array:
			if i < j:
				params.append((i, j))

	params_opt_result = []
	returns_opt_result = []
	for params in params:
		period_fast = params[0]
		period_slow = params[1]
		result = My_Double_SMA_Opt(df=df.copy(), period_fast=period_fast, period_slow=period_slow)
		params_opt_result.append((period_fast, period_slow))  # tuple
		returns_opt_result.append(result)  # float

	params_returns = dict(zip(params_opt_result, returns_opt_result))
	print(params_returns)
	max_returns_key = max(params_returns, key=lambda k: params_returns[k])
	print(max_returns_key, params_returns[max_returns_key])

	exit()


	# # 策略绩效分析 生成策略报告
	# import quantstats, webbrowser
	# df['stra_pct_returns'] = df['total_asset'].pct_change().fillna(0)
	# df_bench = pd.read_csv(filepath_or_buffer=r'E:\qi_learn\bt\data\hs300_bench_day.csv',
	#                        usecols=['date', 'close'],
	#                        parse_dates=['date'],
	#                        index_col='date')
	# df_bench['bench_pct_returns'] = df_bench['close'].pct_change().fillna(0)
	#
	# quantstats.reports.html(returns=df['stra_pct_returns'],
	#                         benchmark=df_bench['bench_pct_returns'],
	#                         output=r'./output_test.html',
	#                         title='test')
	# webbrowser.open(r'E:\qi_learn\QUANTIME\demo_strategies/output_test.html')







