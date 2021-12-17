import numpy as np
import pandas as pd
import talib


def SMA(x: pd.Series, n: int):
	"""
	talib.SMA()
	"""
	SMA = [np.NAN] * (n - 1)
	for index in range(len(x)):
		if index < n - 1:
			continue
		else:
			window = x[index - n + 1:index + 1]
			SMA.append(np.average(window))

	return pd.Series(SMA)


def CROSSUP(x: pd.Series, y: pd.Series):
	"""
	上穿函数
	1 表示 x 上穿 y
	-1 表示 y 上穿 x (或 x 下穿 y)
	NaN 表示 无上下穿 保持原始排序
	"""
	if len(x) != len(y):
		raise Exception
	
	x = x.reset_index(drop=True)
	y = y.reset_index(drop=True)
	
	crossup = [np.NAN]

	for i in range(len(x) - 1):
		if x[i] <= y[i] and x[i + 1] > y[i + 1]:
			crossup.append(1)
		elif x[i] >= y[i] and x[i + 1] < y[i + 1]:
			crossup.append(-1)
		else:
			crossup.append(np.NAN)

	return pd.Series(crossup)


def LLV(x: pd.Series, n: int):
	"""
	talib.MIN()
	"""
	LLV = [np.NAN] * (n - 1)
	for index in range(len(x)):
		if index < n - 1:
			continue
		else:
			window = x[index - n + 1:index + 1]
			LLV.append(min(window))

	return pd.Series(LLV)


def HHV(x: pd.Series, n: int):
	"""
	talib.MAX()
	"""
	HHV = [np.NAN] * (n - 1)
	for index in range(len(x)):
		if index < n - 1:
			continue
		else:
			window = x[index - n + 1:index + 1]
			HHV.append(max(window))

	return pd.Series(HHV)


def RSV(close: pd.Series, high: pd.Series, low: pd.Series, n: int):
	"""
	RSV:=(CLOSE-LLV(LOW,N))/(HHV(HIGH,N)-LLV(LOW,N))*100;
	"""
	RSV = (close.values - LLV(x=low, n=n).values) / (HHV(x=high, n=n).values - LLV(x=low, n=n).values) * 100

	return pd.Series(RSV)


def KDJ(close: pd.Series, high: pd.Series, low: pd.Series, n: int, m1: int, m2: int):
	"""
	N=5;
	M1=3;
	M2=3;

	RSV:=(CLOSE-LLV(LOW,N))/(HHV(HIGH,N)-LLV(LOW,N))*100;
	K:SMA(RSV,M1,1);
	D:SMA(K,M2,1);
	J:3*K-2*D;
	"""

	RSV_VAL = RSV(close=close, high=high, low=low, n=n)
	K = SMA(x=RSV_VAL, n=m1)
	D = SMA(x=K, n=m2)
	J = 3 * K - 2 * D

	return K, D, J


if __name__ == '__main__':
 
	a = pd.Series([1, 2, 3, 4, 5, 6, 7])
	b = pd.Series([1, 3, 0, 5, -2, -3, 8])
	print(CROSSUP(x=a, y=b))

