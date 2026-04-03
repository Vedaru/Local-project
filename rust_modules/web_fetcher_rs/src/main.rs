use std::env;
use std::process::ExitCode;

use _web_fetcher_rs::{fetch_url, DEFAULT_MAX_CHARS, DEFAULT_TIMEOUT_SECONDS};

fn print_usage() {
    eprintln!(
        "Usage: web_fetcher_rs --url <URL> [--timeout <seconds>] [--max-chars <count>]"
    );
}

fn get_flag_value(args: &[String], flag: &str) -> Option<String> {
    args.windows(2)
        .find(|window| window[0] == flag)
        .map(|window| window[1].clone())
}

fn main() -> ExitCode {
    let args: Vec<String> = env::args().collect();
    if args.iter().any(|arg| arg == "--help" || arg == "-h") {
        print_usage();
        return ExitCode::SUCCESS;
    }

    let Some(url) = get_flag_value(&args, "--url") else {
        print_usage();
        return ExitCode::from(2);
    };

    let timeout_seconds = get_flag_value(&args, "--timeout")
        .and_then(|value| value.parse::<u64>().ok())
        .unwrap_or(DEFAULT_TIMEOUT_SECONDS);

    let max_chars = get_flag_value(&args, "--max-chars")
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or(DEFAULT_MAX_CHARS);

    let result = fetch_url(&url, timeout_seconds, max_chars);
    match serde_json::to_string(&result) {
        Ok(payload) => {
            println!("{payload}");
            ExitCode::SUCCESS
        }
        Err(error) => {
            eprintln!("failed to serialize result: {error}");
            ExitCode::from(1)
        }
    }
}