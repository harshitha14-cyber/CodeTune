def demo(n):
    a = 4
    b = a * 2 + 3
    unused = n * 100
    c = n * 8
    d = n * 2
    flag = 0
    r = 0
    if flag:
        r = 999
    else:
        r = b + c
    i = 0
    while i < 3:
        r = r + d
        i = i + 1
    return r
