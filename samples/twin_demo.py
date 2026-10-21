def work(n):
    scale = 8
    offset = 2 * 3 + 1
    total = 0
    i = 0
    while i < 10:
        total = total + i * scale
        i = i + 1
    if n > 0:
        total = total + n * scale + offset
    else:
        total = total - offset
    waste = total * 100
    return total