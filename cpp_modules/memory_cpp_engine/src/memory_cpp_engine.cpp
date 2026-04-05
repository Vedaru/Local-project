#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <thread>
#include <vector>

#if defined(_WIN32)
#if defined(MEMORY_CPP_ENGINE_EXPORTS)
#define MEMORY_API __declspec(dllexport)
#else
#define MEMORY_API __declspec(dllimport)
#endif
#else
#define MEMORY_API
#endif

namespace {

constexpr std::uint64_t FNV_OFFSET = 14695981039346656037ull;
constexpr std::uint64_t FNV_PRIME = 1099511628211ull;

std::size_t resolve_worker_count(std::size_t requested_workers, std::size_t candidate_count) {
    if (candidate_count == 0) {
        return 1;
    }

    std::size_t workers = requested_workers;
    if (workers == 0) {
        workers = static_cast<std::size_t>(std::thread::hardware_concurrency());
    }
    if (workers == 0) {
        workers = 4;
    }

    workers = std::max<std::size_t>(1, workers);
    return std::min(workers, candidate_count);
}

void compute_score_range(
    const float* query,
    std::size_t dimension,
    const float* candidates,
    const double* timestamps,
    const std::uint64_t* access_counts,
    const double* decay_factors,
    double current_time,
    double decay_rate,
    std::size_t begin,
    std::size_t end,
    double* out_scores,
    double* out_decays
) {
    for (std::size_t i = begin; i < end; ++i) {
        const float* candidate = candidates + (i * dimension);

        double dot = 0.0;
        for (std::size_t d = 0; d < dimension; ++d) {
            dot += static_cast<double>(query[d]) * static_cast<double>(candidate[d]);
        }

        const double similarity = dot * 100.0;
        const double time_diff = std::max(0.0, current_time - timestamps[i]);
        const double decay_term = std::exp(-decay_rate * time_diff);
        const double decayed = decay_factors[i] * decay_term;
        const double reinforcement = std::log(1.0 + static_cast<double>(access_counts[i]));

        out_decays[i] = decayed;
        out_scores[i] = similarity * decayed * reinforcement;
    }
}

int compute_adjusted_scores_impl(
    const float* query,
    std::size_t dimension,
    const float* candidates,
    std::size_t candidate_count,
    const double* timestamps,
    const std::uint64_t* access_counts,
    const double* decay_factors,
    double current_time,
    double decay_rate,
    std::size_t worker_count,
    double* out_scores,
    double* out_decays
) {
    if (query == nullptr || candidates == nullptr || timestamps == nullptr || access_counts == nullptr
        || decay_factors == nullptr || out_scores == nullptr || out_decays == nullptr) {
        return 1;
    }
    if (dimension == 0) {
        return 2;
    }

    if (candidate_count == 0) {
        return 0;
    }

    const std::size_t resolved_workers = resolve_worker_count(worker_count, candidate_count);
    if (resolved_workers <= 1 || candidate_count < 256) {
        compute_score_range(
            query,
            dimension,
            candidates,
            timestamps,
            access_counts,
            decay_factors,
            current_time,
            decay_rate,
            0,
            candidate_count,
            out_scores,
            out_decays
        );
        return 0;
    }

    const std::size_t chunk_size = (candidate_count + resolved_workers - 1) / resolved_workers;
    std::vector<std::thread> workers;
    workers.reserve(resolved_workers);

    std::size_t begin = 0;
    while (begin < candidate_count) {
        const std::size_t end = std::min(candidate_count, begin + chunk_size);
        workers.emplace_back(
            [=]() {
                compute_score_range(
                    query,
                    dimension,
                    candidates,
                    timestamps,
                    access_counts,
                    decay_factors,
                    current_time,
                    decay_rate,
                    begin,
                    end,
                    out_scores,
                    out_decays
                );
            }
        );
        begin = end;
    }

    for (auto& worker : workers) {
        worker.join();
    }

    return 0;
}

}  // namespace

extern "C" {

MEMORY_API int compute_adjusted_scores_cpp(
    const float* query,
    std::size_t dimension,
    const float* candidates,
    std::size_t candidate_count,
    const double* timestamps,
    const std::uint64_t* access_counts,
    const double* decay_factors,
    double current_time,
    double decay_rate,
    double* out_scores,
    double* out_decays
) {
    return compute_adjusted_scores_impl(
        query,
        dimension,
        candidates,
        candidate_count,
        timestamps,
        access_counts,
        decay_factors,
        current_time,
        decay_rate,
        0,
        out_scores,
        out_decays
    );
}

MEMORY_API int compute_adjusted_scores_with_threads_cpp(
    const float* query,
    std::size_t dimension,
    const float* candidates,
    std::size_t candidate_count,
    const double* timestamps,
    const std::uint64_t* access_counts,
    const double* decay_factors,
    double current_time,
    double decay_rate,
    std::size_t worker_count,
    double* out_scores,
    double* out_decays
) {
    return compute_adjusted_scores_impl(
        query,
        dimension,
        candidates,
        candidate_count,
        timestamps,
        access_counts,
        decay_factors,
        current_time,
        decay_rate,
        worker_count,
        out_scores,
        out_decays
    );
}

MEMORY_API int hash_embed_text_cpp(
    const std::uint8_t* text_utf8,
    std::size_t text_len,
    std::size_t dimension,
    float* out_embedding
) {
    if (out_embedding == nullptr || dimension == 0) {
        return 1;
    }
    if (text_utf8 == nullptr && text_len > 0) {
        return 2;
    }

    for (std::size_t i = 0; i < dimension; ++i) {
        out_embedding[i] = 0.0f;
    }

    for (std::size_t ngram = 2; ngram <= 4; ++ngram) {
        if (text_len < ngram) {
            continue;
        }
        for (std::size_t start = 0; start + ngram <= text_len; ++start) {
            std::uint64_t hash = FNV_OFFSET;
            for (std::size_t j = 0; j < ngram; ++j) {
                hash ^= static_cast<std::uint64_t>(text_utf8[start + j]);
                hash *= FNV_PRIME;
            }
            const std::size_t index = static_cast<std::size_t>(hash % dimension);
            out_embedding[index] += 1.0f;
        }
    }

    double norm_sq = 0.0;
    for (std::size_t i = 0; i < dimension; ++i) {
        const double value = static_cast<double>(out_embedding[i]);
        norm_sq += value * value;
    }

    const double norm = std::sqrt(norm_sq);
    if (norm > 0.0) {
        for (std::size_t i = 0; i < dimension; ++i) {
            out_embedding[i] = static_cast<float>(static_cast<double>(out_embedding[i]) / norm);
        }
    }

    return 0;
}

}  // extern "C"
