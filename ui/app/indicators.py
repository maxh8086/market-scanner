def sma(closes, n):
    '''Returns a list the same length as closes. Entry i is the mean of closes[i-n+1 .. i], or None if i < n-1.'''
    if n <= 0:
        raise ValueError
    if not closes:
        return []
    result = [None] * len(closes)
    for i in range(n - 1, len(closes)):
        result[i] = sum(closes[i-n+1:i+1]) / n
    return result

def ema(closes, n):
    '''Returns a list the same length as closes. Seed at index n-1 with the SMA of the first n closes. After that, value = close*alpha + prev*(1-alpha) with alpha = 2/(n+1). None before index n-1.'''
    if n <= 0:
        raise ValueError
    if not closes:
        return []
    result = [None] * len(closes)
    if len(closes) < n:
        return result
    result[n-1] = sum(closes[:n]) / n
    alpha = 2 / (n + 1)
    for i in range(n, len(closes)):
        result[i] = closes[i] * alpha + result[i-1] * (1 - alpha)
    return result

def rsi(closes, n=14):
    '''Returns a list the same length as closes. Wilder smoothing. At index n use the simple average of the first n gains and losses (changes at indices 1..n). After that, avg = (prev_avg*(n-1) + current)/n. RSI = 100 - 100/(1+avg_gain/avg_loss). If avg_loss is 0, RSI = 100.0. None before index n.'''
    if n <= 0:
        raise ValueError
    if not closes:
        return []
    result = [None] * len(closes)
    if len(closes) <= n:
        return result
    gains = [0.0] * len(closes)
    losses = [0.0] * len(closes)
    for i in range(1, len(closes)):
        change = closes[i] - closes[i-1]
        if change > 0:
            gains[i] = change
        else:
            losses[i] = -change
    avg_gain = sum(gains[1:n+1]) / n
    avg_loss = sum(losses[1:n+1]) / n
    for i in range(n, len(closes)):
        if i > n:
            avg_gain = (avg_gain * (n-1) + gains[i]) / n
            avg_loss = (avg_loss * (n-1) + losses[i]) / n
        if avg_loss == 0:
            result[i] = 100.0
        else:
            result[i] = 100 - 100 / (1 + avg_gain / avg_loss)
    return result
