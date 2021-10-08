"""
DIF:EMA(CLOSE,12)-EMA(CLOSE,26);
DEA:EMA(DIF,9);
MACD:(DIF-DEA)*2;

金叉:=CROSS(DIF,DEA);
死叉:=CROSS(DEA,DIF);

买入:=金叉;
卖出:=死叉;
"""

import talib
import numpy as np
import pandas as pd
from QUANTIME.demo_strategies.Functions_Numpy import *
pd.set_option('expand_frame_repr', False)
pd.set_option('display.max_rows', 20000)


# 导入数据
df = pd.read_csv(filepath_or_buffer=r'../data_example/hs300etf_day.csv',
				 usecols=['date', 'code', 'open', 'close'],
				 parse_dates=['date'],
				 index_col=['date'],
				 )


# 新增指标列
df['open_pct_change'] = df['open'].pct_change().fillna(value=0)
df['DIF'] = talib.EMA(df['close'], timeperiod=12) - talib.EMA(df['close'], timeperiod=26)
df['DEA'] = talib.EMA(df['DIF'], timeperiod=9)
df['MACD'] = 2 * (df['DIF'] - df['DEA'])

df['past_DIF'] = df['DIF'].shift(periods=1)
df['past_DEA'] = df['DEA'].shift(periods=1)
df.dropna(how='any', inplace=True)


# 生成 [T日收盘] 的金叉死叉信号 [信号来源于:T-1日和T日的 DIF DEA]
df['signal'] = np.NAN
for i in df.index:
	if df.loc[i, 'past_DIF'] <= df.loc[i, 'past_DEA'] and df.loc[i, 'DIF'] > df.loc[i, 'DEA']:  # 金叉做多
		df.loc[i, 'signal'] = 1
	elif df.loc[i, 'past_DIF'] >= df.loc[i, 'past_DEA'] and df.loc[i, 'DIF'] < df.loc[i, 'DEA']:  # 死叉做空
		df.loc[i, 'signal'] = -1


# 生成 [T+1日开盘] 的交易操作 [信号来源于:T日的 signal]
df['trade'] = df['signal'].shift(1).fillna(0)


# 初始化设置
init_cash = 100000
init_commission = 2 / 1000
init_min_size = 100
init_slippage = 0.01


# 删除无用列 添加 position market_value cash total_asset [P-M-C-T ^C^S] 列
df = df[['code', 'open', 'open_pct_change', 'trade']]
df.loc[df.index[0], 'position'] = 0
df.loc[df.index[0], 'market_value'] = 0
df.loc[df.index[0], 'total_asset'] = init_cash
df.loc[df.index[0], 'cash'] = init_cash


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
		no_trade(position=position, market_value=market_value,
			     cash=cash, total_asset=total_asset,
			     open_pct_change=open_pct_change)

	elif trade[-1] == 1:  # 当日有交易 买入做多
		if position[-2] == 0:  # first-start 无仓 初始买入 无仓开多
			empty_position_open_long(long_price=open, position=position,
									 market_value=market_value, cash=cash, total_asset=total_asset,
									 slippage=init_slippage, commission=init_commission, min_size=init_min_size,
									 max_pos_in=True)

		elif position[-2] < 0:  # already-start 已经持有空仓 平空开多
			close_short_open_long(short_price=open, long_price=open,
								  position=position, market_value=market_value, cash=cash, total_asset=total_asset,
								  slippage=init_slippage, commission=init_commission, min_size=init_min_size,
								  max_pos_in=True)

		elif position[-2] > 0:  # already-start 已经持有多仓 即相邻的多头信号重复出现 此策略执行 [当日无交易] 代码段
			no_trade(position=position, market_value=market_value,
					 cash=cash, total_asset=total_asset,
					 open_pct_change=open_pct_change)

	elif trade[-1] == -1:  # 当日有交易 卖出做空
		if position[-2] == 0:  # first-start 无仓 初始卖空 无仓开空
			empty_position_open_short(short_price=open,
									  position=position, market_value=market_value, cash=cash, total_asset=total_asset,
									  slippage=init_slippage, commission=init_commission, min_size=init_min_size,
									  max_pos_in=True)

		elif position[-2] > 0:  # already-start 已经持有多仓 平多开空
			close_long_open_short(long_price=open, short_price=open,
								  position=position, market_value=market_value, cash=cash, total_asset=total_asset,
								  slippage=init_slippage, commission=init_commission, min_size=init_min_size,
								  max_pos_in=True)

		elif position[-2] < 0:  # already-start 已经持有空仓 即相邻的空头信号重复出现 此此略执行 [当日无交易] 代码段
			no_trade(position=position, market_value=market_value,
					 cash=cash, total_asset=total_asset,
					 open_pct_change=open_pct_change)

	df.loc[index, 'trade'] = trade[-1]
	df.loc[index, 'position'] = position[-1]
	df.loc[index, 'market_value'] = market_value[-1]
	df.loc[index, 'cash'] = cash[-1]
	df.loc[index, 'total_asset'] = total_asset[-1]
	df.loc[index, 'open'] = open[-1]
	df.loc[index, 'open_pct_change'] = open_pct_change[-1]


# 打印 dataframe 末尾部分
final_total_asset = df.loc[df.index[-1], 'total_asset']
print('Final Total Asset = {} RMB'.format(final_total_asset))
# print(df)
# exit()

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
webbrowser.open(r'E:\qi_learn\QUANTIME\demo_strategies/output_test.html')




