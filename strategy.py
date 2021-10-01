import data.stock as st
import numpy as np


def week_period_strategy(code, time_freq, start_date, end_date):
    data = st.get_single_price(code, time_freq, start_date, end_date)
    # 新建周期字段
    data['weekday'] = data.index.weekday
    # 周四买入
    data['buy_signal'] = np.where((data['weekday'] == 3), 1, 0)
    # 周一卖出
    data['sell_signal'] = np.where((data['weekday'] == 0), -1, 0)

    # # 模拟重复信号
    # data['buy_signal'] = np.where((data['weekday'] == 3) | (data['weekday'] == 4), 1, 0)
    # data['sell_signal'] = np.where((data['weekday'] == 0) | (data['weekday'] == 1), -1, 0)

    # 整合信号
    data['buy_signal'] = np.where((data['buy_signal'] == 1)
                                  & (data['buy_signal'].shift(1) == 1),
                                  0, data['buy_signal'])
    data['sell_signal'] = np.where((data['sell_signal'] == -1)
                                  & (data['sell_signal'].shift(1) == -1),
                                   0, data['sell_signal'])
    data['signal'] = data['buy_signal'] + data['sell_signal']

    # 计算单次收益率：开仓、平仓 (开仓的全部股数)
    data = data[data['signal'] != 0] # 筛选
    data['profit_pct'] = (data['close'] - data['close'].shift(1)) / data['close'].shift(1)
    data = data[data['signal'] == -1]

    return data


if __name__ == '__main__':
    data = week_period_strategy('000001.XSHE', 'daily', '2020-01-01', '2020-03-01')
    print(data[['close', 'signal', 'profit_pct']])
