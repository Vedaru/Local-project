use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::collections::{HashMap, VecDeque};
use std::sync::{Mutex, OnceLock};

const FNV_OFFSET: u64 = 14695981039346656037;
const FNV_PRIME: u64 = 1099511628211;

const DECAY_HOT_CAPACITY: usize = 256;
const DECAY_WARM_CAPACITY: usize = 2048;
const REINFORCEMENT_HOT_CAPACITY: usize = 128;
const REINFORCEMENT_WARM_CAPACITY: usize = 1024;

#[derive(Clone, Copy, Default)]
struct CacheStats {
    hot_hits: u64,
    warm_hits: u64,
    misses: u64,
}

struct RingLayer {
    capacity: usize,
    order: VecDeque<u64>,
    values: HashMap<u64, f64>,
}

impl RingLayer {
    fn new(capacity: usize) -> Self {
        Self {
            capacity,
            order: VecDeque::with_capacity(capacity),
            values: HashMap::with_capacity(capacity),
        }
    }

    fn get(&self, key: u64) -> Option<f64> {
        self.values.get(&key).copied()
    }

    fn insert(&mut self, key: u64, value: f64) -> Option<(u64, f64)> {
        if self.capacity == 0 {
            return None;
        }

        if self.values.contains_key(&key) {
            self.values.insert(key, value);
            return None;
        }

        let mut evicted = None;
        if self.values.len() >= self.capacity {
            if let Some(evicted_key) = self.order.pop_front() {
                if let Some(evicted_value) = self.values.remove(&evicted_key) {
                    evicted = Some((evicted_key, evicted_value));
                }
            }
        }

        self.order.push_back(key);
        self.values.insert(key, value);
        evicted
    }

    fn clear(&mut self) {
        self.order.clear();
        self.values.clear();
    }
}

struct LayeredRingCache {
    hot: RingLayer,
    warm: RingLayer,
    stats: CacheStats,
}

impl LayeredRingCache {
    fn new(hot_capacity: usize, warm_capacity: usize) -> Self {
        Self {
            hot: RingLayer::new(hot_capacity),
            warm: RingLayer::new(warm_capacity),
            stats: CacheStats::default(),
        }
    }

    fn get_or_insert_with<F>(&mut self, key: u64, builder: F) -> f64
    where
        F: FnOnce() -> f64,
    {
        if let Some(value) = self.hot.get(key) {
            self.stats.hot_hits += 1;
            return value;
        }

        if let Some(value) = self.warm.get(key) {
            self.stats.warm_hits += 1;
            self.promote_to_hot(key, value);
            return value;
        }

        self.stats.misses += 1;
        let value = builder();
        self.insert(key, value);
        value
    }

    fn insert(&mut self, key: u64, value: f64) {
        if let Some((evicted_key, evicted_value)) = self.hot.insert(key, value) {
            self.warm.insert(evicted_key, evicted_value);
        }
    }

    fn promote_to_hot(&mut self, key: u64, value: f64) {
        if let Some((evicted_key, evicted_value)) = self.hot.insert(key, value) {
            self.warm.insert(evicted_key, evicted_value);
        }
    }

    fn clear(&mut self) {
        self.hot.clear();
        self.warm.clear();
        self.stats = CacheStats::default();
    }

    fn stats(&self) -> CacheStats {
        self.stats
    }
}

static DECAY_CACHE: OnceLock<Mutex<LayeredRingCache>> = OnceLock::new();
static REINFORCEMENT_CACHE: OnceLock<Mutex<LayeredRingCache>> = OnceLock::new();

fn decay_cache() -> &'static Mutex<LayeredRingCache> {
    DECAY_CACHE.get_or_init(|| {
        Mutex::new(LayeredRingCache::new(
            DECAY_HOT_CAPACITY,
            DECAY_WARM_CAPACITY,
        ))
    })
}

fn reinforcement_cache() -> &'static Mutex<LayeredRingCache> {
    REINFORCEMENT_CACHE.get_or_init(|| {
        Mutex::new(LayeredRingCache::new(
            REINFORCEMENT_HOT_CAPACITY,
            REINFORCEMENT_WARM_CAPACITY,
        ))
    })
}

fn quantize_non_negative(value: f64, scale: f64) -> u64 {
    if !value.is_finite() {
        return 0;
    }

    let scaled = (value.max(0.0) * scale).round();
    if scaled <= 0.0 {
        return 0;
    }
    if scaled >= u64::MAX as f64 {
        return u64::MAX;
    }

    scaled as u64
}

fn build_decay_key(time_diff: f64, decay_rate: f64) -> u64 {
    let time_key = quantize_non_negative(time_diff, 1000.0);
    let rate_key = quantize_non_negative(decay_rate.abs(), 1_000_000_000.0);

    time_key.rotate_left(17) ^ rate_key.wrapping_mul(0x9E3779B97F4A7C15)
}

#[pyfunction]
fn compute_adjusted_scores(
    query_embedding: Vec<f32>,
    normalized_embeddings: Vec<Vec<f32>>,
    timestamps: Vec<f64>,
    access_counts: Vec<u64>,
    decay_factors: Vec<f64>,
    current_time: f64,
    decay_rate: f64,
) -> PyResult<(Vec<f64>, Vec<f64>)> {
    let candidate_len = normalized_embeddings.len();

    if candidate_len != timestamps.len()
        || candidate_len != access_counts.len()
        || candidate_len != decay_factors.len()
    {
        return Err(PyValueError::new_err(
            "All candidate vectors and metadata lists must have the same length.",
        ));
    }

    if candidate_len == 0 {
        return Ok((Vec::new(), Vec::new()));
    }

    let query_dim = query_embedding.len();
    if query_dim == 0 {
        return Err(PyValueError::new_err("query_embedding cannot be empty."));
    }

    let mut decay_guard = decay_cache()
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    let mut reinforcement_guard = reinforcement_cache()
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());

    let mut adjusted_scores = Vec::with_capacity(candidate_len);
    let mut decayed_factors = Vec::with_capacity(candidate_len);

    for (idx, embedding) in normalized_embeddings.iter().enumerate() {
        if embedding.len() != query_dim {
            return Err(PyValueError::new_err(
                "Each embedding must have the same dimension as query_embedding.",
            ));
        }

        let dot_product = query_embedding
            .iter()
            .zip(embedding.iter())
            .map(|(a, b)| (*a as f64) * (*b as f64))
            .sum::<f64>();

        let similarity = dot_product * 100.0;
        let time_diff = (current_time - timestamps[idx]).max(0.0);
        let decay_key = build_decay_key(time_diff, decay_rate);
        let decay_term =
            decay_guard.get_or_insert_with(decay_key, || (-decay_rate * time_diff).exp());
        let decayed = decay_factors[idx] * decay_term;

        let count_key = access_counts[idx];
        let reinforcement = reinforcement_guard
            .get_or_insert_with(count_key, || (1.0 + access_counts[idx] as f64).ln());
        let adjusted = similarity * decayed * reinforcement;

        adjusted_scores.push(adjusted);
        decayed_factors.push(decayed);
    }

    Ok((adjusted_scores, decayed_factors))
}

#[pyfunction]
fn clear_layered_caches() {
    let mut decay_guard = decay_cache()
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    decay_guard.clear();

    let mut reinforcement_guard = reinforcement_cache()
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    reinforcement_guard.clear();
}

#[pyfunction]
fn get_layered_cache_stats() -> PyResult<(u64, u64, u64, u64, u64, u64)> {
    let decay_stats = decay_cache()
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
        .stats();
    let reinforcement_stats = reinforcement_cache()
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
        .stats();

    Ok((
        decay_stats.hot_hits,
        decay_stats.warm_hits,
        decay_stats.misses,
        reinforcement_stats.hot_hits,
        reinforcement_stats.warm_hits,
        reinforcement_stats.misses,
    ))
}

#[pyfunction]
fn hash_embed_text(text: String, dimension: usize) -> PyResult<Vec<f32>> {
    if dimension == 0 {
        return Err(PyValueError::new_err("dimension must be greater than zero."));
    }

    let mut output = vec![0.0f32; dimension];
    let chars: Vec<char> = text.chars().collect();

    for ngram in 2..=4 {
        if chars.len() < ngram {
            continue;
        }

        for window in chars.windows(ngram) {
            let mut hash = FNV_OFFSET;

            for ch in window {
                let mut encoded = [0u8; 4];
                let utf8 = ch.encode_utf8(&mut encoded);
                for byte in utf8.as_bytes() {
                    hash ^= u64::from(*byte);
                    hash = hash.wrapping_mul(FNV_PRIME);
                }
            }

            let index = (hash as usize) % dimension;
            output[index] += 1.0;
        }
    }

    let norm = output
        .iter()
        .map(|value| (*value as f64) * (*value as f64))
        .sum::<f64>()
        .sqrt() as f32;

    if norm > 0.0 {
        for value in &mut output {
            *value /= norm;
        }
    }

    Ok(output)
}

#[pymodule]
fn _memory_rust(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(compute_adjusted_scores, m)?)?;
    m.add_function(wrap_pyfunction!(clear_layered_caches, m)?)?;
    m.add_function(wrap_pyfunction!(get_layered_cache_stats, m)?)?;
    m.add_function(wrap_pyfunction!(hash_embed_text, m)?)?;
    Ok(())
}
