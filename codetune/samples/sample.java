class Sample {
    int square(int x) {
        return x * x;
    }

    int clamp(int a, int b) {
        int x = a + b;
        int y = square(x);
        int z;
        if (y > 100) {
            z = 100;
        } else {
            z = y;
        }
        int w = 0;
        while (w < 3) {
            w = w + 1;
        }
        return z;
    }
}
