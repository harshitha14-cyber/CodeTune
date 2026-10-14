class OptimizeDemo {
    int demo(int n) {
        int a = 4;
        int b = a * 2 + 3;
        int unused = n * 100;
        int c = n * 8;
        int d = n * 2;
        int flag = 0;
        int r = 0;
        if (flag != 0) {
            r = 999;
        } else {
            r = b + c;
        }
        int i = 0;
        while (i < 3) {
            r = r + d;
            i = i + 1;
        }
        return r;
    }
}
