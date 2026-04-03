use std::time::Duration;

use pyo3::prelude::*;
use reqwest::blocking::Client;
use reqwest::header::{
    HeaderMap, HeaderValue, ACCEPT, ACCEPT_LANGUAGE, CACHE_CONTROL, PRAGMA, USER_AGENT,
};
use scraper::{Html, Selector};
use serde::Serialize;

pub const MIN_VALID_CONTENT_CHARS: usize = 220;
pub const DEFAULT_TIMEOUT_SECONDS: u64 = 12;
pub const DEFAULT_MAX_CHARS: usize = 10_000;

#[derive(Serialize, Debug, Clone)]
pub struct FetchResult {
    pub success: bool,
    pub source: &'static str,
    pub content: Option<String>,
    pub error: Option<String>,
}

fn normalize_whitespace(input: &str) -> String {
    input.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn trim_chars(input: &str, max_chars: usize) -> String {
    input.chars().take(max_chars).collect::<String>()
}

fn looks_like_blocked_page(content: &str) -> bool {
    let lowered = content.to_lowercase();
    let blocked_hints = [
        "captcha",
        "access denied",
        "forbidden",
        "security check",
        "verify",
        "are you human",
        "enable javascript",
        "request blocked",
        "temporarily unavailable",
        "限制本次访问",
        "知乎小管家",
        "请求参数异常",
        "升级客户端后重试",
        "\"code\":40362",
        "\"code\":10003",
    ];

    let matched_hint = blocked_hints.iter().any(|hint| lowered.contains(hint));
    let looks_like_error_json = lowered.contains("{\"error\":") && lowered.contains("\"code\":");

    (matched_hint || looks_like_error_json) && lowered.chars().count() < MIN_VALID_CONTENT_CHARS * 3
}

fn best_text_from_selector(document: &Html, selector_raw: &str) -> String {
    let Ok(selector) = Selector::parse(selector_raw) else {
        return String::new();
    };

    let mut best_text = String::new();

    for element in document.select(&selector) {
        let text = normalize_whitespace(&element.text().collect::<Vec<_>>().join(" "));
        if text.len() > best_text.len() {
            best_text = text;
        }
    }

    best_text
}

fn extract_best_content(html: &str) -> String {
    let document = Html::parse_document(html);

    let article_selectors = [
        "article",
        "main article",
        "[role='main'] article",
        "main",
        "[role='main']",
        ".article-content",
        ".post-content",
        ".entry-content",
        ".markdown-body",
        ".post-body",
        ".content",
        ".article",
        ".RichText",
        ".RichText.ztext",
        ".Post-RichText",
        ".ztext",
        ".J-lemma-content",
        "#article-content",
        "#content",
    ];

    let mut best = String::new();
    for selector in article_selectors {
        let candidate = best_text_from_selector(&document, selector);
        if candidate.len() > best.len() {
            best = candidate;
        }
    }

    if !best.is_empty() {
        return best;
    }

    let fallback_selectors = [
        "article p",
        "main p",
        "p",
        "li",
        "blockquote",
        "pre",
        "code",
        "h1",
        "h2",
        "h3",
    ];

    let mut collected_blocks: Vec<String> = Vec::new();
    for selector in fallback_selectors {
        let Ok(parsed) = Selector::parse(selector) else {
            continue;
        };

        for node in document.select(&parsed) {
            let text = normalize_whitespace(&node.text().collect::<Vec<_>>().join(" "));
            if text.len() >= 20 {
                collected_blocks.push(text);
            }

            if collected_blocks.len() >= 1200 {
                break;
            }
        }

        if collected_blocks.len() >= 1200 {
            break;
        }
    }

    let combined = normalize_whitespace(&collected_blocks.join(" "));
    if !combined.is_empty() {
        return combined;
    }

    best_text_from_selector(&document, "body")
}

pub fn fetch_url(url: &str, timeout_seconds: u64, max_chars: usize) -> FetchResult {
    let mut headers = HeaderMap::new();
    headers.insert(
        USER_AGENT,
        HeaderValue::from_static(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        ),
    );
    headers.insert(
        ACCEPT,
        HeaderValue::from_static("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
    );
    headers.insert(ACCEPT_LANGUAGE, HeaderValue::from_static("zh-CN,zh;q=0.9,en;q=0.8"));
    headers.insert(CACHE_CONTROL, HeaderValue::from_static("no-cache"));
    headers.insert(PRAGMA, HeaderValue::from_static("no-cache"));

    let client = match Client::builder()
        .default_headers(headers)
        .timeout(Duration::from_secs(timeout_seconds.max(5)))
        .build()
    {
        Ok(client) => client,
        Err(error) => {
            return FetchResult {
                success: false,
                source: "rust_static",
                content: None,
                error: Some(format!("failed to build HTTP client: {error}")),
            }
        }
    };

    let response = match client.get(url).send() {
        Ok(response) => response,
        Err(error) => {
            return FetchResult {
                success: false,
                source: "rust_static",
                content: None,
                error: Some(format!("request failed: {error}")),
            }
        }
    };

    if !response.status().is_success() {
        return FetchResult {
            success: false,
            source: "rust_static",
            content: None,
            error: Some(format!("http status {}", response.status())),
        };
    }

    let html = match response.text() {
        Ok(text) => text,
        Err(error) => {
            return FetchResult {
                success: false,
                source: "rust_static",
                content: None,
                error: Some(format!("failed to read response body: {error}")),
            }
        }
    };

    let extracted = normalize_whitespace(&extract_best_content(&html));
    if extracted.is_empty() {
        return FetchResult {
            success: false,
            source: "rust_static",
            content: None,
            error: Some("empty content".to_string()),
        };
    }

    let trimmed = trim_chars(&extracted, max_chars);
    if looks_like_blocked_page(&trimmed) {
        return FetchResult {
            success: false,
            source: "rust_static",
            content: Some(trimmed),
            error: Some("blocked page detected".to_string()),
        };
    }

    if trimmed.chars().count() < MIN_VALID_CONTENT_CHARS {
        return FetchResult {
            success: false,
            source: "rust_static",
            content: Some(trimmed),
            error: Some("content too short".to_string()),
        };
    }

    FetchResult {
        success: true,
        source: "rust_static",
        content: Some(trimmed),
        error: None,
    }
}

#[pyfunction]
#[pyo3(signature = (url, timeout=None, max_chars=None))]
fn fetch_content(url: String, timeout: Option<u64>, max_chars: Option<usize>) -> (bool, Option<String>, Option<String>) {
    let result = fetch_url(
        &url,
        timeout.unwrap_or(DEFAULT_TIMEOUT_SECONDS),
        max_chars.unwrap_or(DEFAULT_MAX_CHARS),
    );
    (result.success, result.content, result.error)
}

#[pymodule]
fn _web_fetcher_rs(_py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(fetch_content, m)?)?;
    Ok(())
}
