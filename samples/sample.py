def square(x):
    return x * x


def clamp(a, b):
    x = a + b
    y = square(x)
    if y > 100:
        z = 100
    else:
        z = y
    w = 0
    while w < 3:
        w = w + 1
    return z
