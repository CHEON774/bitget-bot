import ccxt, asyncio, pandas as pd
import requests
from datetime import datetime
from collections import defaultdict

# ▼ 텔레그램 세팅
TELEGRAM_TOKEN = "7776435078:AAFsM_jIDSx1Eij4YJyqJp-zEDtQVtKohnU"
TELEGRAM_CHAT_ID = "1797494660"

def tg(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})

# ▼ 바이비트 캔들 수집 (가상매매 백테스트 구조)
def get_ohlcv(symbol, timeframe='15m', limit=200):
    bybit = ccxt.bybit({'enableRateLimit': True})
    return pd.DataFrame(
        bybit.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit),
        columns=['timestamp','open','high','low','close','volume']
    ).assign(time=lambda x: pd.to_datetime(x['timestamp'], unit='ms'))

# ▼ 지표계산 (MACD, ADX, 임계치 예시)
def macd(df, fast=7, slow=17, signal=8):
    ema_fast = df['close'].ewm(span=fast).mean()
    ema_slow = df['close'].ewm(span=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal).mean()
    hist = macd_line - signal_line
    df['macd'] = macd_line
    df['macdsignal'] = signal_line
    df['macdhist'] = hist
    return df

def adx(df, n=5):
    high, low, close = df['high'], df['low'], df['close']
    plus_dm = high.diff()
    minus_dm = low.diff()
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    plus_di = 100 * (plus_dm.ewm(span=n).mean() / tr.ewm(span=n).mean())
    minus_di = 100 * (minus_dm.ewm(span=n).mean() / tr.ewm(span=n).mean())
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    df['adx'] = dx.ewm(span=n).mean()
    return df

def threshold(df, col='macdhist', thresh=0):
    df['thresh'] = (df[col] > thresh).astype(int) - (df[col] < -thresh).astype(int)
    return df

# ▼ 전략 클래스(잔고/포지션/카운트 독립 관리)
class Strategy:
    def __init__(self, name, symbols, start_balance=756):
        self.name = name
        self.symbols = symbols
        self.balance = start_balance
        self.position = {sym: None for sym in symbols}
        self.entry_price = {sym: None for sym in symbols}
        self.side = {sym: None for sym in symbols}
        self.trail = {sym: False for sym in symbols}
        self.trail_max = {sym: None for sym in symbols}
        self.profit_count = 0
        self.loss_count = 0

    def open(self, sym, price, side):
        self.position[sym] = True
        self.entry_price[sym] = price
        self.side[sym] = side
        self.trail[sym] = False
        self.trail_max[sym] = price
    def close(self, sym, price, fee=0.00044):
        if self.position[sym]:
            entry = self.entry_price[sym]
            side = self.side[sym]
            # 수익률(롱/숏 모두), 레버리지 없이 단순 %
            profit = (price-entry)/entry if side=='long' else (entry-price)/entry
            # 수수료(진입+청산)
            profit -= fee*2
            if profit >= 0: self.profit_count += 1
            else: self.loss_count += 1
            self.balance *= (1+profit)
            self.position[sym] = None
            self.entry_price[sym] = None
            self.side[sym] = None
            self.trail[sym] = False
            self.trail_max[sym] = None
            return profit
        return None

    def is_open(self, sym): return self.position[sym] is not None

    def summary(self):
        s = f"[전략{self.name}]\n"
        for sym in self.symbols:
            stat = f"{sym}: "
            if self.is_open(sym):
                stat += f"{self.side[sym]} | 진입가: {self.entry_price[sym]}"
            else: stat += "포지션 없음"
            s += stat + '\n'
        s += f"현재 가상잔고: {self.balance:.2f}\n누적 익절: {self.profit_count}회 / 누적 손절: {self.loss_count}회\n"
        return s

# ▼ 포지션 진입/청산 신호(예시, 조건 구체화 필요)
def check_signal_A(df): # MACD+ADX
    # 롱: MACD히스토리 2연속 양봉 + ADX > 25
    long_signal = (df['macdhist'].iloc[-1]>0) & (df['macdhist'].iloc[-2]>0) & (df['adx'].iloc[-1]>25)
    # 숏: MACD히스토리 2연속 음봉 + ADX > 25
    short_signal = (df['macdhist'].iloc[-1]<0) & (df['macdhist'].iloc[-2]<0) & (df['adx'].iloc[-1]>25)
    return long_signal, short_signal

def check_signal_B(df): # MACD+임계치
    # 롱: MACD 0선 돌파(위) + macdhist > 임계치
    long_signal = (df['macd'].iloc[-2]<0) & (df['macd'].iloc[-1]>0) & (df['macdhist'].iloc[-1]>0.1)
    # 숏: MACD 0선 돌파(아래) + macdhist < -임계치
    short_signal = (df['macd'].iloc[-2]>0) & (df['macd'].iloc[-1]<0) & (df['macdhist'].iloc[-1]<-0.1)
    return long_signal, short_signal

def check_signal_D(df): # MACD+ADX+임계치
    long_signal = (df['macd'].iloc[-2]<0) & (df['macd'].iloc[-1]>0) & (df['macdhist'].iloc[-1]>0.1) & (df['adx'].iloc[-1]>25)
    short_signal = (df['macd'].iloc[-2]>0) & (df['macd'].iloc[-1]<0) & (df['macdhist'].iloc[-1]<-0.1) & (df['adx'].iloc[-1]>25)
    return long_signal, short_signal

# ▼ 메인 루프(가상매매)
def main():
    SYMBOLS = ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT']
    stratA = Strategy('A (MACD+ADX)', SYMBOLS)
    stratB = Strategy('B (MACD+임계치)', SYMBOLS)
    stratD = Strategy('D (MACD+ADX+임계치)', SYMBOLS)
    all_strategies = [stratA, stratB, stratD]
    msg_summary = ""

    # 캔들 데이터 (최대 200개)
    dfs = {sym: get_ohlcv(sym) for sym in SYMBOLS}
    for sym in SYMBOLS:
        df = dfs[sym]
        df = macd(df)
        df = adx(df)
        dfs[sym] = df

    # 매봉마다 신호체크 (실시간은 WebSocket loop에 연결)
    for i in range(20, len(dfs[SYMBOLS[0]])):
        now_prices = {sym: dfs[sym].iloc[i]['close'] for sym in SYMBOLS}
        for idx, sym in enumerate(SYMBOLS):
            df = dfs[sym].iloc[:i+1]
            # 전략별 신호 체크
            for strat, sigfn in zip(all_strategies, [check_signal_A, check_signal_B, check_signal_D]):
                long_signal, short_signal = sigfn(df)
                # 진입
                if not strat.is_open(sym):
                    if long_signal: strat.open(sym, now_prices[sym], 'long')
                    elif short_signal: strat.open(sym, now_prices[sym], 'short')
                # 청산(손절/익절/트레일링)
                if strat.is_open(sym):
                    entry = strat.entry_price[sym]
                    price = now_prices[sym]
                    # 익절, 손절, 트레일링 임계치는 심볼별로 다르게 커스터마이즈 가능
                    stop_loss = -0.008   # -0.8%
                    take_profit = 0.022  # 2.2%
                    fee = 0.00044
                    side = strat.side[sym]
                    pl = (price-entry)/entry if side=='long' else (entry-price)/entry
                    pl -= fee*2
                    # 트레일링(예: +2.2%이상 수익구간 진입시 -1% 이탈하면 청산)
                    if not strat.trail[sym] and pl > take_profit:
                        strat.trail[sym] = True
                        strat.trail_max[sym] = price
                    if strat.trail[sym]:
                        if side=='long':
                            strat.trail_max[sym] = max(strat.trail_max[sym], price)
                            if price < strat.trail_max[sym] * (1-0.01):
                                strat.close(sym, price)
                        else:
                            strat.trail_max[sym] = min(strat.trail_max[sym], price)
                            if price > strat.trail_max[sym] * (1+0.01):
                                strat.close(sym, price)
                    # 익절, 손절
                    elif pl < stop_loss or pl > take_profit:
                        strat.close(sym, price)
        # 1시간마다 텔레그램 알림 (여기선 매 루프마다)
        if i % 4 == 0:
            msg_summary = ""
            for strat in all_strategies:
                msg_summary += strat.summary() + '\n'
            tg(msg_summary)

    # 종료시 모든 포지션 자동 청산
    for strat in all_strategies:
        for sym in SYMBOLS:
            if strat.is_open(sym):
                strat.close(sym, dfs[sym].iloc[-1]['close'])
    msg_summary = ""
    for strat in all_strategies:
        msg_summary += strat.summary() + '\n'
    tg(msg_summary)

if __name__ == "__main__":
    main()
