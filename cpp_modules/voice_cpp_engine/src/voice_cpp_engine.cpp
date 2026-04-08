#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <limits>
#include <string>

#if defined(_WIN32)
#include <windows.h>
#endif

#if defined(_WIN32)
#if defined(VOICE_CPP_ENGINE_EXPORTS)
#define VOICE_API __declspec(dllexport)
#else
#define VOICE_API __declspec(dllimport)
#endif
#else
#define VOICE_API
#endif

namespace {

bool write_exact(FILE* file, const void* data, std::size_t size) {
    if (file == nullptr || data == nullptr || size == 0) {
        return size == 0;
    }
    return std::fwrite(data, 1, size, file) == size;
}

bool write_u16_le(FILE* file, std::uint16_t value) {
    const unsigned char bytes[2] = {
        static_cast<unsigned char>(value & 0xFFu),
        static_cast<unsigned char>((value >> 8) & 0xFFu),
    };
    return write_exact(file, bytes, sizeof(bytes));
}

bool write_u32_le(FILE* file, std::uint32_t value) {
    const unsigned char bytes[4] = {
        static_cast<unsigned char>(value & 0xFFu),
        static_cast<unsigned char>((value >> 8) & 0xFFu),
        static_cast<unsigned char>((value >> 16) & 0xFFu),
        static_cast<unsigned char>((value >> 24) & 0xFFu),
    };
    return write_exact(file, bytes, sizeof(bytes));
}

#if defined(_WIN32)
std::wstring utf8_to_utf16(const char* utf8_text) {
    if (utf8_text == nullptr || *utf8_text == '\0') {
        return std::wstring();
    }

    const int wide_len = MultiByteToWideChar(CP_UTF8, 0, utf8_text, -1, nullptr, 0);
    if (wide_len <= 1) {
        return std::wstring();
    }

    std::wstring wide(static_cast<std::size_t>(wide_len), L'\0');
    const int converted = MultiByteToWideChar(CP_UTF8, 0, utf8_text, -1, &wide[0], wide_len);
    if (converted <= 0) {
        return std::wstring();
    }

    if (!wide.empty() && wide.back() == L'\0') {
        wide.pop_back();
    }

    return wide;
}

FILE* open_file_utf8_for_write(const char* path_utf8) {
    const std::wstring wide_path = utf8_to_utf16(path_utf8);
    if (wide_path.empty()) {
        return nullptr;
    }
    return _wfopen(wide_path.c_str(), L"wb");
}
#else
FILE* open_file_utf8_for_write(const char* path_utf8) {
    if (path_utf8 == nullptr || *path_utf8 == '\0') {
        return nullptr;
    }
    return std::fopen(path_utf8, "wb");
}
#endif

bool write_wav_header(FILE* file, std::uint32_t sample_rate, std::uint32_t pcm_size) {
    if (!write_exact(file, "RIFF", 4)) {
        return false;
    }
    if (!write_u32_le(file, static_cast<std::uint32_t>(36u + pcm_size))) {
        return false;
    }
    if (!write_exact(file, "WAVE", 4)) {
        return false;
    }

    if (!write_exact(file, "fmt ", 4)) {
        return false;
    }
    if (!write_u32_le(file, 16u)) {
        return false;
    }
    if (!write_u16_le(file, 1u)) {
        return false;
    }
    if (!write_u16_le(file, 1u)) {
        return false;
    }
    if (!write_u32_le(file, sample_rate)) {
        return false;
    }
    if (!write_u32_le(file, static_cast<std::uint32_t>(sample_rate * 2u))) {
        return false;
    }
    if (!write_u16_le(file, 2u)) {
        return false;
    }
    if (!write_u16_le(file, 16u)) {
        return false;
    }

    if (!write_exact(file, "data", 4)) {
        return false;
    }
    if (!write_u32_le(file, pcm_size)) {
        return false;
    }

    return true;
}

double apply_volume_curve(double normalized, double safe_power) {
    if (normalized <= 0.0) {
        return 0.0;
    }

    const double power_delta_1 = std::abs(safe_power - 1.0);
    if (power_delta_1 < 1e-9) {
        return normalized;
    }

    const double power_delta_half = std::abs(safe_power - 0.5);
    if (power_delta_half < 1e-9) {
        return std::sqrt(normalized);
    }

    const double power_delta_2 = std::abs(safe_power - 2.0);
    if (power_delta_2 < 1e-9) {
        return normalized * normalized;
    }

    return std::pow(normalized, safe_power);
}

double compute_pcm_volume_value(
    const std::int16_t* samples,
    std::size_t sample_count,
    double safe_gate,
    double safe_normalizer,
    double safe_power
) {
    if (samples == nullptr || sample_count == 0u) {
        return 0.0;
    }

    double sum_sq = 0.0;
    std::size_t i = 0u;
    const std::size_t unrolled_end = sample_count - (sample_count % 8u);
    for (; i < unrolled_end; i += 8u) {
        const double s0 = static_cast<double>(samples[i]);
        const double s1 = static_cast<double>(samples[i + 1u]);
        const double s2 = static_cast<double>(samples[i + 2u]);
        const double s3 = static_cast<double>(samples[i + 3u]);
        const double s4 = static_cast<double>(samples[i + 4u]);
        const double s5 = static_cast<double>(samples[i + 5u]);
        const double s6 = static_cast<double>(samples[i + 6u]);
        const double s7 = static_cast<double>(samples[i + 7u]);
        sum_sq +=
            (s0 * s0) +
            (s1 * s1) +
            (s2 * s2) +
            (s3 * s3) +
            (s4 * s4) +
            (s5 * s5) +
            (s6 * s6) +
            (s7 * s7);
    }
    for (; i < sample_count; ++i) {
        const double sample = static_cast<double>(samples[i]);
        sum_sq += sample * sample;
    }

    const double rms = std::sqrt(sum_sq / static_cast<double>(sample_count));
    if (rms < safe_gate) {
        return 0.0;
    }

    const double normalized = std::max(0.0, rms / safe_normalizer);
    const double curved = apply_volume_curve(normalized, safe_power);
    return std::min(curved, 1.0);
}

}  // namespace

extern "C" {

VOICE_API int write_wav_mono16le_cpp(
    const char* path_utf8,
    const std::uint8_t* pcm_data,
    std::size_t pcm_size,
    std::uint32_t sample_rate
) {
    if (path_utf8 == nullptr || *path_utf8 == '\0') {
        return 1;
    }
    if (sample_rate == 0u) {
        return 2;
    }
    if (pcm_data == nullptr && pcm_size > 0) {
        return 3;
    }
    if ((pcm_size % 2u) != 0u) {
        return 4;
    }
    if (pcm_size > static_cast<std::size_t>(std::numeric_limits<std::uint32_t>::max() - 36u)) {
        return 5;
    }

    FILE* file = open_file_utf8_for_write(path_utf8);
    if (file == nullptr) {
        return 6;
    }

    const std::uint32_t pcm_size_u32 = static_cast<std::uint32_t>(pcm_size);
    bool ok = write_wav_header(file, sample_rate, pcm_size_u32);
    if (ok && pcm_size_u32 > 0u) {
        ok = write_exact(file, pcm_data, pcm_size_u32);
    }

    std::fclose(file);
    return ok ? 0 : 7;
}

VOICE_API int compute_pcm_volume_cpp(
    const std::int16_t* samples,
    std::size_t sample_count,
    double gate,
    double normalizer,
    double power,
    double* out_volume
) {
    if (out_volume == nullptr) {
        return 1;
    }
    if (sample_count == 0) {
        *out_volume = 0.0;
        return 0;
    }
    if (samples == nullptr) {
        return 2;
    }

    const double safe_gate = std::max(0.0, gate);
    const double safe_normalizer = std::max(1.0, normalizer);
    const double safe_power = std::max(0.01, power);

    *out_volume = compute_pcm_volume_value(
        samples,
        sample_count,
        safe_gate,
        safe_normalizer,
        safe_power
    );
    return 0;
}

VOICE_API int compute_pcm_volume_batch_cpp(
    const std::int16_t* samples,
    std::size_t sample_count,
    std::size_t frame_samples,
    double gate,
    double normalizer,
    double power,
    double* out_volumes,
    std::size_t out_capacity,
    std::size_t* out_count
) {
    if (out_count == nullptr) {
        return 1;
    }
    *out_count = 0u;

    if (sample_count == 0u) {
        return 0;
    }
    if (samples == nullptr) {
        return 2;
    }
    if (frame_samples == 0u) {
        return 3;
    }
    if (out_volumes == nullptr || out_capacity == 0u) {
        return 4;
    }

    const std::size_t frame_count = sample_count / frame_samples;
    if (frame_count == 0u) {
        return 0;
    }
    if (frame_count > out_capacity) {
        return 5;
    }

    const double safe_gate = std::max(0.0, gate);
    const double safe_normalizer = std::max(1.0, normalizer);
    const double safe_power = std::max(0.01, power);

    for (std::size_t frame_index = 0u; frame_index < frame_count; ++frame_index) {
        const std::size_t offset = frame_index * frame_samples;
        out_volumes[frame_index] = compute_pcm_volume_value(
            samples + offset,
            frame_samples,
            safe_gate,
            safe_normalizer,
            safe_power
        );
    }

    *out_count = frame_count;
    return 0;
}

VOICE_API int build_chunk_index_cpp(
    std::size_t total_size,
    std::size_t chunk_size,
    std::size_t* out_offsets,
    std::size_t* out_sizes,
    std::size_t out_capacity,
    std::size_t* out_count
) {
    if (out_count == nullptr) {
        return 1;
    }
    *out_count = 0u;

    if (chunk_size == 0u) {
        return 2;
    }
    if (total_size == 0u) {
        return 0;
    }
    if (out_offsets == nullptr || out_sizes == nullptr || out_capacity == 0u) {
        return 3;
    }

    const std::size_t chunk_count = (total_size + chunk_size - 1u) / chunk_size;
    if (chunk_count > out_capacity) {
        return 4;
    }

    std::size_t offset = 0u;
    for (std::size_t index = 0u; index < chunk_count; ++index) {
        const std::size_t remaining = total_size - offset;
        const std::size_t size = std::min(chunk_size, remaining);
        out_offsets[index] = offset;
        out_sizes[index] = size;
        offset += size;
    }

    *out_count = chunk_count;
    return 0;
}

}  // extern "C"
