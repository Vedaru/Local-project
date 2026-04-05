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

    long double sum_sq = 0.0;
    for (std::size_t i = 0; i < sample_count; ++i) {
        const long double sample = static_cast<long double>(samples[i]);
        sum_sq += sample * sample;
    }

    const long double mean_sq = sum_sq / static_cast<long double>(sample_count);
    const double rms = std::sqrt(static_cast<double>(mean_sq));
    if (rms < safe_gate) {
        *out_volume = 0.0;
        return 0;
    }

    const double normalized = std::max(0.0, rms / safe_normalizer);
    const double curved = std::pow(normalized, safe_power);
    *out_volume = std::min(curved, 1.0);
    return 0;
}

}  // extern "C"
