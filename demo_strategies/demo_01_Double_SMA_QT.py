import numpy as np
import pandas as pd
pd.set_option('expand_frame_repr', False)
pd.set_option('display.max_rows', 20000)
from QUANTIME.engine import QTEngine
from QUANTIME.strategy import QTStrategy


class My_Double_SMA(QTStrategy):

    params = {
        'period_fast': 5,
        'period_slow': 20,
    }

    def __init__(self):
        QTStrategy.__init__(self)
        self.close_array = self.datas.close
        self.ma_fast = self.close_array.sma(period=self.params['period_fast'])
        self.ma_slow = self.close_array.sma(period=self.params['period_slow'])

    def next(self):
        if self.ma_fast > self.ma_slow:
            self.buy()
        else:
            pass

    pass


if __name__ == '__main__':

    period_fast = 10
    period_slow = 60

    df = pd.read_csv(filepath_or_buffer=r'../data_example/hs300etf_day.csv',
                     usecols=['date', 'code', 'open', 'close'],
                     parse_dates=['date'],
                     index_col=['date'],
                     )

    era = QTEngine()

    era.add_data(data=df, data_type=pd.DataFrame)

    era.set_cash(cash=100000)
    era.set_commission(commission=2/1000)
    era.set_slippage(slippage=0.01)

    era.add_strategy(strategy=My_Double_SMA)

    era.run()










