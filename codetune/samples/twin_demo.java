class TwinDemo {
    int work(int n) {
        int scale = 8;
        int offset = 2 * 3 + 1;
        int total = 0;
        int i = 0;
        while (i < 10) {
            total = total + i * scale;
            i = i + 1;
        }
        if (n > 0) {
            total = total + n * scale + offset;
        } else {
            total = total - offset;
        }
        int waste = total * 100;
        return total;
    }
}