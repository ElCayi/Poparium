//! Python's `random.Random`: the Mersenne Twister and the few methods the
//! meadow uses, so a seeded meadow (its grass, where each Popo starts) comes
//! out exactly as it always has.

pub struct PyRandom {
    state: [u32; 624],
    index: usize,
}

impl PyRandom {
    /// `random.Random(n)` for an integer seed.
    pub fn new(seed: u64) -> Self {
        let mut key: Vec<u32> = Vec::new();
        let mut n = seed;
        while n > 0 {
            key.push(n as u32);
            n >>= 32;
        }
        if key.is_empty() {
            key.push(0);
        }
        let mut random = PyRandom { state: [0; 624], index: 624 };
        random.init_by_array(&key);
        random
    }

    /// Seeded from the clock, for what only has to look random.
    pub fn from_time() -> Self {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos() as u64)
            .unwrap_or(1);
        PyRandom::new(nanos ^ (std::process::id() as u64) << 32)
    }

    fn init_genrand(&mut self, seed: u32) {
        self.state[0] = seed;
        for i in 1..624 {
            let previous = self.state[i - 1];
            self.state[i] = 1_812_433_253u32.wrapping_mul(previous ^ (previous >> 30)).wrapping_add(i as u32);
        }
        self.index = 624;
    }

    fn init_by_array(&mut self, key: &[u32]) {
        self.init_genrand(19_650_218);
        let (mut i, mut j) = (1usize, 0usize);
        for _ in 0..624.max(key.len()) {
            let previous = self.state[i - 1];
            self.state[i] = (self.state[i] ^ (previous ^ (previous >> 30)).wrapping_mul(1_664_525))
                .wrapping_add(key[j])
                .wrapping_add(j as u32);
            i += 1;
            j += 1;
            if i >= 624 {
                self.state[0] = self.state[623];
                i = 1;
            }
            if j >= key.len() {
                j = 0;
            }
        }
        for _ in 0..623 {
            let previous = self.state[i - 1];
            self.state[i] =
                (self.state[i] ^ (previous ^ (previous >> 30)).wrapping_mul(1_566_083_941)).wrapping_sub(i as u32);
            i += 1;
            if i >= 624 {
                self.state[0] = self.state[623];
                i = 1;
            }
        }
        self.state[0] = 0x8000_0000;
    }

    fn genrand(&mut self) -> u32 {
        if self.index >= 624 {
            for k in 0..624 {
                let y = (self.state[k] & 0x8000_0000) | (self.state[(k + 1) % 624] & 0x7fff_ffff);
                let mut next = self.state[(k + 397) % 624] ^ (y >> 1);
                if y & 1 != 0 {
                    next ^= 0x9908_b0df;
                }
                self.state[k] = next;
            }
            self.index = 0;
        }
        let mut y = self.state[self.index];
        self.index += 1;
        y ^= y >> 11;
        y ^= (y << 7) & 0x9d2c_5680;
        y ^= (y << 15) & 0xefc6_0000;
        y ^ (y >> 18)
    }

    fn getrandbits(&mut self, k: u32) -> u64 {
        if k <= 32 {
            return (self.genrand() >> (32 - k)) as u64;
        }
        // Not needed by the app beyond 32 bits; whole words, least significant first
        let low = self.genrand() as u64;
        let high = (self.genrand() >> (64 - k.min(64))) as u64;
        low | high << 32
    }

    fn randbelow(&mut self, n: usize) -> usize {
        let k = usize::BITS - n.leading_zeros();
        loop {
            let r = self.getrandbits(k) as usize;
            if r < n {
                return r;
            }
        }
    }

    /// `randrange(n)`, n > 0.
    pub fn randrange(&mut self, n: usize) -> usize {
        self.randbelow(n.max(1))
    }

    /// `randint(a, b)`, both included.
    pub fn randint(&mut self, a: i64, b: i64) -> i64 {
        a + self.randbelow((b - a + 1) as usize) as i64
    }

    pub fn choice<T: Copy>(&mut self, options: &[T]) -> T {
        options[self.randbelow(options.len())]
    }

    /// `random()`: a float in [0, 1).
    pub fn random(&mut self) -> f64 {
        let a = (self.genrand() >> 5) as f64;
        let b = (self.genrand() >> 6) as f64;
        (a * 67_108_864.0 + b) * (1.0 / 9_007_199_254_740_992.0)
    }
}
