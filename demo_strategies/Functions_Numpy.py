# 满仓交易 计算订单成交量
def max_pos(price, cash, commission, min_size):
	cash_available = cash * (1 - commission)
	pos = cash_available / price // min_size * min_size
	return pos


# 当日无交易
def no_trade(position, market_value, cash, total_asset, open_pct_change):

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


# 无仓开多
def empty_position_open_long(long_price,
							 position, market_value, cash, total_asset,
							 slippage, commission, min_size,
							 volume=1, max_pos_in=False, target_pos_in=False,
							 ):

	# 滑点注入[^S]
	buy_price = long_price[-1] + slippage

	# 开多
	# 若设置百分比仓位
	buy_position = volume
	if max_pos_in:  # 满仓
		buy_position = max_pos(price=buy_price,
							   cash=cash[-2],
							   commission=commission,
							   min_size=min_size)
	elif target_pos_in:  # 指定百分比仓位
		buy_position = None
		pass

	position[-1] = buy_position  # P
	buy_value = buy_position * buy_price  # V
	market_value[-1] = buy_value  # M
	cash[-1] = cash[-2] - buy_value  # C
	cash[-1] -= buy_value * commission  # [^C]
	total_asset[-1] = market_value[-1] + cash[-1]  # T


# 无仓开空
def empty_position_open_short(short_price,
							  position, market_value, cash, total_asset,
							  slippage, commission, min_size,
							  volume=1, max_pos_in=False, target_pos_in=False,):

	# 滑点注入 [^S]
	sell_price = short_price[-1] - slippage

	# 开空
	# 若设置百分比仓位
	sell_position = volume
	if max_pos_in:  # 满仓
		sell_position = max_pos(price=sell_price,
							   cash=cash[-2],
							   commission=commission,
							   min_size=min_size)
		sell_position = - sell_price  # P --
	elif target_pos_in:  # 指定百分比仓位
		sell_position = 999999999999999999
		sell_position = - sell_position  # P --
		pass

	sell_value = abs(sell_position) * sell_price  # V ++
	position[-1] = sell_position  # P --
	market_value[-1] = sell_value  # M ++
	cash[-1] = cash[-2] - sell_value  # C
	cash[-1] -= sell_value * commission  # [^C]
	total_asset[-1] = market_value[-1] + cash[-1]  # T


# 平多开空 后续持有空仓
def close_long_open_short(long_price, short_price,
						  position, market_value, cash, total_asset,
						  slippage, commission, min_size,
						  volume=1, max_pos_in=False, target_pos_in=False,):

	# 滑点注入 [^S]
	buy_price = long_price[-1] + slippage
	sell_price = short_price[-1] - slippage

	# 平多
	sell_value = buy_price * position[-2]
	position[-1] = 0  # P
	market_value[-1] = 0  # M
	cash[-1] = cash[-2] + sell_value  # C
	cash[-1] -= sell_value * commission  # [^C]
	total_asset[-1] = cash[-1]  # T

	# 开空
	# 若设置百分比仓位
	sell_position = volume
	if max_pos_in:  # 满仓
		sell_position = max_pos(price=buy_price,
							   cash=cash[-1],
							   commission=commission,
							   min_size=min_size)
		sell_position = - sell_position  # P --
	elif target_pos_in:  # 指定百分比仓位
		sell_position = 999999999999
		sell_position = - sell_position  # P --
		pass

	position[-1] = sell_position  # P --
	sell_value = abs(sell_position) * sell_price  # V ++
	market_value[-1] = sell_value  # M
	cash[-1] = cash[-1] - sell_value  # C
	cash[-1] -= sell_value * commission  # [^C]
	total_asset[-1] = market_value[-1] + cash[-1]  # T


# 平空开多 后续持有多仓
def close_short_open_long(short_price, long_price,
						  position, market_value, cash, total_asset,
						  slippage, commission, min_size,
						  volume=1, max_pos_in=False, target_pos_in=False,):

	# 滑点注入 [^S]
	sell_price = short_price[-1] - slippage
	buy_price = long_price[-1] + slippage

	# 平空
	sell_value = sell_price * abs(position[-2])
	position[-1] = 0  # P
	market_value[-1] = 0  # M
	cash[-1] = cash[-2] + sell_value  # C
	cash[-1] -= sell_value * commission  # [^C]
	total_asset[-1] = cash[-1]  # T

	# 开多
	# 若设置百分比仓位
	buy_position = volume
	if max_pos_in:  # 满仓
		buy_position = max_pos(price=buy_price,
							   cash=cash[-1],
							   commission=commission,
							   min_size=min_size)
	elif target_pos_in:  # 指定百分比仓位
		buy_position = None
		pass

	position[-1] = buy_position  # P
	buy_value = buy_position * buy_price  # V
	market_value[-1] = buy_value  # M
	cash[-1] = cash[-1] - buy_value  # C
	cash[-1] -= buy_value * commission  # [^C]
	total_asset[-1] = market_value[-1] + cash[-1]  # T


# 空仓加空 后续仍持有空仓
def short_position_add_short():
	pass


# 空仓减空 后续仍持有空仓
def short_position_reduce_short():
	pass


# 多仓加多 后续仍持有多仓
def long_position_add_long():
	pass


# 多仓减多 后续仍持有多仓
def long_position_reduce_long():
	pass


# 平仓
def close(position):
	if position > 0:
		pass
	elif position < 0:
		pass
	elif position == 0:
		raise Exception
		pass
	pass

